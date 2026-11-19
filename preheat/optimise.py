"""Linear programmes over the 24 hourly heat-pump powers (HiGHS).

`solve` minimises the day's electricity cost at the tariff. `solve_energy` is a price-blind
comparator with the same whole-day foresight: it minimises the day's electricity (kWh) under
the same bounds, and its schedule is then billed at the same tariff.
"""
import math

import numpy as np
from scipy.optimize import linprog

from .baseline import baseline
from .fixture import FLOOR_BASE, floors
from .model import check_bounds, decay, energy_terms, simulate
from .result import Result

TIE_TOL_KWH = 1e-7


def _check_floors(L, day):
    if L.shape != (25,) or not np.all(np.isfinite(L)):
        raise ValueError("L must hold 25 finite floor values")
    if day.T0 < L[0]:
        raise ValueError("start temperature is below the floor L[0]")


def _has_bool(values):
    """True when a boolean sits anywhere in a (possibly nested) sequence. NumPy would coerce
    it to 0 or 1 before the dtype check sees it."""
    if isinstance(values, (bool, np.bool_)):
        return True
    if isinstance(values, (str, bytes, np.ndarray)) or not hasattr(values, "__iter__"):
        return False
    return any(_has_bool(v) for v in values)


def floor_vector(L=None):
    """The floor vector as a float array, or the standard one. Numeric types only: strings,
    booleans and ragged or nested values are rejected here, once, for every solver."""
    if L is None:
        return floors()
    if _has_bool(L):
        raise ValueError("L must hold 25 finite floor values (numbers only)")
    try:
        raw = np.asarray(L)
    except ValueError:
        raise ValueError("L must hold 25 finite floor values") from None
    if raw.dtype.kind not in "iuf":
        raise ValueError("L must hold 25 finite floor values (numbers only)")
    return raw.astype(float)


