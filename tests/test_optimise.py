import math

import numpy as np
import pytest

from preheat import optimise
from preheat.baseline import baseline
from preheat import fixture as fx
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
        assert out["baseline_status"] == "infeasible" and out["optimised_status"] == "infeasible"
        assert "avoided_kwh" not in out and "saving_eur" not in out


def test_comparator_failure_is_not_reported_as_physical_infeasibility():
    # At 2 kW the one-hour rule fails in the evening, but a feasible schedule exists.
    for e in ENVELOPES:
        d = with_pmax(day("nominal", e), 2.0)
        out = compare_pair(22.5, d)
        assert out["status"] == "baseline_failed"
        assert out["baseline_status"] == "infeasible" and out["optimised_status"] == "ok"
        assert "one-hour rule" in out["reason"]


def test_t7_validation(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("linprog called")
    monkeypatch.setattr(optimise, "linprog", boom)
    d = day("nominal", "current")
    for bad in (20.5, float("nan"), float("inf"), True):
        with pytest.raises(ValueError):
            solve(d, bad)
    hot = type(d)(d.C, d.UA, 23.0, d.P_MAX, d.Tout, d.COP, d.g, d.price)
    cold = type(d)(d.C, d.UA, 19.9, d.P_MAX, d.Tout, d.COP, d.g, d.price)
    short = type(d)(d.C, d.UA, d.T0, d.P_MAX, d.Tout[:23], d.COP, d.g, d.price)
    nan = type(d)(d.C, d.UA, d.T0, d.P_MAX, d.Tout, d.COP, (float("nan"),) * 24, d.price)
    for bad_day in (hot, cold, short, nan):
        with pytest.raises(ValueError):
            solve(bad_day, 22.5)


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
    # At the optimal cost, the evening kWh is unique: no tied schedule shifts it.
    for c_, e, k in all_pairs():
        d = day(k, e)
        opt = solve(d, c_)
        c, A, b, bounds = optimise.build(d, c_)
        cost_row = c.reshape(1, -1)
        ev = np.zeros(48)
        ev[17:22] = 1.0
        vals = []
        for sign in (1, -1):
            r = optimise.linprog(sign * ev, A_ub=cost_row, b_ub=[opt.cost_eur + 1e-7],
                                 A_eq=A, b_eq=b, bounds=bounds, method="highs")
            assert r.status == 0
            vals.append(sign * r.fun)
        assert abs(vals[0] - vals[1]) <= 1e-5, (c_, e, k)


def test_check_bounds_rejects_non_finite_schedules():
    d = day("nominal", "current")
    assert check_bounds(np.full(24, np.nan), np.full(25, np.nan), d, 22.5)
    assert check_bounds(np.zeros(24), np.full(25, 21.0), d, 22.5) == []


def test_tariff_and_evening_window_match():
    # The expensive price applies to the hours starting 17:00..21:00, the same hours that the
    # evening kWh metric sums; the 21 °C floor applies to the states at 18:00..21:00.
    for e in ENVELOPES:
        d = day("nominal", e)
        expensive = [t for t in range(24) if d.price[t] > min(d.price)]
        assert expensive == list(fx.EVENING) == [17, 18, 19, 20, 21]
    L = fx.floors()
    assert [k for k in range(25) if L[k] > fx.FLOOR_BASE] == [18, 19, 20, 21]


def test_paired_schedules_end_at_the_same_temperature():
    # Unequal terminal heat cannot explain the savings in the published pairs.
    for c, e, k in all_pairs():
        pair = compare_pair(c, day(k, e))
        assert abs(pair["baseline"].T_end - pair["optimised"].T_end) <= 1e-6, (c, e, k)


def test_matched_foresight_comparator():
    for c in CEILINGS:
        for e in ENVELOPES:
            d = day("nominal", e)
            rule, energy_lp, cost_lp = baseline(d, c), optimise.solve_energy(d, c), solve(d, c)
            assert energy_lp.status == "ok"
            assert check_bounds(energy_lp.p, simulate(energy_lp.p, d), d, c) == []
            assert energy_lp.elec_kwh <= min(rule.elec_kwh, cost_lp.elec_kwh) + 1e-7
            assert cost_lp.cost_eur <= energy_lp.cost_eur + 1e-9


# --- Floor vector is normalised once -------------------------------------------------------

def _floors_as(kind):
    L = list(fx.floors())
    return {"strings": [str(v) for v in L], "bools": [True] * 25, "nested": [L],
            "mixed_bool": [True] + [20] * 24, "mixed_bool_last": [20] * 24 + [False],
            "numpy_bool": [np.True_] + [20] * 24, "nested_bool": [[True] + [20] * 24],
            "short": L[:24], "ragged": [L[:3], L[3:]], "none_inside": L[:24] + [None],
            "nan": L[:24] + [float("nan")]}[kind]


@pytest.mark.parametrize("kind", ["strings", "bools", "mixed_bool", "mixed_bool_last", "numpy_bool",
                                  "nested_bool", "nested", "short", "ragged",
                                  "none_inside", "nan"])
def test_every_solver_rejects_a_bad_floor_vector_the_same_way(kind):
    d, bad = day("nominal", "current"), _floors_as(kind)
    calls = (lambda: optimise.solve_raw(d, 23.0, bad), lambda: optimise.solve(d, 23.0, bad),
             lambda: optimise.solve_energy(d, 23.0, bad), lambda: compare_pair(23.0, d, bad))
    for call in calls:
        with pytest.raises(ValueError, match="L must hold 25 finite floor values"):
            call()


def test_a_numeric_floor_vector_gives_the_same_answer_as_an_array():
    d = day("nominal", "current")
    L = fx.floors()
    for variant in (list(L), tuple(L), np.asarray(L, dtype=np.float32).astype(float)):
        assert optimise.solve(d, 23.0, variant).cost_eur == optimise.solve(d, 23.0, L).cost_eur
    assert optimise.solve_raw(d, 23.0, list(L)).fun == optimise.solve_raw(d, 23.0, L).fun
    assert optimise.solve(d, 23.0).cost_eur == optimise.solve(d, 23.0, L).cost_eur


def test_validate_returns_the_vector_the_solvers_use():
    d = day("nominal", "current")
    out = optimise.validate(23.0, d, list(fx.floors()))
    assert isinstance(out, np.ndarray) and out.dtype == float and out.shape == (25,)
