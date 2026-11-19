"""Sweep ceilings x envelopes x cases; results.json and diagnostics.json; compare() tool."""
import json
import math

import numpy as np
import scipy

from . import fixture as fx
from .baseline import baseline
from .fixture import CASES, CEILINGS, ENVELOPES, day, floors
from .fixture import with_pmax
from .optimise import compare_pair, idx_T, solve, solve_energy, solve_raw

FORMAT = "preheat-results/1"
DIAG_FORMAT = "preheat-diagnostics/1"
LO, HI = 21.5, 24.0
STRICT_STATES = list(range(17, 23))   # stricter comfort: 21 °C at every boundary 17:00..22:00
REDUCED_P_MAX = 2.0                   # kW electrical, reduced-power diagnostic
FLOOR_HOUR = 21                       # the 21:00 evening check
FD_STEP = 0.01                        # K, finite-difference step for the floor check
FLOOR_RAISE = 0.1                     # K, the "tighter" floor shown to the user
DUAL_TOL = 1e-4                       # EUR/K, allowed gap between dual and re-solve
SIGN_TOL = 1e-9


def _r(x):
    if isinstance(x, dict):
        return {k: _r(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_r(v) for v in x]
    if isinstance(x, (float, np.floating)):
        return round(float(x), 6)
    return x


def _metrics(r):
    return {"elec_kwh": r.elec_kwh, "evening_kwh": r.evening_kwh,
            "cost_eur": r.cost_eur, "T_end_c": r.T_end}


def _record(ceiling, env, case):
    out = {"ceiling_c": ceiling, "envelope": env, "case": case}
    pair = compare_pair(ceiling, day(case, env))
    if pair["status"] != "ok":
        out.update(status=pair["status"], reason=pair["reason"],
                   baseline_status=pair["baseline_status"],
                   optimised_status=pair["optimised_status"])
        return out, pair
    out.update(status="ok", baseline=_metrics(pair["baseline"]),
               optimised=_metrics(pair["optimised"]), avoided_kwh=pair["avoided_kwh"],
               avoided_pct=pair["avoided_pct"], saving_eur=pair["saving_eur"])
    return out, pair


def _band(rows):
    """Observed min/max across the cases that solved. A case whose baseline uses no evening
    electricity has no avoided percentage but still contributes its euro saving."""
    ok = [r for r in rows if r["status"] == "ok"]
    out = {"n_cases_ok": len(ok)}
    pct = [r["avoided_pct"] for r in ok if r["avoided_pct"] is not None]
    if pct:
        out.update(avoided_pct_min=min(pct), avoided_pct_max=max(pct))
    if ok:
        out.update(saving_eur_min=min(r["saving_eur"] for r in ok),
                   saving_eur_max=max(r["saving_eur"] for r in ok))
    return out


def run():
    records, bands, example = [], [], None
    for c in CEILINGS:
        for e in ENVELOPES:
            rows = []
            for k in CASES:
                rec, pair = _record(c, e, k)
                records.append(rec)
                rows.append(rec)
                if (c, e, k) == (fx.REFERENCE_CEILING, "current", "nominal") and rec["status"] == "ok":
                    example = pair
            bands.append({"ceiling_c": c, "envelope": e, **_band(rows)})
    d = day("nominal", "current")
    ex = None
    if example is not None:
        ex = {"ceiling_c": fx.REFERENCE_CEILING, "envelope": "current", "case": "nominal",
              "hours": list(range(24)),
              "p_baseline_kw": example["baseline"].p, "p_optimised_kw": example["optimised"].p,
              "T_baseline_c": example["baseline"].T, "T_optimised_c": example["optimised"].T,
              "floor_c": [d.T0] + list(floors()[1:]), "price_eur_per_kwh": d.price}
    inf = {"p_max_kw": 0.2}
    for e in ENVELOPES:
        inf[e] = solve(with_pmax(day("nominal", e), 0.2), 22.5).status
    return _r({
        "format": FORMAT, "synthetic": True,
        "fixture": {
            "T0_c": fx.T0, "p_max_kw": fx.P_MAX, "C_kwh_per_k": fx.C_NOMINAL,
            "UA_kw_per_k": ENVELOPES,
            "price_eur_per_kwh": {"normal": fx.PRICE_NORMAL, "evening": fx.PRICE_EVENING},
            "evening_hours": list(fx.EVENING), "floor_c": fx.FLOOR_BASE,
            "evening_floor_c": fx.FLOOR_EVE, "evening_check_states": sorted(fx.EVE_CHECK_K),
            "outdoor_c": {"night": 2.0, "day_09_17": 6.0},
            "gains_kw": {"normal": 0.2, "evening": 0.5},
            "cop": "clip(3 + 0.05*(Tout - 5), 2, 4)",
            "ceilings_c": CEILINGS, "cases": CASES},
        "solver": {"name": "scipy.optimize.linprog", "method": "highs",
                   "scipy_version": scipy.__version__},
        "records": records, "bands": bands, "example_day": ex, "infeasible_check": inf})


def dumps(results):
    return json.dumps(results, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def strict_floors():
    """Floors with 21 °C at every hourly boundary from 17:00 to 22:00 (diagnostic only)."""
    L = floors().astype(float)
    L[STRICT_STATES] = fx.FLOOR_EVE
    return L


def _pair_summary(pair):
    if pair["status"] != "ok":
        return {"status": pair["status"], "reason": pair["reason"],
                "baseline_status": pair["baseline_status"],
                "optimised_status": pair["optimised_status"]}
    return {"status": "ok", "baseline": _metrics(pair["baseline"]),
            "optimised": _metrics(pair["optimised"]), "avoided_kwh": pair["avoided_kwh"],
            "avoided_pct": pair["avoided_pct"], "saving_eur": pair["saving_eur"]}


def _raised(L, hour, by):
    out = np.array(L, dtype=float)
    out[hour] += by
    return out


def tighter_floor():
    """Cost of a warmer 21:00 minimum, nominal day at the reference ceiling, both houses.

    The LP's dual on the 21:00 lower bound (EUR per K) is compared with a re-solve whose floor
    is 0.01 K higher. Generation fails if a solve is not optimal, if the HiGHS sign convention
    (minimisation: lower marginals >= 0, upper marginals <= 0) does not hold, or if the dual and
    the re-solve disagree. A zero marginal on an active bound is allowed and recorded."""
    L = floors().astype(float)
    k = FLOOR_HOUR
    rows = []
    for e in ENVELOPES:
        d = day("nominal", e)
        base = solve_raw(d, fx.REFERENCE_CEILING, L)
        step = solve_raw(d, fx.REFERENCE_CEILING, _raised(L, k, FD_STEP))
        plus = solve_raw(d, fx.REFERENCE_CEILING, _raised(L, k, FLOOR_RAISE))
        for name, res in (("base", base), ("+0.01", step), ("+0.1", plus)):
            if res.status != 0:
                raise RuntimeError(f"tighter_floor: {e} {name} solve failed: {res.message}")
        if base.lower.marginals.min() < -SIGN_TOL or base.upper.marginals.max() > SIGN_TOL:
            raise RuntimeError(f"tighter_floor: {e} marginals break the minimisation sign convention")
        dual = float(base.lower.marginals[idx_T(k)])
        fd = (step.fun - base.fun) / FD_STEP
        agree = abs(dual - fd) <= DUAL_TOL
        if not agree:
            raise RuntimeError(f"tighter_floor: {e} dual {dual:.6f} and re-solve {fd:.6f} differ")
        rows.append({"envelope": e, "hour": k, "floor_c": float(L[k]),
                     "cost_base": float(base.fun), "cost_plus_0_1": float(plus.fun),
                     "fd_eur_per_k": fd, "dual_eur_per_k": dual,
                     "active": bool(abs(base.x[idx_T(k)] - L[k]) <= 1e-7), "agree": agree})
    return {
        "description": (f"Nominal day at {fx.REFERENCE_CEILING} °C. Daily cost of the cost LP when "
                        f"the {k}:00 minimum is {FLOOR_RAISE:g} K warmer, and the LP's dual value "
                        f"for that minimum (EUR per K) checked against a re-solve {FD_STEP:g} K "
                        "higher. Local to this one day and setting."),
        "ceiling_c": fx.REFERENCE_CEILING, "case": "nominal",
        "raise_k": FLOOR_RAISE, "rows": rows}


def diagnostics():
    """Named checks kept apart from the 84-record sweep and its bands (nominal case only)."""
    matched = []
    for c in CEILINGS:
        for e in ENVELOPES:
            d = day("nominal", e)
            rule, energy_lp, cost_lp = baseline(d, c), solve_energy(d, c), solve(d, c)
            row = {"ceiling_c": c, "envelope": e, "rule_status": rule.status,
                   "energy_lp_status": energy_lp.status, "cost_lp_status": cost_lp.status}
            if cost_lp.status == "ok" and energy_lp.status == "ok":
                row.update(energy_lp=_metrics(energy_lp), cost_lp=_metrics(cost_lp),
                           saving_vs_energy_lp_eur=energy_lp.cost_eur - cost_lp.cost_eur,
                           evening_avoided_vs_energy_lp_kwh=(energy_lp.evening_kwh
                                                             - cost_lp.evening_kwh))
            if cost_lp.status == "ok" and rule.status == "ok":
                row.update(rule=_metrics(rule),
                           saving_vs_rule_eur=rule.cost_eur - cost_lp.cost_eur)
            matched.append(row)
    strict = [{"ceiling_c": c, "envelope": e,
               **_pair_summary(compare_pair(c, day("nominal", e), strict_floors()))}
              for c in CEILINGS for e in ENVELOPES]
    reduced = []
    for e in ENVELOPES:
        d = with_pmax(day("nominal", e), REDUCED_P_MAX)
        rule, cost_lp = baseline(d, fx.REFERENCE_CEILING), solve(d, fx.REFERENCE_CEILING)
        row = {"envelope": e, "rule_status": rule.status, "rule_reason": rule.reason,
               "cost_lp_status": cost_lp.status,
               "pair_status": compare_pair(fx.REFERENCE_CEILING, d)["status"]}
        if cost_lp.status == "ok":
            row["cost_lp"] = _metrics(cost_lp)
        reduced.append(row)
    return _r({
        "format": DIAG_FORMAT, "synthetic": True, "case": "nominal",
        "note": ("Diagnostics only. They are not part of the 84 sweep records or the "
                 "sensitivity bands in results.json."),
        "matched_foresight": {
            "description": ("Price-blind LP with the same whole-day foresight and bounds as the "
                            "cost LP, minimising the day's electricity (kWh), then billed at the "
                            "same tariff. saving_vs_energy_lp_eur isolates the gain from "
                            "responding to the tariff."),
            "rows": matched},
        "strict_evening_comfort": {
            "description": ("21 °C required at every hourly boundary from 17:00 to 22:00 "
                            "instead of 18:00 to 21:00 only; one-hour rule vs cost LP."),
            "floor_states": STRICT_STATES, "rows": strict},
        "reduced_power": {
            "description": (f"Heat pump limited to {REDUCED_P_MAX:g} kW electrical at "
                            f"{fx.REFERENCE_CEILING} °C."),
            "p_max_kw": REDUCED_P_MAX, "ceiling_c": fx.REFERENCE_CEILING, "rows": reduced},
        "tighter_floor": tighter_floor(),
    })


def write(results, path="results.json"):
    with open(path, "w", encoding="utf-8") as f:
        f.write(dumps(results))


def compare(ceiling_c):
    """The one tool the language layer may call. Same code path as the sweep."""
    if isinstance(ceiling_c, bool) or not isinstance(ceiling_c, (int, float)) \
            or not math.isfinite(ceiling_c) or not LO <= ceiling_c <= HI:
        return {"status": "invalid", "ceiling_c": ceiling_c,
                "reason": f"maximum must be a number between {LO} and {HI} °C"}
    v = round(float(ceiling_c), 1)
    envs = {}
    for e in ENVELOPES:
        rows, nominal = [], None
        for k in CASES:
            rec, _ = _record(v, e, k)
            rows.append(rec)
            if k == "nominal":
                nominal = rec
        if nominal["status"] != "ok":
            envs[e] = {"status": nominal["status"], "reason": nominal["reason"]}
            continue
        envs[e] = {"status": "ok",
                   "baseline_evening_kwh": nominal["baseline"]["evening_kwh"],
                   "optimised_evening_kwh": nominal["optimised"]["evening_kwh"],
                   "avoided_kwh": nominal["avoided_kwh"], "avoided_pct": nominal["avoided_pct"],
                   "baseline_cost_eur": nominal["baseline"]["cost_eur"],
                   "optimised_cost_eur": nominal["optimised"]["cost_eur"],
                   "saving_eur": nominal["saving_eur"], "case_range": _band(rows)}
    return {"status": "ok", "ceiling_c": v, "synthetic": True, "envelopes": envs}
