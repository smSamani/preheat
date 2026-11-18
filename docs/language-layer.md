---
type: concept
title: Language layer
description: Optional confirm-then-call interface that turns a sentence into one confirmed setting.
resource: preheat/ask.py, preheat/traces/demo.json
tags: [language-model, tool-calling, replay]
generated:
  by: human:smSamani
  at: 2026-11-18
status: current
stale_after: 2027-05-18
sources: []
---

# Language layer

The model only proposes `ceiling_c`, asks one clarifying question, or declines. The program echoes "Maximum X °C, all day — correct? (yes/no)", waits for `yes`, calls `compare` in that one place, and renders every number from the tool output with its unit. Text from the model that mentions money, energy or percentages is replaced by a fixed prompt. Malformed or out-of-range calls never reach `compare`.

Tool schema: `compare(ceiling_c)`, number between 21.5 and 24.0, no other keys.

## Offline replay

`python -m preheat ask --offline` feeds the user turns of `preheat/traces/demo.json` through the state machine, takes recorded model outputs in place of the model, recomputes program and tool turns, and requires identical text, results within 1e-9 and equal call counts. The shipped trace is **hand-written** (`source: hand-written`, `model: null`).

## Live mode

One adapter, `call_model`, for an OpenAI-style chat-completions endpoint using the standard library. Configuration only from `PREHEAT_LLM_API_KEY` and `PREHEAT_LLM_MODEL`; without them the command prints a hint and exits 2. Tests and `--offline` never read these variables or use the network. `--record PATH` saves a live session as a trace.

## Live check

`python -m preheat ask --eval tests/phrasings.json` scores 15 labelled synthetic phrasings once and writes `evals/live_eval.json`. **Not run.** No live model was used for this project so far.
