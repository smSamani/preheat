from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Result:
    status: str                      # ok | infeasible | solver_error | bound_violation
    reason: Optional[str] = None
    p: Optional[tuple] = None        # 24 values, None unless ok
    T: Optional[tuple] = None        # 25 values from forward simulation
    elec_kwh: Optional[float] = None
    evening_kwh: Optional[float] = None
    cost_eur: Optional[float] = None
    T_end: Optional[float] = None
