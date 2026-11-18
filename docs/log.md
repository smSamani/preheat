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

- Initial version: fixture, exact 1R1C model, price-blind baseline, linear programme with forward check, 84-pair sweep, `results.json`, two figures (`preheat/`, `figures/`).
- Regression check T8 matched the scratch-run values at 22.5 °C without changes to the fixture.
- Added the optional language layer (`preheat/ask.py`), a hand-written offline trace (`preheat/traces/demo.json`) and the phrasings file for a later live check. No live check has been run.
- Added README, tests T1 to T18 and this documentation bundle.
- Added `pytest.ini` so a bare `pytest -q` finds the package (found in the clean-clone rehearsal).
