---
type: runbook
title: Runbook
description: Install, run, test, replay and troubleshoot preheat.
resource: README.md, requirements.txt
tags: [runbook, setup]
generated:
  by: human:smSamani
  at: 2026-11-18
status: current
stale_after: 2027-05-18
sources:
  - id: scipy-linprog
    title: SciPy linprog documentation
    url: https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linprog.html
---

# Runbook

```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m preheat                  # sweep; writes results.json and both figures; prints the 22.5 °C table
python -m preheat ask --offline    # replay the recorded trace
pytest -q                          # all checks, no network
```

Regenerate figures and `results.json` with `python -m preheat` and commit them with the code change that alters them. Live mode and the live check need the two environment variables described in [language-layer.md](language-layer.md).

Clean-environment rehearsal: clone into `.rehearsal/` (gitignored), create a fresh venv, run the commands above, and confirm `results.json` is byte-identical to the committed file.

Troubleshooting: an `infeasible` status means the bounds cannot be met within the heat-pump limit; a `bound_violation` means the forward check disagreed with the solver. A different SciPy version may change solver output in the last digits[^scipy-linprog].

[^scipy-linprog]: SciPy `linprog` with `method="highs"`; status 0 optimal, 2 infeasible.
