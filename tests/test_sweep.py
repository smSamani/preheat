import json
from pathlib import Path

import numpy as np
import pytest

from preheat import plot, sweep
from preheat.fixture import REFERENCE_CEILING, day, floors
from preheat.optimise import idx_T, solve, solve_raw

ROOT = Path(__file__).resolve().parent.parent


def test_t10_deterministic():
    assert sweep.dumps(sweep.run()) == sweep.dumps(sweep.run())
    assert sweep.dumps(sweep.diagnostics()) == sweep.dumps(sweep.diagnostics())


def test_committed_outputs_match_a_fresh_run():
    # Holds with the pinned NumPy/SciPy; another solver build may differ in the last digits.
    assert (ROOT / "results.json").read_text(encoding="utf-8") == sweep.dumps(sweep.run())
    assert (ROOT / "diagnostics.json").read_text(encoding="utf-8") == sweep.dumps(sweep.diagnostics())


def test_t11_shape():
    res = sweep.run()
    assert len(res["records"]) == 84 and len(res["bands"]) == 12
    for b in res["bands"]:
        assert b["n_cases_ok"] == 7
        nom = next(r for r in res["records"] if r["ceiling_c"] == b["ceiling_c"]
                   and r["envelope"] == b["envelope"] and r["case"] == "nominal")
        for key in ("avoided_pct", "saving_eur"):
            assert b[key + "_min"] - 1e-9 <= nom[key] <= b[key + "_max"] + 1e-9


def test_band_keeps_cost_rows_without_a_percentage():
    rows = [{"status": "ok", "avoided_pct": None, "saving_eur": 0.3},
            {"status": "ok", "avoided_pct": 50.0, "saving_eur": 0.5},
            {"status": "infeasible"}]
    band = sweep._band(rows)
    assert band == {"n_cases_ok": 2, "avoided_pct_min": 50.0, "avoided_pct_max": 50.0,
                    "saving_eur_min": 0.3, "saving_eur_max": 0.5}
    assert sweep._band([{"status": "ok", "avoided_pct": None, "saving_eur": 0.1}]) == {
        "n_cases_ok": 1, "saving_eur_min": 0.1, "saving_eur_max": 0.1}


def test_diagnostics_are_separate_and_complete():
    d = sweep.diagnostics()
    assert d["format"] == sweep.DIAG_FORMAT
    assert len(d["matched_foresight"]["rows"]) == 12
    assert all(r["cost_lp_status"] == "ok" and r["energy_lp_status"] == "ok"
               for r in d["matched_foresight"]["rows"])
    for r in d["matched_foresight"]["rows"]:
        assert 0 <= r["saving_vs_energy_lp_eur"] <= r["saving_vs_rule_eur"] + 1e-9
    assert all(r["status"] == "ok" for r in d["strict_evening_comfort"]["rows"])
    assert [r["pair_status"] for r in d["reduced_power"]["rows"]] == ["baseline_failed"] * 2


def test_tighter_floor_dual_matches_resolve():
    block = sweep.diagnostics()["tighter_floor"]
    assert block["case"] == "nominal" and block["ceiling_c"] == 22.5
    assert [r["envelope"] for r in block["rows"]] == ["current", "insulated"]
    for row in block["rows"]:
        assert row["hour"] == 21 and row["floor_c"] == 21.0
        assert row["agree"] is True
        assert abs(row["dual_eur_per_k"] - row["fd_eur_per_k"]) <= 1e-4
        assert row["cost_plus_0_1"] >= row["cost_base"]
        if row["active"]:
            assert row["dual_eur_per_k"] >= 0
    current = block["rows"][0]
    assert current["active"] and abs(current["dual_eur_per_k"] - 0.26035) < 1e-4


def test_tighter_floor_solves_are_ok_and_signs_follow_minimisation():
    L = floors()
    for env in ("current", "insulated"):
        d = day("nominal", env)
        base = solve_raw(d, REFERENCE_CEILING, L)
        raised = L.copy()
        raised[21] += 0.1
        assert base.status == 0 and solve_raw(d, REFERENCE_CEILING, raised).status == 0
        assert base.lower.marginals.min() >= -1e-9
        assert base.upper.marginals.max() <= 1e-9
        assert base.lower.marginals[idx_T(21)] == base.lower.marginals[44]


def test_tighter_floor_fails_when_dual_and_resolve_disagree(monkeypatch):
    monkeypatch.setattr(sweep, "DUAL_TOL", -1.0)
    with pytest.raises(RuntimeError, match="differ"):
        sweep.tighter_floor()


def test_tighter_floor_does_not_change_the_other_diagnostics():
    committed = json.loads((ROOT / "diagnostics.json").read_text(encoding="utf-8"))
    fresh = json.loads(sweep.dumps(sweep.diagnostics()))
    assert committed == fresh
    assert {"matched_foresight", "strict_evening_comfort", "reduced_power"} <= set(fresh)


def test_solve_raw_validates_a_custom_floor_vector():
    d = day("nominal", "current")
    L = floors()
    for bad in (L[:24], np.append(L, 21.0), np.where(np.arange(25) == 3, np.nan, L),
                np.where(np.arange(25) == 3, np.inf, L), np.where(np.arange(25) == 0, d.T0 + 1, L)):
        with pytest.raises(ValueError):
            solve_raw(d, REFERENCE_CEILING, bad)
    assert solve_raw(d, REFERENCE_CEILING, L).status == 0
    assert solve_raw(d, REFERENCE_CEILING).fun == solve(d, REFERENCE_CEILING).cost_eur


def test_flex_curve_caption_without_a_reference_pair(tmp_path):
    res = sweep.run()
    res["records"] = [r for r in res["records"] if r["ceiling_c"] != REFERENCE_CEILING]
    path = tmp_path / "flex.png"
    plot.flex_curve(res, str(path))
    assert path.stat().st_size > 0


def test_flex_curve_caption_without_an_evening_percentage(monkeypatch, tmp_path):
    captions = []
    real = plot.plt.Figure.text
    monkeypatch.setattr(plot.plt.Figure, "text",
                        lambda self, *a, **k: captions.append(a[2]) or real(self, *a, **k))
    res = sweep.run()
    for r in res["records"]:
        if r["ceiling_c"] == REFERENCE_CEILING and r["status"] == "ok":
            r["avoided_pct"] = None
    plot.flex_curve(res, str(tmp_path / "flex.png"))
    assert captions and "None" not in captions[0] and "nan" not in captions[0].lower()


def test_example_day_with_no_example_writes_nothing(tmp_path, capsys):
    path = tmp_path / "example.png"
    assert plot.example_day({"example_day": None}, str(path)) is False
    assert not path.exists()
    assert "example day not available" in capsys.readouterr().out
    path.write_bytes(b"old")
    plot.example_day({"example_day": None}, str(path))
    assert path.read_bytes() == b"old"            # never overwritten, never deleted
