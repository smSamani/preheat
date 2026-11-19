# Evaluation files

Authored conversations and reports for the language layer. How the evaluation is designed and scored is in [docs/language-layer.md](../docs/language-layer.md); the commands are in [docs/runbook.md](../docs/runbook.md).

| File | What it is |
|---|---|
| `dev.json` | Development cases (330 conversations, 336 turns). Used while building; tuning on it is allowed. Changing it changes the stamped hash, so regenerate the reports afterwards. |
| `heldout.json` | Held-out cases (43 conversations, 48 turns), written independently from the public description. **Never edit this file.** Its hash is checked by a test. |
| `heldout.manifest.json` | Frozen record of the held-out file: hash, case counts and how it was written. |
| `heldout_brief.md` | The public intent description the held-out cases were written from. Frozen. |
| `fixtures/gemini_envelope.json` | One recorded response envelope shape used by the parser tests. Frozen. |
| `fixtures/expected_topics.json` | Independent stored copy of the number-free explanation topics, read by the scorer's expected-text builder. A test checks it against the rendered text and its hash. |
| `report_rules.json` | Rules-only scores on dev and held-out. A test requires a fresh run to match. |
| `report_replay.json` | Scripted-reply scores on the dev injected-failure cases. A test requires a fresh run to match. |
| `report_rules_first_run.json` | The first rules-only held-out run, before the logged post-held-out change. Frozen. |
| `live/*.json` | Stamped reports of live Gemini runs, one file per run, published whatever the result. `live/*.raw.json` (provider responses) is gitignored. |

SHA-256 of the frozen inputs:

```
c705b9829d3182f4d0c4b31009274f4f18553f10f816dded0d4bbbf692d39329  heldout.json
1aa2f1bde63706fdc893f887746fbf541f7849383ea6dd6c2d3358abf171d747  heldout_brief.md
d1228ee32adf5eb01e43df96b2c8af70a001dd45e719d8acf20df8ca6068a9a0  fixtures/gemini_envelope.json
62d7824e06126a5548a8bd2917ae8798265cdf206e5e836d2e92bf4419b27098  dev.json (current)
6af1922828c938f4f46068bf361507302915b8b7c398c89bb1f92401fdeb8004  fixtures/expected_topics.json
```

Committed reports must match a fresh run (`python -m preheat eval --mode rules`, `--mode replay`). Live results apply only to the model, date and prompt in their stamp.
