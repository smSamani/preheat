import math

import numpy as np
import pytest

from preheat import optimise
from preheat.baseline import baseline
from preheat.fixture import CASES, CEILINGS, ENVELOPES, day, with_pmax
from preheat.model import check_bounds, simulate
from preheat.optimise import compare_pair, solve


def all_pairs():
    return [(c, e, k) for c in CEILINGS for e in ENVELOPES for k in CASES]


def test_t4_bounds_all_pairs():
    for c, e, k in all_pairs():
        d = day(k, e)
        for r in (baseline(d, c), solve(d, c)):
            assert r.status == "ok", (c, e, k, r.reason)
            T = simulate(r.p, d)
            assert check_bounds(r.p, T, d, c) == []
            assert np.max(np.abs(T - np.array(r.T))) <= 1e-6


def test_t5_lp_never_worse():
    for c, e, k in all_pairs():
        d = day(k, e)
        assert solve(d, c).cost_eur <= baseline(d, c).cost_eur + 1e-9


def test_t6_infeasible():
    for e in ENVELOPES:
        d = with_pmax(day("nominal", e), 0.2)
        r = solve(d, 22.5)
        assert r.status == "infeasible"
        assert r.p is None and r.T is None and r.cost_eur is None and r.evening_kwh is None
        out = compare_pair(22.5, d)
        assert out["status"] == "infeasible"
        assert "avoided_kwh" not in out and "saving_eur" not in out


def test_t7_validation(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("linprog called")
    monkeypatch.setattr(optimise, "linprog", boom)
    d = day("nominal", "current")
    for bad in (20.5, float("nan"), float("inf"), True):
        with pytest.raises(ValueError):
            solve(d, bad)
    hot = type(d)(d.C, d.UA, 23.0, d.P_MAX, d.Tout, d.COP, d.g, d.price)
    with pytest.raises(ValueError):
        solve(hot, 22.5)


def test_t8_regression():
    exp = {"current": (56.3, 3.38, 0.54, 6.00, 6.61), "insulated": (81.7, 3.39, 0.55, 4.15, 4.17)}
    for e, (pct, kwh, eur, base_e, base_c) in exp.items():
        r = compare_pair(22.5, day("nominal", e))
        assert r["status"] == "ok"
        assert r["avoided_pct"] == pytest.approx(pct, abs=0.5)
        assert r["avoided_kwh"] == pytest.approx(kwh, abs=0.03)
        assert r["saving_eur"] == pytest.approx(eur, abs=0.01)
        assert r["baseline"].evening_kwh == pytest.approx(base_e, abs=0.02)
        assert r["baseline"].cost_eur == pytest.approx(base_c, abs=0.02)


def test_t9_evening_metric_well_defined():
    for e in ENVELOPES:
        d = day("nominal", e)
        opt = solve(d, 22.5)
        c, A, b, bounds = optimise.build(d, 22.5)
        cost_row = c.reshape(1, -1)
        ev = np.zeros(48)
        ev[17:22] = 1.0
        vals = []
        for sign in (1, -1):
            r = optimise.linprog(sign * ev, A_ub=cost_row, b_ub=[opt.cost_eur + 1e-7],
                                 A_eq=A, b_eq=b, bounds=bounds, method="highs")
            assert r.status == 0
            vals.append(sign * r.fun)
        assert abs(vals[0] - vals[1]) <= 1e-3
