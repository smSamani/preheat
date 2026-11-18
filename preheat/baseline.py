"""Price-blind rule: each hour heat just enough to reach the next state's floor."""
import numpy as np

from .fixture import floors
from .model import check_bounds, decay, energy_terms, simulate, step
from .result import Result


def baseline(day, ceiling):
    L = floors()
    a = decay(day)
    p = np.zeros(24)
    T = np.zeros(25)
    T[0] = day.T0
    for t in range(24):
        t_free = a * T[t] + (1 - a) * (day.Tout[t] + day.g[t] / day.UA)
        if t_free < L[t + 1]:
            p[t] = (L[t + 1] - t_free) * day.UA / ((1 - a) * day.COP[t])
            if p[t] > day.P_MAX + 1e-12:
                return Result("infeasible", f"baseline needs {p[t]:.2f} kW at hour {t}")
        T[t + 1] = step(T[t], p[t], day, t)
    viol = check_bounds(p, T, day, ceiling)
    if viol:
        return Result("bound_violation", "; ".join(viol))
    e = energy_terms(p, T, day)
    return Result("ok", None, tuple(p), tuple(simulate(p, day)),
                  e["elec_kwh"], e["evening_kwh"], e["cost_eur"], float(T[24]))
