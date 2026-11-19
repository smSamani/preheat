---
type: index
title: preheat documentation
description: Entry point to the documentation bundle for preheat.
resource: README.md
tags: [index]
author: smSamani
generated:
  at: 2026-11-19
status: current
stale_after: 2027-05-18
sources: []
---

# preheat

`preheat` is a small local Python tool about one synthetic heat-pump home on one synthetic winter day. It asks how much evening heat-pump electricity can be moved earlier by warming the house in advance, as the maximum indoor temperature varies, for two values of an effective whole-home heat-loss coefficient. It is a personal curiosity project. Savings are measured against a simple one-hour rule. A matched-foresight diagnostic shows how much smaller they are against a fairer comparator.

Reading order:

1. [Model](model.md): the thermal model, the synthetic fixture and what the two envelopes hold fixed.
2. [Optimiser](optimiser.md): the one-hour rule, the linear programme, the matched-foresight comparator and the statuses.
3. [Sweep](sweep.md): the 84-pair sweep, `results.json`, `diagnostics.json` (including the tighter-floor check) and the figures.
4. [Language layer](language-layer.md): the optional grounded confirm-then-calculate interface, its grammar and routing policy, the evaluation design, provenance and published live runs.
5. [Dashboard](dashboard.md): local web simulator, assistant grounding and optional Gemini routing.
6. [Runbook](runbook.md): install, run, test, evaluate, troubleshoot.
7. [Log](log.md): dated changes.

The evaluation files are described in [evals/README.md](../evals/README.md).