def validate(ceiling, day, L=None):
    """Check the inputs and return the floor vector every later step must use."""
    L = floor_vector(L)
    _check_floors(L, day)
    if isinstance(ceiling, bool) or not isinstance(ceiling, (int, float)) \
            or not math.isfinite(ceiling):
        raise ValueError("ceiling must be a finite number")
    if ceiling < max(L[1:]):
        raise ValueError(f"floor above ceiling: ceiling {ceiling} is below {max(L[1:])}")
    for name in ("C", "UA", "T0", "P_MAX"):
        value = getattr(day, name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number")
    for name in ("Tout", "COP", "g", "price"):
        values = np.asarray(getattr(day, name), dtype=float)
        if values.shape != (24,) or not np.all(np.isfinite(values)):
            raise ValueError(f"{name} must hold 24 finite hourly values")
    if min(day.COP) <= 0:
        raise ValueError("COP must be positive")
    if day.T0 > ceiling:
        raise ValueError("start temperature is above the ceiling")
    if day.T0 < FLOOR_BASE:
        raise ValueError(f"start temperature is below the {FLOOR_BASE:g} °C floor")
    if day.P_MAX < 0 or day.C <= 0 or day.UA <= 0:
        raise ValueError("P_MAX must be >= 0 and C, UA > 0")
    return L


def idx_T(k):
    return 23 + k


def build(day, ceiling, L=None):
    """Cost vector, dynamics (A x = b) and bounds for x = [p[0..23], T[1..24]]."""
    a = decay(day)
    L = floors() if L is None else L
    A = np.zeros((24, 48))
    b = np.zeros(24)
    for t in range(24):
        A[t, t] = -(1 - a) * day.COP[t] / day.UA
        A[t, idx_T(t + 1)] = 1.0
        if t >= 1:
            A[t, idx_T(t)] = -a
        b[t] = (1 - a) * (day.Tout[t] + day.g[t] / day.UA) + (a * day.T0 if t == 0 else 0.0)
    # Each interval is 1 h, so price[t] * p[t] is the cost of hour t in EUR.
    c = np.concatenate([np.array(day.price), np.zeros(24)])
    bounds = [(0.0, day.P_MAX)] * 24 + [(L[k], ceiling) for k in range(1, 25)]
    return c, A, b, bounds


def _finish(res, day, ceiling, L):
    """Turn a linprog result into a Result, re-checked by forward simulation."""
    if res.status == 2:
        return Result("infeasible", "no schedule satisfies the bounds within the power limit")
    if res.status != 0:
        return Result("solver_error", str(res.message))
    p = res.x[:24].copy()
    p = np.where((p < 0) & (p >= -1e-9), 0.0, p)
    T_lp = np.concatenate([[day.T0], res.x[24:]])
    T = simulate(p, day)
    viol = check_bounds(p, T, day, ceiling, L)
    if np.max(np.abs(T - T_lp)) > 1e-6:
        viol.append("forward simulation disagrees with LP temperatures")
    if viol:
        return Result("bound_violation", "; ".join(viol))
    e = energy_terms(p, T, day)
    return Result("ok", None, tuple(p), tuple(T), e["elec_kwh"], e["evening_kwh"],
                  e["cost_eur"], float(T[24]))


def solve_raw(day, ceiling, L=None):
    """The raw `linprog` result of the cost LP, for reading duals. Same problem as `solve`."""
    L = validate(ceiling, day, L)
    c, A, b, bounds = build(day, ceiling, L)
    return linprog(c, A_eq=A, b_eq=b, bounds=bounds, method="highs")


def solve(day, ceiling, L=None):
    """Cost-minimising schedule, re-checked by forward simulation of the same model."""
    L = validate(ceiling, day, L)
    c, A, b, bounds = build(day, ceiling, L)
    res = linprog(c, A_eq=A, b_eq=b, bounds=bounds, method="highs")
    return _finish(res, day, ceiling, L)


def solve_energy(day, ceiling, L=None):
    """Matched-foresight, price-blind comparator: minimise the day's kWh under the same bounds.

    Stage 1 finds the least daily electricity. If several schedules reach it, stage 2 picks the
    cheapest of them at the tariff, which favours the comparator (no ties occur in the fixture)."""
    L = validate(ceiling, day, L)
    c, A, b, bounds = build(day, ceiling, L)
    energy = np.concatenate([np.ones(24), np.zeros(24)])
    first = linprog(energy, A_eq=A, b_eq=b, bounds=bounds, method="highs")
    if first.status != 0:
        return _finish(first, day, ceiling, L)
    second = linprog(c, A_ub=energy.reshape(1, -1), b_ub=[first.fun + TIE_TOL_KWH],
                     A_eq=A, b_eq=b, bounds=bounds, method="highs")
    return _finish(second, day, ceiling, L)


def compare_pair(ceiling, day, L=None):
    """One-hour rule versus cost-minimising LP under identical bounds.

    `status` is "ok" only when both succeed. When the LP finds a schedule but the one-hour rule
    cannot, `status` is "baseline_failed": the bounds are physically reachable, only the
    comparator fails. Otherwise it is the LP's own status (e.g. "infeasible")."""
    L = validate(ceiling, day, L)
    base = baseline(day, ceiling, L)
    opt = solve(day, ceiling, L)
    if base.status != "ok" or opt.status != "ok":
        if opt.status == "ok":
            status = "baseline_failed"
            reason = ("the one-hour rule cannot meet the bounds (" + base.reason
                      + "); the cost-minimising schedule can")
        else:
            status, reason = opt.status, opt.reason
        return {"status": status, "baseline_status": base.status,
                "optimised_status": opt.status, "reason": reason}
    avoided = base.evening_kwh - opt.evening_kwh
    pct = None if base.evening_kwh < 1e-9 else 100 * avoided / base.evening_kwh
    return {"status": "ok", "baseline": base, "optimised": opt, "avoided_kwh": avoided,
            "avoided_pct": pct, "saving_eur": base.cost_eur - opt.cost_eur}
