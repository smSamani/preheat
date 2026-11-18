"""Cost-minimising schedule as a linear programme (HiGHS)."""
import math

import numpy as np
from scipy.optimize import linprog

from .baseline import baseline
from .fixture import floors
from .model import check_bounds, decay, energy_terms, simulate
from .result import Result


def validate(ceiling, day):
    if isinstance(ceiling, bool) or not isinstance(ceiling, (int, float)) \
            or not math.isfinite(ceiling):
        raise ValueError("ceiling must be a finite number")
    if ceiling < max(floors()[1:]):
        raise ValueError(f"floor above ceiling: ceiling {ceiling} is below {max(floors()[1:])}")
    if day.T0 > ceiling:
        raise ValueError("start temperature is above the ceiling")
    if day.P_MAX < 0 or day.C <= 0 or day.UA <= 0:
        raise ValueError("P_MAX must be >= 0 and C, UA > 0")


def idx_T(k):
    return 23 + k


def build(day, ceiling):
    a = decay(day)
    L = floors()
    A = np.zeros((24, 48))
    b = np.zeros(24)
    for t in range(24):
        A[t, t] = -(1 - a) * day.COP[t] / day.UA
        A[t, idx_T(t + 1)] = 1.0
        if t >= 1:
            A[t, idx_T(t)] = -a
        b[t] = (1 - a) * (day.Tout[t] + day.g[t] / day.UA) + (a * day.T0 if t == 0 else 0.0)
    c = np.concatenate([np.array(day.price), np.zeros(24)])
    bounds = [(0.0, day.P_MAX)] * 24 + [(L[k], ceiling) for k in range(1, 25)]
    return c, A, b, bounds


def solve(day, ceiling):
    """Solve the LP and re-check the schedule by forward simulation."""
    validate(ceiling, day)
    c, A, b, bounds = build(day, ceiling)
    res = linprog(c, A_eq=A, b_eq=b, bounds=bounds, method="highs")
    if res.status == 2:
        return Result("infeasible", "no schedule satisfies the bounds")
    if res.status != 0:
        return Result("solver_error", str(res.message))
    p = res.x[:24].copy()
    p = np.where((p < 0) & (p >= -1e-9), 0.0, p)
    T_lp = np.concatenate([[day.T0], res.x[24:]])
    T = simulate(p, day)
    viol = check_bounds(p, T, day, ceiling)
    if np.max(np.abs(T - T_lp)) > 1e-6:
        viol.append("forward simulation disagrees with LP temperatures")
    if viol:
        return Result("bound_violation", "; ".join(viol))
    e = energy_terms(p, T, day)
    return Result("ok", None, tuple(p), tuple(T), e["elec_kwh"], e["evening_kwh"],
                  e["cost_eur"], float(T[24]))


def compare_pair(ceiling, day):
    validate(ceiling, day)
    base = baseline(day, ceiling)
    opt = solve(day, ceiling)
    if base.status != "ok" or opt.status != "ok":
        first = base if base.status != "ok" else opt
        return {"status": first.status, "baseline_status": base.status,
                "optimised_status": opt.status, "reason": first.reason}
    avoided = base.evening_kwh - opt.evening_kwh
    pct = None if base.evening_kwh < 1e-9 else 100 * avoided / base.evening_kwh
    return {"status": "ok", "baseline": base, "optimised": opt, "avoided_kwh": avoided,
            "avoided_pct": pct, "saving_eur": base.cost_eur - opt.cost_eur}
