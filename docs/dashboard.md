---
type: concept
title: Web dashboard
description: Local simulator with hourly charts and a scenario assistant whose replies are fixed templates filled from solver output and number-checked.
resource: preheat/web.py, preheat/assistant.py, preheat/intent.py, preheat/ceiling.py, preheat/gemini.py, preheat/ui/
tags: [dashboard, simulator, gemini]
author: smSamani
generated:
  at: 2026-11-19
status: current
stale_after: 2027-05-18
sources:
  - id: gemini-compatibility
    title: Gemini OpenAI compatibility
    url: https://ai.google.dev/gemini-api/docs/openai
---

# Web dashboard

Run `python -m preheat web` and visit `http://127.0.0.1:8765`. Use `--port` to choose another port. The server binds to loopback only.

The dashboard runs the same one-hour rule and linear programme for both envelopes at the selected ceiling and what-if case. Power values cover one hour each. Temperature values are states at each hour mark. The evening difference is one-hour-rule minus optimised consumption between 17:00 and 22:00. The daily cost saving covers the full day.

## Assistant panel and grounding

The assistant panel is labelled "Copilot" in the UI. It works without a key. Each message becomes one typed intent (`preheat/intent.py`) and the server renders a fixed English or Persian template from it (`preheat/assistant.py`). The intents are:

- propose one all-day ceiling. Only the rules in `preheat/ceiling.py` can do this, and only for a value typed in the latest message;
- a clarifying question or a refusal with a fixed reason (unit, range, precision, several values, "below", a target, a question, no value; negation, a floor or switch-off request, a time-limited request);
- a comparison card: evening electricity avoided or daily cost saved compared with the one-hour rule, or the difference between the two envelopes;
- one fixed explanation topic: preheating, insulation, tariff, comfort, assumptions, baseline, limits, `tighter_floor`, or `out_of_scope`.

`tighter_floor` answers "what would a tighter 21:00 floor cost?" with a text reply (no card). It reads the committed `tighter_floor` block of `diagnostics.json` ([sweep.md](sweep.md)), is labelled "Nominal day, 22.5 °C" whatever scenario is active, and runs no solver.

The routing decision is made before any solver runs. A proposal, a question, a refusal and a topic run no LP; only a comparison card reads the solver results for the current scenario, cached by (ceiling, case).

**No-solve guarantee, scoped.** No LP runs for a chat-proposed ceiling until the person selects **Apply to scenario** (in the command line, until "yes"). Read-only answers may still solve the *current* scenario, because a comparison card needs its results. The evaluation counts solves per turn and treats any extra solve as a safety violation ([language-layer.md](language-layer.md)). Clock times such as 22:00 are not read as temperatures.

**Optional Gemini.** With a key and model ID from Settings, the server asks Gemini only when the built-in rules cannot place a read-only question. It sends:

- the latest message only, no earlier turns;
- the active settings: case label, ceiling and allowed range. No solver numbers are sent.

Gemini must answer with one of four tools, all with enum-only arguments: `show_comparison(metric)`, `explain(topic)`, `decline(reason)` and `request_ceiling_change()`. No tool carries a number, so Gemini cannot propose a value. `request_ceiling_change` only leads to the "which single maximum?" question. Its free text is never shown. When the reply cannot be used, the out-of-scope text is shown and `note` holds one fixed sentence for the failure code (`unavailable`, `timeout`, `text_only`, `multiple_calls`, `unknown_tool`, `invalid_args`) or for a failed number check (`number_check`). The note never contains provider text.

**What leaves the machine.** Only the latest message and the active settings go to Gemini, never the chat history and never solver numbers. The browser still keeps the full chat history and sends it to the local server in `messages`, as the API below requires. The server validates it and drops everything but the last user message. With no key, nothing leaves the machine.

**Number check.** `assistant.ground` runs on every reply, from the rules or from Gemini, and on every comparison-card string before it is returned. `ungrounded_numbers` accepts a number only if a solver or fixture fact matches all of the following:

- the value at the shown precision (integers must be exact);
- the sign;
- the unit (€, €/kWh, kWh, kW, %, °C, kWh/K, kW/K);
- the house the sentence names;
- whether nearby words call it a reduction ("saved", "less", "avoided") or a level ("cost", "bill").

Clock times must be model hours. A failing reply is replaced by a fixed text without numbers, and the note says it was withheld. The checker is a plausibility guard, not a proof: it can pass a number that is real but sits in the wrong sentence (a correct value attributed to the wrong quantity, for example). The templates are the guarantee, because every number in a reply is written into a fixed sentence from a named solver field. The evaluation scorer is stricter than this guard and checks labelled values (see [language-layer.md](language-layer.md)).

A proposed ceiling is applied only when the user selects **Apply to scenario**.

## API used by the page

- `GET /api/config`: case labels, the reference ceiling and the two prices.
- `POST /api/scenario {ceiling, case}`: per-envelope `status`, `reason` and, when `ok`, `baseline` and `optimised` (`power`, `temperature`, `evening_kwh`, `cost_eur`), `avoided_kwh`, `avoided_pct` (may be `null`) and `saving_eur`.
- `POST /api/interpret {messages, scenario, key?, model?}`: one of `text`, `text` + `comparison {title, rows[{label, value, detail}]}`, or `ceiling`. It also returns a `source` (`rules` or `gemini`, where `gemini` means Gemini picked the intent and the server rendered it) and an optional `note`.

## Security boundary

This is a personal loopback tool. The server:

- binds 127.0.0.1;
- checks `Host` and `Origin`;
- requires JSON for POSTs, with a request-size cap;
- sends no CORS headers;
- uses a same-origin CSP;
- does not log requests.

Tests cover the host, origin and content-type rules against a running server. The browser keeps the Gemini key in page memory only. The local server forwards it to Google's OpenAI-compatible endpoint over HTTPS as a bearer token[^gemini-compatibility]. Connections have a 10 s read deadline, so a stalled client cannot hold a handler open. The port is still meant for the local machine only.

## Interface

The workspace shows both houses' daily cost and evening-electricity comparisons. A shared timeline aligns the hourly power step plot with smoothed temperature trajectories and the comfort envelope. Both plots are drawn on canvas with gradient lines and areas, a labelled peak-tariff band and a glowing marker on the inspected hour. The highlighted tariff window and linked hover readouts use the same hour scale. The hourly data table provides the underlying chart values. The chart and panel transitions respect the system’s reduced-motion preference.

The summary uses the selected insulation and shows baseline-to-preheated peak use, daily cost and the first hourly temperature sample at the ceiling. The comparison lists both absolute measures for all four house and heating states. The delta compares the two preheated daily costs. Each house's baseline percentage remains secondary.

The charts share an hour cursor with pointer, touch and keyboard input. The temperature chart shades the allowed range. The power chart marks the peak tariff and hours with additional preheat draw. Applying a ceiling proposal highlights the intervals where the selected house's optimised power or temperature changes.

The visual theme is calm frosted glass: a self-hosted pale blue gradient background, translucent blurred panels, one blue accent for lines, rings and chips, neutral slate text, and a single sand tone for the peak tariff. The page uses one 1200 px column; the three scenario control cards and the three summary tiles share the same three-column grid, and each chart sits in its own hairline-separated block of the schedule card. The stylesheet uses system fonts only because the content security policy allows nothing but same-origin assets.

[^gemini-compatibility]: Google, Gemini API OpenAI compatibility (bearer-token authentication).
