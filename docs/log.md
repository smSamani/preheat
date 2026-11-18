---
type: log
title: Change log
description: Dated record of changes to code and results, newest first.
resource: docs/
tags: [log]
generated:
  by: human:smSamani
  at: 2026-11-18
status: current
stale_after: 2027-05-18
sources: []
---

# Log

## 2026-11-18

- Review fixes: the example-day figure drew the evening floor as a step, so a valid schedule looked as if it broke the floor between 21:00 and 22:00; it now joins the hourly bound points. Added a legend to the power panel and a title. Main figure: dotted band edges and a labelled 22.5 °C line. README: corrected the claim that the two measures rank the houses differently at 22.5 °C (they only do at 23.5 °C and above), corrected "coast" (the schedule still tops up in the evening) and added plain-English explanations of C, UA, COP and the linear programme. `results.json` unchanged.
- Initial version: fixture, exact 1R1C model, price-blind baseline, linear programme with forward check, 84-pair sweep, `results.json`, two figures (`preheat/`, `figures/`).
- Regression check T8 matched the scratch-run values at 22.5 °C without changes to the fixture.
- Added the optional language layer (`preheat/ask.py`), a hand-written offline trace (`preheat/traces/demo.json`) and the phrasings file for a later live check. No live check has been run.
- Added README, tests T1 to T18 and this documentation bundle.
- Added `pytest.ini` so a bare `pytest -q` finds the package (found in the clean-clone rehearsal).
