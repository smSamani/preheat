"""Synthetic fixture: one fictional heat-pump home on one synthetic winter day.

Everything here is invented for illustration. Nothing is downloaded or measured.
"""
from dataclasses import dataclass, replace

import numpy as np

T0 = 20.0                      # degC at 00:00
P_MAX = 4.0                    # kW electrical, continuous 0..P_MAX
C_NOMINAL = 4.0                # kWh/K
ENVELOPES = {"current": 0.20, "insulated": 0.13}   # UA in kW/K; nothing else differs
EVENING = range(17, 22)        # hours starting 17..21 (same as the high price)
CEILINGS = [21.5, 22.0, 22.5, 23.0, 23.5, 24.0]
FLOOR_BASE = 20.0
FLOOR_EVE = 21.0
EVE_CHECK_K = {18, 19, 20, 21}
REFERENCE_CEILING = 22.5
PRICE_NORMAL = 0.22
PRICE_EVENING = 0.38
CASES = ["nominal", "outdoor_minus3", "outdoor_plus3", "capacity_3", "capacity_8",
         "gains_x0.5", "gains_x1.5"]
CASE_LABELS = {
    "nominal": "Nominal",
    "outdoor_minus3": "Colder day (-3 °C)",
    "outdoor_plus3": "Milder day (+3 °C)",
    "capacity_3": "Lighter house (C = 3 kWh/K)",
    "capacity_8": "Heavier house (C = 8 kWh/K)",
    "gains_x0.5": "Half internal gains",
    "gains_x1.5": "1.5x internal gains",
}


@dataclass(frozen=True)
class Day:
    C: float
    UA: float
    T0: float
    P_MAX: float
    Tout: tuple
    COP: tuple
    g: tuple
    price: tuple


def cop_curve(tout):
    return np.clip(3.0 + 0.05 * (np.asarray(tout, dtype=float) - 5.0), 2.0, 4.0)


def floors():
    """L[k] for k = 0..24 (index 0 unused, equal to the start floor)."""
    return np.array([FLOOR_EVE if k in EVE_CHECK_K else FLOOR_BASE for k in range(25)])


def day(case="nominal", envelope="current"):
    if case not in CASES:
        raise ValueError(f"unknown case {case!r}")
    tout = np.array([6.0 if 9 <= t < 17 else 2.0 for t in range(24)])
    g = np.array([0.5 if 17 <= t < 22 else 0.2 for t in range(24)])
    price = np.array([PRICE_EVENING if 17 <= t <= 21 else PRICE_NORMAL for t in range(24)])
    C = C_NOMINAL
    if case == "outdoor_minus3":
        tout = tout - 3.0
    elif case == "outdoor_plus3":
        tout = tout + 3.0
    elif case == "capacity_3":
        C = 3.0
    elif case == "capacity_8":
        C = 8.0
    elif case == "gains_x0.5":
        g = g * 0.5
    elif case == "gains_x1.5":
        g = g * 1.5
    return Day(C=C, UA=ENVELOPES[envelope], T0=T0, P_MAX=P_MAX, Tout=tuple(tout),
               COP=tuple(cop_curve(tout)), g=tuple(g), price=tuple(price))


def with_pmax(d, p_max):
    return replace(d, P_MAX=p_max)
