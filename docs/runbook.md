---
type: runbook
title: Runbook
description: Install, run, test, replay and troubleshoot preheat.
resource: README.md, requirements.txt, AGENTS.md
tags: [runbook, setup]
author: smSamani
generated:
  at: 2026-11-19
status: current
stale_after: 2027-05-18
sources:
  - id: scipy-linprog
    title: SciPy linprog documentation
    url: https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linprog.html
---

# Runbook

Tested with Python 3.15.2 on macOS. The pinned NumPy and SciPy need Python 3.12 or newer. `python -m preheat` checks the version before it imports NumPy or SciPy and exits with one line on an older Python.

```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m preheat                  # sweep + diagnostics; writes results.json, diagnostics.json, figures; prints the 22.5 °C table
python -m preheat ask --offline    # replay both recorded traces
python -m preheat web              # dashboard at http://127.0.0.1:8765 (loopback only)
python -m preheat eval --mode rules    # score the authored conversations without a model
python -m pytest -q                # all checks, no external network
```

Regenerate the figures, `results.json` and `diagnostics.json` with `python -m preheat`, and commit them with the code change that alters them. A test fails if the committed JSON differs from a fresh run. Live mode and live evaluation need `PREHEAT_GEMINI_KEY` and optionally `PREHEAT_GEMINI_MODEL` ([language-layer.md](language-layer.md)). Tests and the offline commands never read the key.

Clean-environment rehearsal: clone into `.rehearsal/` (gitignored), create a fresh venv, run the commands above, and confirm that `results.json` and `diagnostics.json` are byte-identical to the committed files.

## Evaluation commands

```
python -m preheat eval --mode rules  [--split dev|heldout|both]   # default both; writes evals/report_rules.json
python -m preheat eval --mode replay                                # dev only; writes evals/report_replay.json
PREHEAT_GEMINI_KEY=... python -m preheat eval --mode live --split dev|heldout
```

`rules` and `replay` run with the network blocked and exit 1 if the safety gate fails (any safety violation). Commit the regenerated reports with the code change that alters them; a test requires a fresh run to equal the committed files. `--out PATH` writes elsewhere, `--quiet` prints only the gate.

**Held-out cases.** `evals/heldout.json` is frozen and must never be edited or opened to tune rules. Its SHA-256 is checked in `tests/test_evals.py` and recorded in `evals/heldout.manifest.json`. To write a new held-out set: give an independent author only the public description in `evals/heldout_brief.md`, have them write the cases before any rule is changed, check only structure and label vocabulary, record the new hash in the manifest and the test, and run rules-only once. Report that first run. Any later rule change made after seeing results is a post-held-out change and goes in `log.md`; keep the first-run report next to the new one.

**Live runs.** Set `PREHEAT_GEMINI_KEY` in the shell (never in a file, never committed) and run the live command on `dev` first, then once on `heldout`. Each run writes a stamped report `evals/live/<UTC date>-<model>-<split>[-runN].json` and a raw-response file `*.raw.json`, which is gitignored and stays local. Publish every report whatever the result, with counts, wins, regressions and misses. Published so far: three runs on 2026-11-18 (earlier rules), a dev and a held-out run on 2026-11-19 (rules before the gate tightening) a dev and a held-out `-run2` on 2026-11-19 (rules before the fifth post-held-out change, prompt version 2) and a dev and a held-out `-run3` on 2026-11-19 (final rules, prompt version 2). After any rule change, repeat the live run on the final rules and add the new files; never edit earlier ones. Tests that count the files in `evals/live/` ignore names starting with `._` (macOS artefacts). The `-run3` files are the live runs on the current rules; the earlier ones predate the fifth post-held-out change and are labelled with their rules state in the README. A live run applies only to the stamped model, date and prompt. If the prompt is changed after reading dev results, say so in the README and do not use the dev numbers as an estimate.

**`loopback` marker.** Tests run with outbound sockets blocked (`tests/conftest.py`). A test marked `loopback` may reach 127.0.0.1 only; the local-server tests use it.

**Manual Apply click-through (owner).** The dashboard UI is not covered by automated browser tests. After a change to the server, run `python -m preheat web`, open `http://127.0.0.1:8765`, type "try a 23 maximum" in the assistant, confirm that the reply is a proposal and that the charts have not changed, select **Apply to scenario**, and confirm that the scenario ceiling changes to 23.0 °C and the charts update. Then type "don't set it to 23" and check that a refusal appears and nothing is applied.

## Troubleshooting

- `infeasible`: no schedule meets the bounds within the heat-pump limit.
- `baseline_failed`: the optimiser found a schedule, but the one-hour rule cannot meet the bounds (for example at 2 kW). This is not physical infeasibility.
- `bound_violation`: the forward check disagreed with the solver.

A different SciPy version may change solver output in the last digits[^scipy-linprog].

[^scipy-linprog]: SciPy `linprog` with `method="highs"`; status 0 optimal, 2 infeasible.
