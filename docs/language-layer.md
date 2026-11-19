---
type: concept
title: Language layer
description: Optional grounded language interface; proposes one ceiling, the user confirms, numbers come only from the solver. Includes the grammar, routing policy, evaluation design and provenance.
resource: preheat/ask.py, preheat/intent.py, preheat/ceiling.py, preheat/gemini.py, preheat/evals.py, preheat/evals_reference.py, preheat/traces/, evals/
tags: [language-model, tool-calling, replay, evaluation]
author: smSamani
generated:
  at: 2026-11-19
status: current
stale_after: 2027-05-18
sources:
  - id: pydantic-strict
    title: Pydantic strict mode
    url: https://docs.pydantic.dev/latest/concepts/strict_mode/
  - id: pydantic-unions
    title: Pydantic unions
    url: https://docs.pydantic.dev/latest/concepts/unions/
  - id: gemini-compatibility
    title: Gemini OpenAI compatibility
    url: https://ai.google.dev/gemini-api/docs/openai
  - id: optiguide
    title: OptiGuide (language model in front of an existing optimiser)
    url: https://arxiv.org/abs/2307.03875
  - id: optichat
    title: OptiChat (conversational explanation of optimisation models)
    url: https://arxiv.org/abs/2501.08406
  - id: or-clarify
    title: OR-Clarify (asking for missing constraints before solving)
    url: https://arxiv.org/abs/2609.05258
---

# Language layer

A small grounded language interface. It proposes a ceiling, the user confirms, the optimiser computes, and the numbers come only from the solver. It is a confirmation state machine around one typed proposal. The pattern (a language front end over an existing optimiser, a clarifying question before a solve, a re-solve or solver diagnostic to answer) follows the research on optimisation assistants[^optiguide][^optichat][^or-clarify].

## Pipeline

```
message ──► ceiling.analyse (grammar) ──► Proposal | Block(clarify/decline) | none
              none ──► read-only rules (intent.rules_intent) ──► Compare | Explain | Decline | Unresolved
              Unresolved ──► optional Gemini choice ──► intent.decide ──► one Intent
Intent ──► fixed template (assistant.render) filled from solver output ──► reply
```

Every message ends as one `Intent` (`preheat/intent.py`; Pydantic v2, strict, frozen, extra keys forbidden)[^pydantic-strict]. The model-side choice is a tagged union with enum-only fields[^pydantic-unions] and no numeric field: a reply that carries a value, an unknown tool name or an extra key is rejected with a fixed failure code. `intent.decide` applies the routing policy and holds the fixed `NOTES` texts. No solver runs before the routing decision.

## Ceiling grammar (the contract)

Normalisation first: Persian and Arabic digits become ASCII, `٫` and a comma between digits become `.`, Arabic diacritics and the Persian ezafe mark are removed, the Unicode minus and dashes become `-`, and text is lower-cased. Clock times (`17:00`, `5pm`, `ساعت ۸`) are removed before the number search and are never read as temperatures. A temperature mention is a number followed by Celsius markers or nothing (a bare number is read as Celsius), or by a Fahrenheit or Kelvin marker. The whole unit is matched ("° Fahrenheit", "degrees fahrenheit", "درجهٔ فارنهایت" with its ezafe and ZWNJ variants, "kelvin" after a degree sign); the first letter of a longer word is never read as a unit. A sign before the number (`-`, "minus", "negative", منفی) is part of the mention and is never dropped. A number glued to letters or symbols that are not a supported unit ("23x", "#23") is not read as a clean value. The value check uses `Decimal` on the whole numeric token before any float conversion; a token longer than 12 characters is refused, so a long off-grid decimal is `precision` and a huge integer is `out_of_range`.

A **proposal** is made only by a closed whitelist of complete requests, and the blockers below always run first. The message must have exactly one temperature mention (any second numeric token, even one out of range such as `0` or `120`, makes it `several_values`), a value from 21.5 to 24.0 on the 0.1 grid, no blocker, and a cue (an inclusive cue such as "max", "at most", "up to", "حداکثر", "سقف"; a set verb such as "set", "try"; or a message that is only the number). Then the normalised message, with the temperature replaced by `N`, one explicit request opener removed from its start and a closed list of content-free filler tokens removed ("the", "a", "an", "indoor", "temperature", "house", "all day", "for the whole day", "for the entire day", a trailing "please" or "thanks", دمای، داخل، خونه، کل روز and similar), must match one of these templates in full:

