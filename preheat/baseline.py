"""Price-blind one-hour rule: each hour heat just enough to reach the next state's floor.

It looks one hour ahead only and never aims above the floor. It is a simple stated rule,
not a model of a real thermostat. See `optimise.solve_energy` for a price-blind comparator
that has the same whole-day foresight as the cost-minimising LP.
"""
import numpy as np

from .fixture import floors
from .model import check_bounds, decay, energy_terms, simulate, step
from .result import Result


def baseline(day, ceiling, L=None):
    L = floors() if L is None else L
    a = decay(day)
    p = np.zeros(24)
    T = np.zeros(25)
    T[0] = day.T0
    for t in range(24):
        t_free = a * T[t] + (1 - a) * (day.Tout[t] + day.g[t] / day.UA)
        if t_free < L[t + 1]:
            p[t] = (L[t + 1] - t_free) * day.UA / ((1 - a) * day.COP[t])
            if p[t] > day.P_MAX + 1e-12:
                return Result("infeasible", f"the one-hour rule needs {p[t]:.2f} kW at hour {t}, "
                                            f"above the {day.P_MAX:g} kW limit")
        T[t + 1] = step(T[t], p[t], day, t)
    viol = check_bounds(p, T, day, ceiling, L)
    if viol:
        return Result("bound_violation", "; ".join(viol))
    e = energy_terms(p, T, day)
    return Result("ok", None, tuple(p), tuple(simulate(p, day)),
                  e["elec_kwh"], e["evening_kwh"], e["cost_eur"], float(T[24]))
