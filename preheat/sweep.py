"""Sweep ceilings x envelopes x cases; results.json writer; compare() tool."""
import json
import math

import numpy as np
import scipy

from . import fixture as fx
from .fixture import CASES, CEILINGS, ENVELOPES, day, floors
from .fixture import with_pmax
from .optimise import compare_pair, solve

FORMAT = "preheat-results/1"
LO, HI = 21.5, 24.0


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
        out.update(status=pair["status"], reason=pair["reason"])
        return out, pair
    out.update(status="ok", baseline=_metrics(pair["baseline"]),
               optimised=_metrics(pair["optimised"]), avoided_kwh=pair["avoided_kwh"],
               avoided_pct=pair["avoided_pct"], saving_eur=pair["saving_eur"])
    return out, pair


def _band(rows):
    ok = [r for r in rows if r["status"] == "ok" and r["avoided_pct"] is not None]
    return {"avoided_pct_min": min(r["avoided_pct"] for r in ok),
            "avoided_pct_max": max(r["avoided_pct"] for r in ok),
            "saving_eur_min": min(r["saving_eur"] for r in ok),
            "saving_eur_max": max(r["saving_eur"] for r in ok),
            "n_cases_ok": len(ok)} if ok else {"n_cases_ok": 0}


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