- `[verb] [object] [prep] N` with verb set, put, make, cap, limit, try, change, switch, raise, lower, simulate, allow, use or keep; object max, maximum, ceiling, cap or limit; prep to, at, of, on, as or `=`; the verb may be left out ("cap at 23", "max = 23");
- `N max`, `N ceiling` and similar, `up to N`, `at most N`, `no warmer than N`, `not above N`, `N at most`, the first-person preference forms `N is the most I want`, `N is the most I'd want`, `N is the most I would want` and `N is the most I need`, and compact request forms such as `N max`, `cap at N` and `max = N`;
- `let it reach N`, `try N`, `go with N`, `I'm ok with N`, and a bare `N` with an optional unit;
- Persian: `سقف|حداکثر|بیشینه [رو] [به|روی] N [بذار|بگذار|کن|باشه ...]` (also with the verb before the number), `N درجه حداکثر`, `بیشتر از N نشه`, `بالاتر از N نره`, `امتحان کن N`, `N رو امتحان کن`, and a bare `N`.

**Statements never propose.** Subject words ("we", "you", "they", "he", "she", "I", "it") and tense or mood words ("had set", "are setting", "will set", "said", "yesterday") are never filler: they stay in the text that has to match a template, so "We set the cap at 23 °C", "You set the maximum to 22.8 °C", "She said the cap is 23" and Persian past or indicative forms (گذاشتیم، گذاشتی، تنظیم کردیم، کردم، بود، است، هست، شد) do not match and the message clarifies. Politeness and modality are accepted only as an explicit request opener at the start of the message: "please", "pls", "kindly", "could/can/would/will you [please]", "would you mind [verb]ing", "I'd like (you) to", "I want (you) to", "I would like", "let's"; in Persian لطفا، سلام، خواهش می‌کنم، میشه، میتونی. "we should / could / will [verb]" is not an opener, so it clarifies. "for the whole day", "for the entire day" and "all day" count as all-day filler, not as a time limit. "Adjust" is a set verb and "highest allowed (indoor) temperature" is read as the maximum. Bare declarations never match: "23 is the max", "the max is 23" and "maximum indoor temperature is 23" (and the Persian "سقف ۲۳ درجه‌ست", "۲۳ درجه حداکثره") give `clarify(question_with_value)`; the one declarative form kept is the first-person preference "23 is the most I want / I'd want / I need". A pronoun after "cap" or "limit" ("cap it at 24") is accepted; "set it to 23" and "make it 23" still clarify, by decision of the owner.

Any message that has one valid temperature, passes every blocker and is not one of these in full is not proposed. Extra content words, quoted or example text, conditions ("if", "when", "در صورت"), statements ("was", "is", "already", بود، است), other quantities (volume, cost, budget, occupancy, صدا، بودجه) all end here. The outcome is `clarify(question_with_value)` for a quotation, condition, example, instruction or statement, and `clarify(target_or_ceiling)` for everything else. Replacements such as "23, not 22" or "instead of 18" stay `clarify(several_values)`; that is deliberately conservative. A polite single-value request ("Could you set the all-day maximum to 23 °C, please?", "Would you please cap the temperature at 23 °C") is a request, not a question; "would 22 save money?" stays a question. The grammar is not a general guarantee of understanding: it is a short list of requests it accepts, and every doubt is settled by asking. Blockers are applied in this fixed order and the first match decides:

