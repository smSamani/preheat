---
type: concept
title: Optimiser
description: Price-blind baseline and the cost-minimising linear programme with its forward check.
resource: preheat/baseline.py, preheat/optimise.py
tags: [optimiser, linear-programme, HiGHS]
generated:
  by: human:smSamani
  at: 2026-11-18
status: current
stale_after: 2027-05-18
sources:
  - id: scipy-linprog
    title: SciPy linprog documentation
    url: https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linprog.html
---

# Optimiser

## Baseline

Each hour, heat just enough to reach the next state's floor `L[t+1]`, or not at all if free-running already reaches it. It ignores prices, never looks past one hour and never aims above the floor. If it needs more than `P_MAX` it is reported infeasible; the power is not clipped.

## Linear programme

Decision vector `x = [p[0..23], T[1..24]]` (48 variables). Equality constraints, one per hour: `T[t+1] − a·T[t] − β[t]·p[t] = (1−a)(Tout[t] + g[t]/UA)` with `β = (1−a)·COP/UA`; the right-hand side of hour 0 also carries `a·T0`. Bounds: `p ∈ [0, P_MAX]`, `T[k] ∈ [L[k], ceiling]`. Objective: whole-day cost `Σ price[t]·p[t]`. Solved with `linprog(method="highs")`[^scipy-linprog].

## Status handling and checks

Validation runs before any solve (non-finite or boolean ceiling, ceiling below 21 °C, start above ceiling, non-positive parameters). Solver status 0 is `ok`, 2 is `infeasible` (no schedule, no metrics), anything else `solver_error`. For `ok`, a forward simulation must match the LP temperatures within 1e-6 and satisfy all bounds, otherwise the status is `bound_violation` and no comparison is made.

The evening metric is well defined at the optimal cost: test T9 fixes the cost and minimises then maximises evening kWh; the two agree within 1e-3 kWh.

[^scipy-linprog]: SciPy `linprog` with `method="highs"`; status 0 optimal, 2 infeasible.
