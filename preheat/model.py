"""Single-zone 1R1C model with an exact hourly update."""
import math

import numpy as np

from .fixture import EVENING, floors

TOL_P = 1e-9
TOL_T = 1e-6


def decay(day):
    return math.exp(-day.UA * 1.0 / day.C)


def step(T, p, day, t):
    a = decay(day)
    teq = day.Tout[t] + (day.COP[t] * p + day.g[t]) / day.UA
    return a * T + (1 - a) * teq


def simulate(p, day):
    T = np.zeros(25)
    T[0] = day.T0
    for t in range(24):
        T[t + 1] = step(T[t], p[t], day, t)
    return T


def check_bounds(p, T, day, ceiling, L=None):
    """Human-readable violations; empty list if the schedule is fine.

    L is the floor for each state k = 0..24 (default: the fixture's floors)."""
    out = []
    L = floors() if L is None else L
    p, T = np.asarray(p, dtype=float), np.asarray(T, dtype=float)
    if p.shape != (24,) or T.shape != (25,):
        return [f"expected 24 powers and 25 temperatures, got {p.shape} and {T.shape}"]
    if not (np.all(np.isfinite(p)) and np.all(np.isfinite(T))):
        return ["schedule contains a non-finite value"]
    for t in range(24):
        if p[t] < -TOL_P or p[t] > day.P_MAX + TOL_P:
            out.append(f"power {p[t]:.4f} kW outside 0..{day.P_MAX} at hour {t}")
    for k in range(1, 25):
        if T[k] < L[k] - TOL_T:
            out.append(f"T[{k}]={T[k]:.4f} below floor {L[k]}")
        if T[k] > ceiling + TOL_T:
            out.append(f"T[{k}]={T[k]:.4f} above ceiling {ceiling}")
    return out


def energy_terms(p, T, day):
    """Per-hour energy balance over the exact trajectory, and the reported metrics.

    Every interval is one hour, so kW x 1 h = kWh: sum(p) is the day's electricity in kWh and
    sum(price * p) its cost in EUR."""
    a = decay(day)
    tau = day.C / day.UA
    net = 0.0
    for t in range(24):
        teq = day.Tout[t] + (day.COP[t] * p[t] + day.g[t]) / day.UA
        integral = teq + (T[t] - teq) * tau * (1 - a)
        loss = day.UA * (integral - day.Tout[t])
        net += day.COP[t] * p[t] + day.g[t] - loss
    stored = day.C * (T[24] - T[0])
    return {
        "residual": stored - net,
        "elec_kwh": float(sum(p)),
        "evening_kwh": float(sum(p[t] for t in EVENING)),
        "cost_eur": float(sum(day.price[t] * p[t] for t in range(24))),
    }