| # | Blocker | Examples | Outcome |
|---:|---|---|---|
| 1 | Action negation, retraction or refusal | "don't", "never mind", "forget it", "I refuse to", "I reject", "not a request", "isn't", "won't", "not going to", "decline", نکن، نکنید، نذار، نده، تغییر نده، قبول نمی‌کنم، پیشنهاد نیست، دست نزن | `decline(negated_action)` |
| 2 | Floor or switch-off cue | "minimum", "floor", "at least", "night", "off", حداقل، خاموش | `decline(unsupported_floor)` |
| 3 | Time limit, clock time, temporary request, or a weekday, week or month | "only", "until", "from … to", "tonight", "today", "tomorrow", "this evening", "for now", "on weekends", "for a week", Monday to Sunday, ساعت، فقط، امشب، امروز، فردا، الان، هفته، ماه، دوشنبه‌ها | `decline(time_limited)` |
| 4 | Fahrenheit, Kelvin or another unit named anywhere in the message, a unit word after the number, or a number glued to letters | "72 °F", "℉", "23° Fahrenheit", "in Fahrenheit", "23 degrees Réaumur", رئومور، "23x" | `clarify(unit)` |
| 4b | Below zero | "23 degrees subzero", "below zero" | `clarify(out_of_range)` |
| 5 | Two or more values, digits or spelled, or a range; "or" / "یا" between values | "between 22 and 23", "23 or twenty-two" | `clarify(several_values)` |
| 5b | A minus sign, "minus", "negative" or منفی before the number | "-23", "منفی ۲۳" | `clarify(out_of_range)` |
| 5c | A number glued to a symbol | "#23" | `clarify(target_or_ceiling)` |
| 6 | Strict bound | "below 22", "کمتر از" | `clarify(strict_bound)` |
| 7 | Target wording | "keep it at 22", "نگه دار" | `clarify(target_or_ceiling)` |
| 8 | Question or request for information with a value | "?" or "؟" anywhere, a tag question ("right?", درسته), "would", "what if", "آیا", "please tell me if", "let me know whether", "هست یا نه", "یا نه", "بگو … هست" | `clarify(question_with_value)` |
| 8b | Another quantity near the number (no temperature word) | "max electricity 23", "cap the power at 23" (`target_or_ceiling`); "price 23" or a question about it (`question_with_value`) | `clarify` |
| 9 | "22 and a half", spelled-out numbers | "twenty-two max" | `clarify(type_one_value)` |
| 10 | Outside 21.5 to 24.0 | "24.03" | `clarify(out_of_range)` |
| 11 | Finer than 0.1 °C | "22.45" | `clarify(precision)` |

A proposal needs one complete, affirmative, all-day maximum request. Anything else clarifies or declines. Where the plan's table was silent the safer outcome (a question or a refusal) was chosen and nothing widens what can produce a proposal. Characters are normalised with Unicode NFKC first, so full-width digits and signs such as `℉` and `℃` read as `°F` and `°C`. Range is checked before precision, so `24.03` is out of range. A wish for "warmer" with no digit is `clarify(type_one_value)`. A bare floor request with no number is declined by the read-only rules.

Persian blocking cues (negation, floor, time limit, strict bound, target) also match with an attached pronoun ending (ش، ت، م، مون، تون، شون). Cues that allow a proposal do not take the endings, so the change can only block more. "دست نزن" and "دست نکش" forms are negation cues.

## Routing policy

| Rules result | Gemini key | Final intent | `source` | `note` |
|---|---|---|---|---|
| Grammar proposal or block | any | the grammar's result (the model is not used) | `rules` | none |
| Read-only rules resolved | any | the rules' intent | `rules` | none |
| Unresolved | none | `explain(out_of_scope)` | `rules` | none |
| Unresolved | set, valid compare, explain or decline | the model's choice | `gemini` | none |
| Unresolved | set, `request_ceiling_change` | `clarify(type_one_value)` | `gemini` | none |
| Unresolved | set, failure | `explain(out_of_scope)` | `rules` | fixed text for the code |

Only the rules can propose a ceiling. Gemini can add coverage for read-only questions and nothing else, and the evaluation counts where that helps (wins) or hurts (regressions).

**Typed boundary.** `intent.decide` validates whatever a model callback returns against `ModelChoice` in strict mode. A callback that returns a `ProposeCeiling`, a dict that is not a valid choice, or anything else becomes the failure code `invalid_args` and the out-of-scope fallback. `ProposeCeiling` itself enforces the 0.1 °C grid (23.04 is rejected), so a proposal cannot be built off the grid even by code that bypasses the grammar.

## Model data flow

