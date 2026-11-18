---
type: concept
title: Sweep and outputs
description: 84-pair sweep, results.json schema and the two figures.
resource: preheat/sweep.py, preheat/plot.py, results.json
tags: [sweep, results, figures]
generated:
  by: human:smSamani
  at: 2026-11-18
status: current
stale_after: 2027-05-18
sources: []
---

# Sweep

Six ceilings (21.5 to 24 °C in 0.5 °C steps) × two envelopes × seven cases = 84 pairs, each solved and forward-checked. Order: ceilings ascending, envelopes `current` then `insulated`, cases as listed in [model.md](model.md).

`results.json` (format `preheat-results/1`) holds the fixture, solver version, one record per pair, per-ceiling bands, an `example_day` block and an `infeasible_check`. Floats are rounded to six decimals and there are no timestamps, so reruns are byte-identical. Bands are the minimum and maximum across the seven cases: a sensitivity range, not probabilities. Non-`ok` records carry `status` and `reason` only.

`compare(ceiling_c)` in `sweep.py` uses the same code path and is the single tool the language layer may call.

Figures: `figures/flex_curve.png` (two panels, avoided share and euros saved per day; band edges drawn as dotted lines so overlapping bands stay distinguishable; the 22.5 °C reference line is labelled; caption numbers read from the records) and `figures/example_day.png` (temperature, allowed range and hourly power for the current house at 22.5 °C, with a legend on both panels). The allowed range is drawn by joining the hourly bound points, the same way as the temperature lines, because bounds are only checked at those points; within an hour the exact trajectory is monotone, so an hourly check is enough.
