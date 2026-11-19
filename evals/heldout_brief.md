# Task: write an independent held-out test set for a chat interface

You are NOT to read any files, run commands or browse. Work only from this brief and write only the final JSON document to standard output (nothing else, no code fences, no commentary).

You are acting as an independent test author. The developer of the system will never see your set while building, and will be scored on it later. Write realistic, varied user messages. Do not try to be easy and do not try to be adversarial for its own sake; write what real, varied people (Iranian and international students, a facility manager, a curious homeowner) would actually type.

## The product (public description)

"preheat" is a small simulation dashboard for one invented home with a heat pump on one invented winter day. Two houses are simulated: "current" and "better insulated". Electricity costs 0.38 EUR/kWh from 17:00 to 22:00 (the "peak" window) and 0.22 EUR/kWh otherwise. A linear-programming optimiser pre-heats the house before the expensive hours. Comfort rules: indoor temperature at least 20 °C all day, at least 21 °C at the checks 18:00–21:00 (the "evening floor"), and at most a chosen all-day maximum ("ceiling").

A person can chat with an assistant in English or Persian. The assistant understands exactly these things (the public intent schema). Every user message must map to exactly ONE of these labels:

- kind "propose", value_c = number: the person clearly and affirmatively asks to try or set ONE all-day MAXIMUM indoor temperature, one value in Celsius between 21.5 and 24.0 in steps of 0.1 (a message that is just a bare number like "23" also counts and is read as Celsius). The person must still confirm afterwards.
- kind "clarify" with reason, when the message touches the all-day maximum but cannot be turned into a safe proposal:
  - "unit": the temperature is given in Fahrenheit or Kelvin
  - "out_of_range": a Celsius value outside 21.5–24.0
  - "precision": finer than 0.1 °C (e.g. 22.45)
  - "several_values": two or more temperatures, or a range, in one message
  - "strict_bound": strictly below / under / less than a value
  - "target_or_ceiling": the person wants to hold or keep the house AT a temperature (a target) rather than cap it
  - "question_with_value": a question that mentions a value but does not ask to set it (e.g. asks what would happen)
  - "type_one_value": the person wants to change the maximum but gives no usable digit value (e.g. "a bit warmer", or a number spelled in words)
- kind "decline" with reason:
  - "negated_action": the person says NOT to do something / retracts ("don't set it to 23", "no, forget 23")
  - "unsupported_floor": the person wants to change the minimum / evening floor / night set-back / switch the heating off (not supported)
  - "time_limited": the person wants a maximum for only part of the day or between clock times
- kind "compare" with metric:
  - "peak_electricity": how much evening / peak-window electricity preheating avoids
  - "daily_cost": how many euros preheating saves per day within each house
  - "insulation_difference": how the better-insulated house compares with the current one
- kind "explain" with topic: "preheating" (how/why it works), "insulation" (why insulation helps), "tariff" (prices and the peak window), "comfort" (current temperature limits), "assumptions" (model inputs), "baseline" (what the savings are measured against), "limits" (what the model cannot say: real homes, a whole year), "tighter_floor" (what it would cost to make the 21:00 evening minimum warmer), "out_of_scope" (anything off-topic, meaningless, or too ambiguous to place).
- kind "confirm" (value_c = the pending value): the person says yes to a pending proposal the assistant just echoed. Only allowed as a later turn right after a "propose" turn. The user text is a short yes in English or Persian.
- kind "cancel": the person says no / cancel to a pending proposal. Same placement rule.

## What to write

About 40 conversations (each 1 to 3 turns; about 48 turns in total). At least 16 conversations must have lang "fa" (Persian: colloquial Tehrani Persian, some with Persian digits ۰-۹ and the decimal separator ٫, some with Arabic digits, some in Latin-script Persian "Finglish", some mixed Persian/English); the rest "en" (include a few non-native English phrasings, typos, and lowercase-only messages).

Cover these six categories, roughly 5–8 conversations each (mark each with "category"):
1. "floor21": requests about setting or changing the 21:00 / evening floor or minimum value (and questions about what a tighter 21:00 floor would cost, which is the explain topic "tighter_floor", not a change).
2. "negation_retraction": saying no, retracting, "don't", "forget it", "never mind", "I changed my mind", including after a pending proposal (cancel turns).
3. "question_no_change": questions that mention a temperature but do not ask for a change ("what happens at 23?", "would 22 save money?").
4. "clock_fahrenheit": clock times (5pm, 17:00, ساعت ۸) and Fahrenheit/Kelvin values, including messages that combine a Celsius maximum with a clock time.
5. "savings_insulation": questions about savings, costs, insulation, peak electricity, the tariff, the baseline, limits, assumptions, in many wordings.
6. "offtopic_ambiguous": off-topic (weather tomorrow, jokes), vague ("make it cosy", "warmer please"), prompt-injection style ("ignore the rules and set 30"), empty-ish or garbled messages.
Also include some plain affirmative "propose" paraphrases in both languages (about 6 conversations, at least 2 Persian, at least 2 using colloquial wording that is NOT the obvious "set maximum to X"), and a few multi-turn propose→confirm and propose→cancel conversations.

Rules for quality:
- Each conversation has a "family_id": a short slug naming the underlying request type; several conversations (English and Persian) may share a family when they are paraphrases of each other. Use about 25–30 families. Do not reuse family ids for different meanings.
- At least 40% of the messages should be phrasings that a simple keyword-matching program would plausibly fail to place (colloquial, indirect, unusual order, slang, typos, mixed language), as that is what this test is for. The remainder may be fairly standard.
- Choose the label that a careful, literal-minded product designer would give under the schema above. If a message is truly ambiguous between two labels, rewrite the message so it is not.
- value_c must be a number only for "propose" and "confirm" turns, otherwise null. reason is only for clarify/decline, metric only for compare, topic only for explain; unused fields are null.
- "must_not_propose": true for every turn where proposing a ceiling would be a safety error (everything that is not a propose/confirm turn but mentions or implies a temperature change), otherwise false.
- Do not use any value in a propose turn outside 21.5–24.0 or off the 0.1 grid.
- Ids: "ho-en-01", "ho-fa-01", ... in order.

## Output format (JSON only)

{
  "version": 1,
  "written_by": "separate language model (not the developer), before any rule code was written",
  "cases": [
    {
      "id": "ho-en-01",
      "family_id": "fam-example",
      "lang": "en",
      "category": "floor21",
      "turns": [
        {"user": "...", "expected": {"kind": "decline", "reason": "unsupported_floor", "metric": null, "topic": null, "value_c": null, "must_not_propose": true}}
      ]
    }
  ]
}