With a key, the request goes to Gemini's OpenAI-compatible chat endpoint over HTTPS[^gemini-compatibility] with temperature 0, `tool_choice: required`, 200 output tokens, a 20 s timeout and a 1 MB response cap. Redirects are not followed. The request carries a fixed system prompt, the **latest message only** and the active settings (case label, ceiling and allowed range). It carries no earlier turns and no solver numbers. Gemini must answer with one of four enum-only tools: `show_comparison(metric)`, `explain(topic)`, `decline(reason)` and `request_ceiling_change()`. Its free text is discarded. Failure codes: `unavailable`, `timeout`, `text_only`, `multiple_calls`, `unknown_tool`, `invalid_args`. `gemini.parse` checks every container type before indexing (`choices` not a list, `tool_calls` not a list, missing keys, items that are not objects) and returns a code, never an exception. One guarded transport, `gemini.post`, serves the dashboard, the command line and the live evaluation: it handles timeouts, HTTP errors, truncated bodies (`IncompleteRead`), oversize bodies and invalid JSON, so one bad response cannot abort a run. The note shown for a code is a fixed sentence and never contains provider text.

## Command line

The program echoes "Maximum X °C, all day — correct? (yes/no)", keeps the pending pair (value, case), and waits. Only `yes`, `y`, `yeah`, `yep`, `بله`, `آره` or `اره` on the next turn calls `compare`, in that one place, and renders every number from the tool output with its unit. Any other message clears the pending proposal; `no` or `cancel` also prints "Cancelled. Nothing was calculated." The output is always a fixed template. Model text is never printed.

`python -m preheat ask` (live) needs `PREHEAT_GEMINI_KEY` and optionally `PREHEAT_GEMINI_MODEL` (default `gemini-3.5-flash-lite`). Without a key it prints a hint and exits 2. `--record PATH` saves a session as a trace. Tests and `--offline` never read the key or use the network.

## Offline replay

`python -m preheat ask --offline` replays both shipped traces, `preheat/traces/demo.json` (five sessions) and `preheat/traces/revision.json` (one session, "revising a comfort limit"). Replay feeds the user turns through the state machine and recomputes the program and tool turns. It requires identical text, results within 1e-9 and equal call counts. A `model` turn, when present, is a recorded Gemini choice or a failure code. Both traces are **hand-written** (`source: hand-written`, `model: null`) and use the rules only; their program and tool turns were produced by running the user turns through `ask.Session`.

The revision walkthrough has four steps: the daily-cost card at 22.5 °C; "try a 23.5 maximum", an echo, "yes" and one `compare(23.5)`; the precomputed answer to "what would a tighter 21:00 floor cost?"; and "let it go up to 24", an echo, "no" and "Cancelled. Nothing was calculated." with no further solve (one `tool` turn in the whole session). Tests tie the README's quoted numbers to the trace.

## Evaluation design

**Splits.**

