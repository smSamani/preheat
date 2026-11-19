---
type: concept
title: Optimiser
description: One-hour rule, cost-minimising linear programme, matched-foresight comparator, statuses and checks.
resource: preheat/baseline.py, preheat/optimise.py
tags: [optimiser, linear-programme, HiGHS]
author: smSamani
generated:
  at: 2026-11-19
status: current
stale_after: 2027-05-18
sources:
  - id: scipy-linprog
    title: SciPy linprog documentation
    url: https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linprog.html
  - id: scipy-highs
    title: SciPy linprog HiGHS method reference
    url: https://docs.scipy.org/doc/scipy/reference/optimize.linprog-highs.html
---

# Optimiser

## One-hour rule (headline baseline)

Each hour, heat just enough to reach the next state's floor `L[t+1]`, or not at all if free-running already reaches it. It ignores prices, never looks past one hour and never aims above the floor. If it needs more than `P_MAX` it returns `infeasible` with the power it would need; the power is not clipped. This is a stated simple rule, not a model of a real thermostat.

## Cost-minimising linear programme

Decision vector `x = [p[0..23], T[1..24]]` (48 variables). One equality constraint per hour: `T[t+1] − a·T[t] − β[t]·p[t] = (1−a)(Tout[t] + g[t]/UA)` with `β = (1−a)·COP/UA`. The right-hand side of hour 0 also carries `a·T0`. Bounds: `p ∈ [0, P_MAX]`, `T[k] ∈ [L[k], ceiling]`. Objective: whole-day cost `Σ price[t]·p[t]·Δt` with `Δt = 1 h`. The terminal condition is just the ordinary floor `T[24] ≥ 20`. Solved with `linprog(method="highs")`[^scipy-linprog].

Within an hour the exact trajectory is monotone, so a constant bound met at both hour marks holds throughout that hour. Where the floor steps from 20 to 21 °C (17:00 → 18:00), only the hour marks are constrained.

## Matched-foresight comparator (diagnostic)

`solve_energy` uses the same constraints and minimises the day's electricity `Σ p[t]·Δt` without prices. Its schedule is then billed at the tariff. If several schedules tie on kWh, a second stage picks the cheapest of them, which favours the comparator. No ties occur in the fixture. The difference between its bill and the cost LP's bill isolates the gain from responding to the tariff. The difference between the one-hour rule and the cost LP mixes that gain with the LP's whole-day foresight. Results are in `diagnostics.json` ([sweep.md](sweep.md)).

## Status handling and checks

Validation runs before any solve. It rejects:

- a non-finite or boolean ceiling, or a ceiling below the highest floor;
- a start temperature above the ceiling or below 20 °C;
- non-finite parameters or hourly arrays that are not 24 long;
- non-positive `C`, `UA` or COP, or a negative `P_MAX`.

Solver status 0 is `ok`, 2 is `infeasible` (no schedule, no metrics), and anything else is `solver_error`. For `ok`, a forward replay through the same exact model must match the LP temperatures within 1e-6 and satisfy all bounds. Otherwise the status is `bound_violation` and no comparison is made.

`compare_pair` keeps `baseline_status` and `optimised_status` separately. Its top-level `status` is `ok` only when both succeed. It is `baseline_failed` when the LP finds a schedule but the one-hour rule cannot, so the bounds are reachable and only the comparator fails. In every other case it is the LP's own status, for example `infeasible`.

The evening metric is well defined at the optimal cost. Test T9 fixes the cost and minimises, then maximises, evening kWh for all 84 pairs; the two agree within 1e-5 kWh. In every published pair the two schedules end at the same temperature, so unequal terminal heat cannot explain the savings.

## Pricing one comfort limit

A custom floor vector `L` is normalised once by `floor_vector` (numbers only; strings, ragged or nested values and a wrong length raise `ValueError`, and so does a boolean anywhere in the sequence, which is checked before NumPy can turn `True` into `1`), and `validate` returns that same array, which `solve_raw`, `solve`, `solve_energy` and `compare_pair` then use for validation, solving and the forward-simulation check.

`solve_raw(day, ceiling, L)` returns the raw `linprog` result of the same cost LP, so the duals can be read. HiGHS reports marginals under the minimisation convention[^scipy-highs]: `lower.marginals >= 0` and `upper.marginals <= 0` within tolerance, and a marginal is the change in the optimal cost (€) per unit increase of that bound. The temperature at hour mark `k` sits at variable index `idx_T(k) = 23 + k`, so the 21:00 floor reads `lower.marginals[idx_T(21)]`, which is index 44. Its unit is € per K.

The precomputed example (`tighter_floor` in `diagnostics.json`, [sweep.md](sweep.md)) is the nominal day at 22.5 °C for both houses. The current house's dual is about +€0.260 per K and the better-insulated house's about +€0.248 per K. Caveats:

- The dual is a local price for a very small change. The cost is convex in the floor, so a finite step costs at least dual × step. The better-insulated house's 0.1 K step costs €0.0255 against €0.0248 from the dual.
- A bound can be active with a zero marginal (a degenerate vertex). That is allowed. The `active` field only records whether the floor binds, and a zero dual then does not mean the floor can be moved freely in larger steps.
- The answer applies to this one day and this one setting. It says nothing about a different ceiling, case or a larger change.

**Build-time check.** Generation re-solves with the 21:00 floor 0.01 K higher and compares the cost difference per K with the dual. It also re-solves 0.1 K higher for the cost shown to the user. It fails if any solve is not optimal, if the marginal signs break the convention, or if the dual and the re-solve differ by more than 1e-4 €/K. The cost LP itself is unchanged, so `results.json` is unchanged.

[^scipy-linprog]: SciPy `linprog` with `method="highs"`; status 0 optimal, 2 infeasible.
[^scipy-highs]: SciPy `linprog` HiGHS options and result fields (`lower.marginals`, `upper.marginals`).
