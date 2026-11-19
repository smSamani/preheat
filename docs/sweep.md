---
type: concept
title: Sweep and outputs
description: 84-pair sweep, results.json schema, separate diagnostics.json and the two figures.
resource: preheat/sweep.py, preheat/plot.py, results.json, diagnostics.json
tags: [sweep, results, figures]
author: smSamani
generated:
  at: 2026-11-19
status: current
stale_after: 2027-05-18
sources: []
---

# Sweep

Six ceilings (21.5 to 24 °C in 0.5 °C steps) × two envelopes × seven cases = 84 pairs, each solved and forward-checked. Order: ceilings ascending, envelopes `current` then `insulated`, cases as listed in [model.md](model.md).

`results.json` (format `preheat-results/1`) holds:

- the fixture and the solver version;
- one record per pair;
- per-ceiling bands;
- an `example_day` block (`null` if the reference case fails; `plot.example_day` then prints a one-line notice and writes nothing, so a stale figure is neither refreshed nor deleted);
- an `infeasible_check`.

Floats are rounded to six decimals and there are no timestamps. With the pinned NumPy and SciPy, reruns are byte-identical, and a test compares the committed files with a fresh run. Another solver build may differ in the last digits.

Bands are the observed minimum and maximum across the cases that solved: a sensitivity range, not probabilities. Each case is solved with perfect knowledge of its own day, so the bands say nothing about forecast error. A case whose one-hour rule uses no evening electricity has no avoided percentage. It still counts towards the euro band and `n_cases_ok`. Non-`ok` records carry `status`, `reason`, `baseline_status` and `optimised_status` only.

## Metrics

- `avoided_kwh`: one-hour-rule minus LP electricity in the hours starting 17:00 to 21:00.
- `avoided_pct`: `avoided_kwh` as a share of that house's own one-hour-rule evening kWh. Houses with different starting kWh have different denominators, so always read it with the kWh.
- `saving_eur`: difference in whole-day heat-pump electricity cost.
- `elec_kwh`: the whole day's electricity. Over the 84 pairs it is lower with the optimised schedule than with the one-hour rule in 54 and higher in 30, so it can rise while the bill falls (for the nominal current house from 23.0 °C upwards).

## Diagnostics (`diagnostics.json`)

Format `preheat-diagnostics/1`, nominal case only. The `tighter_floor` block was added with the language layer; the other blocks are unchanged. These checks are kept apart from the 84 records and the bands:

- `matched_foresight`: for every ceiling and envelope, the price-blind kWh-minimising LP ([optimiser.md](optimiser.md)) billed at the tariff, against the cost LP. At 22.5 °C the extra saving from responding to the tariff is €0.13 (current) and €0.10 (insulated), compared with €0.54 and €0.55 against the one-hour rule.
- `strict_evening_comfort`: 21 °C at every hour mark from 17:00 to 22:00 instead of 18:00 to 21:00 only. At 22.5 °C the avoided share falls to 34.7% and 58.1%.
- `reduced_power`: a 2 kW cap at 22.5 °C. The one-hour rule fails in the evening, but the LP still finds a schedule, so the status is `baseline_failed`.
- `tighter_floor`: what a warmer 21:00 minimum costs, nominal day at 22.5 °C, both houses. Each row has the base daily cost, the cost with the floor 0.1 K higher (`cost_plus_0_1`), the LP dual of the 21:00 floor (`dual_eur_per_k`, about 0.260 for the current house and 0.248 for the better-insulated one), a re-solve 0.01 K higher (`fd_eur_per_k`), whether the bound is `active` and whether the two `agree` (within 1e-4 €/K; generation fails otherwise). See [optimiser.md](optimiser.md). It is local to one day and one setting and feeds the `tighter_floor` explain topic.

## Figures

`figures/flex_curve.png` has two panels:

- the avoided share compared with the one-hour rule;
- euros saved per day, with dashed lines for the saving compared with the matched-foresight comparator.

Band edges are drawn as dotted lines, and the 22.5 °C reference line is labelled. The caption numbers are read from the records, and missing metrics are drawn as gaps.

`figures/example_day.png` shows the current house at 22.5 °C:

- temperature, the allowed range and hourly power;
- the one-hour rule labelled as such;
- a legend on both panels.

The allowed range joins the hourly bound points, the same way as the temperature lines, because bounds are only checked at those points.

`compare(ceiling_c)` in `sweep.py` uses the same code path and is the single tool the command-line language interface may call.
