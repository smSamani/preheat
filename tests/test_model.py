import math

import numpy as np

from preheat.baseline import baseline
from preheat.fixture import day, with_pmax
from preheat.model import energy_terms, simulate, step
from preheat.optimise import solve


def test_t1_no_heat_decay():
    for env in ("current", "insulated"):
        d = day("nominal", env)
        d = type(d)(d.C, d.UA, d.T0, d.P_MAX, (2.0,) * 24, d.COP, (0.0,) * 24, d.price)
        T = simulate(np.zeros(24), d)
        for k in range(25):
            assert abs(T[k] - (2 + (d.T0 - 2) * math.exp(-d.UA * k / d.C))) <= 1e-12


def test_t2_exact_vs_euler(nominal):
    _, d = nominal
    p = baseline(d, 22.5).p
    T_exact = simulate(p, d)
    T, worst = d.T0, 0.0
    n = 3600
    h = 1.0 / n
    for t in range(24):
        for _ in range(n):
            T += h * (d.COP[t] * p[t] + d.g[t] - d.UA * (T - d.Tout[t])) / d.C
        worst = max(worst, abs(T - T_exact[t + 1]))
    assert worst <= 1e-3


def test_t3_energy_balance(nominal):
    _, d = nominal
    for r in (baseline(d, 22.5), solve(d, 22.5)):
        e = energy_terms(r.p, r.T, d)
        assert abs(e["residual"]) <= 1e-9