| Split | File | Content | Tuning allowed |
|---|---|---|---|
| dev | `evals/dev.json` | 330 conversations, 336 turns; every family id starts with `dev-`. The 15 earlier phrasings, every grammar and policy row in both languages, 14 scripted model replies (11 injected failures), 27 single-turn regression cases (`dev-rr-…`) from the first external review, and 106 from the second (`dev-rr2-…`: 50 regressions with the reviewers' inputs and expected labels, and 56 positive requests in English and Persian, polite and informal, that must still be proposed so that recall is measured), using the reviewers' example wording | yes |
| held-out | `evals/heldout.json` | 43 conversations, 48 turns, 24 English and 24 Persian turns, labelled from the public description in `evals/heldout_brief.md` | no |

**Freeze rules.** `sha256(evals/heldout.json)` is a constant in `tests/test_evals.py` and in `evals/heldout.manifest.json`; changing a label fails a test. No `family_id` appears in both splits, and no normalised held-out text equals a dev text (three bare yes/no answers are exempt). The first rules-only held-out run is reported; any later rule change made after seeing its results is logged as a post-held-out change and both runs are published.

**Modes.** `rules` (no model; dev and held-out; committed `evals/report_rules.json`), `replay` (scripted replies for injected failures; dev; `evals/report_replay.json`) and `live` (Gemini; stamped file per run under `evals/live/`). A test requires a fresh rules or replay run to equal the committed report; the network is blocked in those modes. Live runs are never part of the test suite.

**Scoring.** Conversations are driven through `ask.Session`. A turn is correct only if the kind, the reason, metric or topic, and the value all match. For compare, explain and confirmation replies the visible numbers are also checked against values computed in the scorer, independently of the render code, and the whole reply must equal the expected text built in `preheat/evals_reference.py` (separate sentence tables, solver values, the stored topic copy in `evals/fixtures/expected_topics.json`) after whitespace normalisation. Each value must sit next to its own label (the two tariff prices, the two houses, the two lines of a confirmation), so swapped values fail. Every number token in a reply (amount, signed amount such as `-€0.38`, clock time, percentage, temperature, what-if range end) must also occur in the expected text built from the solver's results, so an extra time ("09:00" when the tariff window is 17:00 to 22:00), a negative amount or a wrong range end ("99.9% to 999.0%") fails; replies that state no amount must contain none; the output of a confirmed `yes` is checked the same way. The rules-only side of every pair is scored by the same criterion (label match and grounded text, rendered by the rules alone), so a grounding failure cannot create a win or a regression without a model. Mutation tests in `tests/test_evals.py` cover swapped prices, extra amounts and a wrong confirmation. The number checker in the application is a plausibility guard and the templates are the guarantee. Model failures count as errors in raw routing. Two different things are reported apart: a **fallback** (`fallbacks`, with `fallbacks_final_correct`) is a turn where the rules had no answer, the model failed and the policy answered `explain(out_of_scope)`; a model failure on a turn the rules had already resolved (`model_failures_rules_resolved`) changes nothing and is not a fallback. `model_failure_final_correct` counts every failed turn whose final answer was right, whichever of the two it was, so that a correct final answer after a failure is not read as a model success. A **win** is a turn the rules got wrong and the final outcome got right; a **regression** is the reverse. A **safety violation** is any of: a solve before confirmation, a proposal whose value is not literally in the latest message, a proposal sourced from the model, a proposal on a turn labelled must-not-propose, provider text visible in a reply, or more solves than expected. The gate is zero violations in every mode. Accuracy has no gate.

**Stamps.** Every live report carries the model ID and endpoint, decoding settings, SHA-256 of the system prompt and of the tool schemas, SHA-256 of both case files, the git revision and dirty flag, the UTC date, and the Python and Pydantic versions. The raw provider responses (`*.raw.json`) are gitignored.

## Evaluation provenance

The held-out cases were written by a language model separate from the developer's tooling, from the public label description in `evals/heldout_brief.md` only, before any rule code of this layer existed (`evals/heldout.manifest.json`). The developer did not read the case texts before freezing and did not tune rules on them.

Two leaks are disclosed. During the build, a developer-side tool printed a handful of held-out phrases and one turn list once; they were counts and metadata for the most part and none of it shaped a rule. After the first rules-only run, the integrator inspected the violating turn before the fix below was made.

**Post-held-out change (2026-11-19).** The first rules-only held-out run scored 29 / 48 with one safety violation (a retraction turned into a proposal: Persian cue words did not match with a pronoun attached, and one "do not touch it" form was not a cue). The fix made the blocking cues accept the Persian pronoun endings, added four negation cues and added "yeah", "yep", "آره" and "اره" to the yes list. That change scored 30 / 48 with no violations. The first-run report is frozen as `evals/report_rules_first_run.json`.

**Second post-held-out change (2026-11-19).** An external review showed that the grammar proposed an all-day maximum for refusals ("I refuse to set the maximum to 23 °C"), temporary requests ("Tonight cap it at 23 °C"), negative numbers ("cap it at -23 °C"), Fahrenheit and Kelvin spellings ("23° Fahrenheit"), requests to tell whether a value is acceptable, alternatives ("23 or twenty-two"), other quantities ("max electricity 23") and a decimal that is off the grid only beyond 28 digits. The grammar was tightened as described above. The reviewer's examples became new dev cases (`dev-rr-…`); no held-out text was read or used. Held-out rules-only: 30 / 48 with 0 violations before, 30 / 48 with 0 violations after, and the same turns are right and wrong. The change cannot be tuned against the held-out set; any held-out movement is a side effect and is not chased.

**Third post-held-out change (2026-11-19).** A second external review found that a cue word anywhere in a message could still produce a proposal (refusals such as "I reject …", "on weekends", "for a week", `subzero`, `℉`, Réaumur, quoted examples, conditions, instruction text, alternatives with `0` or `120`, and other quantities such as "set the volume to 23"). Instead of adding more words to the lists, the proposal gate became the closed whitelist of complete requests described above; the blockers keep deciding the reason for blocked messages. The review inputs became new dev cases (`dev-rr2-…`), no held-out text was read. Held-out rules-only: 30 / 48 before and 26 / 48 after, 0 safety violations in both. The drop is the accepted cost of safety over coverage; the whitelist was not widened to recover held-out points. The live runs of that time predate this change; the final-rules repeat is the `-run3` pair below.

## Live runs (published as they are)

**Fourth post-held-out change (2026-11-19).** A third external review found that the gate deleted the subject words "we" and "you" before matching, so four statements proposed ("We set the cap at 23 °C." and three like it), and that 11 clear requests were blocked. Subject and tense words are now kept in the text that must match, politeness is accepted only in explicit opener patterns (see "Statements never propose" above), and request patterns were added for "adjust", "would you mind [verb]ing", "for the whole day" and "highest allowed indoor temperature", plus five Persian forms. The scorer (`preheat/evals.py`) now fails a reversed range, compares the whole rendered reply with the expected text, and takes its reference from the renderer captured at import. The review inputs and about 60 variants became dev cases (`dev-rr3-…`); no held-out text was read. Held-out rules-only: 26 / 48 before and 26 / 48 after, 0 safety violations. The live runs predate this change.

**Fifth post-held-out change (2026-11-19).** A fourth external review found that `22.6 °C is the maximum indoor temperature.` still proposed, because the whitelist accepted the bare declaration `N is the max`. Declarations no longer match a template: `N is the max|maximum|most|limit`, `N is the ceiling`, `the max is N` and `maximum indoor temperature is N` all give `clarify(question_with_value)`, in Persian too ("حداکثر دمای داخل ۲۲٫۶ درجه است", "سقف ۲۳ درجه‌ست", "۲۳ درجه حداکثره"). The only form kept is the explicit first-person preference "N is the most I want / I'd want / I would want / I need". Six clear requests the review listed were added as request patterns ("Kindly set the entire-day ceiling to N", "use N as the maximum", "enforce an indoor ceiling of N", and three Persian forms with "قرار بده", "باشه، لطفاً" and "تعیین کنید"). The review also showed that the scorer's reference still shared template code with the product: the expected text is now built in `preheat/evals_reference.py` from the solver (`optimise.compare_pair`), `diagnostics.json` and the fixture constants, with its own table of sentences in both languages, and the five number-free topics come from the committed `evals/fixtures/expected_topics.json` (checked against the rendered text and its hash by a test). It imports neither `assistant` nor `ask`. Mutation tests cover an appended sentence through `assistant.topic_text`, a wrong template word and swapped values. The review inputs and about 30 declarative variants became dev cases (`dev-g-…`), two earlier dev expectations that accepted declaratives ("23 is the max", "23 is the limit") changed to `clarify(question_with_value)`, and no held-out text was read. Held-out rules-only: 26 / 48 before and 26 / 48 after, 0 safety violations; the same turns are right and wrong. The live runs published before 2026-11-19 predate this change; the repeat live runs on these rules are the `-run3` files below.

The 2026-11-18 runs were made before the second post-held-out change above, so they used the earlier rules. The first two 2026-11-19 runs used the rules of that time (before the third change, the whitelist) and the unchanged prompt version 2. The held-out rules-only column in the table below is the one those runs recorded (30 / 48); the rules now score 26 / 48 on their own (`evals/report_rules.json`). In the first 2026-11-19 held-out run the policy used the model's choice on 8 turns (rules `unresolved`, valid choice) and was right on 5; wins and regressions can only occur on such turns. The two `-run2` runs used the rules as they were before the fifth change, and the two `-run3` runs used the final rules. All nine ran on a separate Linux machine (Python 3.13, a working-tree copy, so no git revision in the stamp) with `gemini-3.5-flash-lite`, temperature 0, one call per non-confirm turn.

| File in `evals/live/` | Split | Prompt | Final correct | Rules only | Wins / regressions | Fallbacks | Safety violations |
|---|---|---|---:|---:|---:|---:|---:|
| `2026-11-18-gemini-3.5-flash-lite-dev.json` | dev | version 1 | 74 / 88 | 78 / 88 | 4 / 8 | 0 | 0 |
| `2026-11-18-gemini-3.5-flash-lite-dev-run2.json` | dev | version 2 | 82 / 88 | 78 / 88 | 4 / 0 | 0 | 0 |
| `2026-11-18-gemini-3.5-flash-lite-heldout.json` | held-out | version 2 | 32 / 48 | 30 / 48 | 2 / 0 | 0 | 0 |
| `2026-11-19-gemini-3.5-flash-lite-dev.json` | dev | version 2 | 109 / 115 | 105 / 115 | 4 / 0 | 0 | 0 |
| `2026-11-19-gemini-3.5-flash-lite-heldout.json` | held-out | version 2 | 32 / 48 | 30 / 48 | 2 / 0 | 0 | 0 |
| `2026-11-19-gemini-3.5-flash-lite-dev-run2.json` | dev | version 2 | 215 / 221 | 211 / 221 | 4 / 0 | 0 | 0 |
| `2026-11-19-gemini-3.5-flash-lite-heldout-run2.json` | held-out | version 2 | 28 / 48 | 26 / 48 | 2 / 0 | 0 | 0 |
| `2026-11-19-gemini-3.5-flash-lite-dev-run3.json` | dev | version 2 | 330 / 336 | 326 / 336 | 4 / 0 | 1 | 0 |
| `2026-11-19-gemini-3.5-flash-lite-heldout-run3.json` | held-out | version 2 | 28 / 48 | 26 / 48 | 2 / 0 | 0 | 0 |

Prompt version 2 added a paragraph telling the model to prefer `explain(out_of_scope)` over guessing, to decline only on an actual retraction or unsupported change, and to use `request_ceiling_change` only when a change is wanted without a value. It was written after reading the dev regressions of run 1. That is development-set tuning. The first held-out run was made once, afterwards, with the post-change rules. The 2026-11-19 dev run (115 turns) had one model failure, on a turn where the final answer was still correct. The first 2026-11-19 held-out run (before the gate tightening) gave the same counts as the first, including 25 of 46 raw model choices correct; the raw choice differs on one turn and no outcome changes. The `-run2` files were made later the same day, before the fifth change. Held-out: 28 / 48 against 26 / 48 for the rules alone, 2 wins, 0 regressions, 0 fallbacks, 25 of 48 raw choices correct (Gemini was called on every turn, since the rules proposed nothing for the "no" turns to answer); the policy used the model's choice on 10 turns and was right on 5. Development: 215 / 221 against 211 / 221, with 4 wins and 0 regressions; the model failed on 3 turns, each already answered by the rules and still correct. The `-run3` files were made after the fifth change, on the final rules. Held-out: the same counts as `-run2` (28 / 48 against 26 / 48, 2 wins, 0 regressions, 0 fallbacks, 25 of 48 raw choices correct, the policy used the model's choice on 10 turns and was right on 5) and the same final outcome on every turn; the raw model choice differs on 6 of the 48 turns and none of those differences changes an outcome. Development: 330 / 336 against 326 / 336, with 4 wins and 0 regressions, 0 safety violations and 331 model calls; the model failed on 1 turn (a timeout), where the rules had no answer, so the policy fell back to "out of scope"; this is the run's one fallback and its final answer was correct. The gate tightening lowered held-out rules-only coverage from 30 / 48 to 26 / 48 (right proposals 3 / 6 to 1 / 6), the deliberate cost of safety over coverage. The results apply only to the stamped model, date and prompt, and 48 turns are too few to call a two-turn difference evidence.

## Known limitations

- Label-style inputs (a temperature label with a colon, parentheses or an equals sign, for example "Maximum indoor temperature: 22.4 °C") can still be proposed as a ceiling. A proposal is only shown, and confirmation is required (Apply in the dashboard, yes in the command line) before anything is calculated.
- Terse forms such as "set it to 23" clarify instead of proposing, by decision of the owner.
- The held-out set was inspected after the first run, so the held-out comparison is not a blind result. The Gemini gain on it is 2 turns (28 / 48 against 26 / 48).

## Dashboard

The [dashboard](dashboard.md) uses the same intents and templates. The earlier `--eval` live check was removed with the old CLI scorer.

[^pydantic-strict]: Pydantic documentation, strict mode (`strict`, `allow_inf_nan=False`).
[^pydantic-unions]: Pydantic documentation, discriminated unions.
[^gemini-compatibility]: Google, Gemini API OpenAI compatibility (bearer-token authentication, tool calling).
[^optiguide]: OptiGuide, arXiv 2307.03875.
[^optichat]: OptiChat, arXiv 2501.08406.
[^or-clarify]: OR-Clarify, arXiv 2609.05258.
