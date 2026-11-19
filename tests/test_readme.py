import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
RESULTS = json.loads((ROOT / "results.json").read_text(encoding="utf-8"))
DIAG = json.loads((ROOT / "diagnostics.json").read_text(encoding="utf-8"))


def section(title):
    m = re.search(rf"## {re.escape(title)}\n(.*?)(?:\n## |\Z)", README, re.S)
    return m.group(1)


def found_section():
    return section("What I found")


def energy_counts():
    pairs = [r for r in RESULTS["records"] if r["status"] == "ok"]
    lower = sum(1 for r in pairs if r["optimised"]["elec_kwh"] < r["baseline"]["elec_kwh"])
    higher = sum(1 for r in pairs if r["optimised"]["elec_kwh"] > r["baseline"]["elec_kwh"])
    return len(pairs), lower, higher


def first_higher_ceiling():
    return min(r["ceiling_c"] for r in RESULTS["records"] if r["envelope"] == "current"
               and r["case"] == "nominal" and r["optimised"]["elec_kwh"] > r["baseline"]["elec_kwh"])


def rec(ceiling, envelope, case="nominal"):
    return next(r for r in RESULTS["records"] if r["ceiling_c"] == ceiling
                and r["envelope"] == envelope and r["case"] == case)


def diag(section, ceiling, envelope):
    return next(r for r in DIAG[section]["rows"]
                if r["ceiling_c"] == ceiling and r["envelope"] == envelope)


def expected_phrases():
    """Each README finding, rebuilt from the named case and field it reports."""
    c, i = rec(22.5, "current"), rec(22.5, "insulated")
    c35, i35 = rec(23.5, "current"), rec(23.5, "insulated")
    light, heavy = rec(22.5, "current", "capacity_3"), rec(22.5, "current", "capacity_8")
    mc, mi = diag("matched_foresight", 22.5, "current"), diag("matched_foresight", 22.5, "insulated")
    sc, si = diag("strict_evening_comfort", 22.5, "current"), diag("strict_evening_comfort", 22.5, "insulated")
    ex = RESULTS["example_day"]
    return [
        f"avoids {c['avoided_kwh']:.2f} kWh ({c['avoided_pct']:.1f}%) of its {c['baseline']['evening_kwh']:.2f} kWh",
        f"saves €{c['saving_eur']:.2f} on a day that costs €{c['baseline']['cost_eur']:.2f}",
        f"same energy, {i['avoided_kwh']:.2f} kWh, but that is {i['avoided_pct']:.1f}% of its smaller {i['baseline']['evening_kwh']:.2f} kWh",
        f"saves €{i['saving_eur']:.2f} on a day that costs €{i['baseline']['cost_eur']:.2f}",
        f"avoids all of its use in the 17:00 to 22:00 tariff window, {i35['avoided_kwh']:.2f} kWh ({i35['avoided_pct']:.1f}%), and saves €{i35['saving_eur']:.2f}",
        f"avoids {c35['avoided_kwh']:.2f} kWh ({c35['avoided_pct']:.1f}%) and saves more, €{c35['saving_eur']:.2f}",
        f"between €{rec(21.5, 'current')['saving_eur']:.2f} (21.5 °C) and €{rec(24.0, 'current')['saving_eur']:.2f} (24.0 °C)",
        f"already costs €{mc['energy_lp']['cost_eur']:.2f} (current) and €{mi['energy_lp']['cost_eur']:.2f} (better insulated)",
        f"saves only €{mc['saving_vs_energy_lp_eur']:.2f} and €{mi['saving_vs_energy_lp_eur']:.2f} more",
        f"At 21.5 °C it saves €{diag('matched_foresight', 21.5, 'current')['saving_vs_energy_lp_eur']:.2f} more",
        f"({c35['baseline']['elec_kwh']:.2f} → {c35['optimised']['elec_kwh']:.2f} kWh)",
        f"draws the full {max(ex['p_optimised_kw']):.2f} kW in one hour",
        f"in {energy_counts()[1]} of the {energy_counts()[0]} pairs and higher in {energy_counts()[2]}",
        f"higher from {first_higher_ceiling():.1f} °C upwards",
        f"highest draw is {max(ex['p_baseline_kw']):.2f} kW",
        f"falls to {sc['avoided_pct']:.1f}% ({sc['avoided_kwh']:.2f} kWh) and {si['avoided_pct']:.1f}% ({si['avoided_kwh']:.2f} kWh)",
        f"saving falls to €{sc['saving_eur']:.2f} for each house",
        f"avoids {light['avoided_pct']:.1f}% ({light['avoided_kwh']:.2f} kWh, €{light['saving_eur']:.2f} saved)",
        f"it avoids {heavy['avoided_pct']:.1f}% ({heavy['avoided_kwh']:.2f} kWh, €{heavy['saving_eur']:.2f} saved)",
    ]


def test_t17_findings_match_named_results():
    sec = " ".join(found_section().split())
    phrases = expected_phrases()
    for phrase in phrases:
        assert phrase in sec, phrase
    assert f'{diag("strict_evening_comfort", 22.5, "current")["saving_eur"]:.2f}' \
        == f'{diag("strict_evening_comfort", 22.5, "insulated")["saving_eur"]:.2f}'   # "for each house"
    # Every number in the findings is either one of those phrases' numbers or a stated setting.
    allowed = set(re.findall(r"\d+(?:\.\d+)?", " ".join(phrases)))
    allowed |= {"21.5", "22.5", "23.5", "24.0", "17", "18", "19", "20", "21", "22", "00",
                "3", "8", "0.38", "0.22", "4.00", "21", "17:00", "1", "4", "48"}
    text = sec.replace("`results.json`", "").replace("`diagnostics.json`", "")
    for tok in re.findall(r"\d+(?:\.\d+)?", text):
        assert tok in allowed, tok


def test_t18_no_annualising_and_paired_percentages():
    assert not re.search(r"annual|per year|a year|/yr|yearly", README, re.I)
    for line in found_section().splitlines():
        if "%" in line:
            assert "kWh" in line or "€" in line, line


def test_language_interface_is_not_called_an_agent():
    assert not re.search(r"\bagents?\b|agentic", README, re.I)


# --- Language interface: evaluation tables, walkthrough, tighter floor ---------------------

EVALS = ROOT / "evals"
REVISION = json.loads((ROOT / "preheat" / "traces" / "revision.json").read_text(encoding="utf-8"))


def report(name):
    return json.loads((EVALS / name).read_text(encoding="utf-8"))


HELDOUT_FIRST = "live/2026-11-18-gemini-3.5-flash-lite-heldout.json"
HELDOUT_PRE = "live/2026-11-19-gemini-3.5-flash-lite-heldout.json"          # before the gate tightening
HELDOUT_BEFORE_FIFTH = "live/2026-11-19-gemini-3.5-flash-lite-heldout-run2.json"
HELDOUT_FINAL = "live/2026-11-19-gemini-3.5-flash-lite-heldout-run3.json"   # final rules
DEV_PRE = "live/2026-11-19-gemini-3.5-flash-lite-dev.json"
DEV_BEFORE_FIFTH = "live/2026-11-19-gemini-3.5-flash-lite-dev-run2.json"
DEV_FINAL = "live/2026-11-19-gemini-3.5-flash-lite-dev-run3.json"


def table_rows(title_prefix):
    """The README table whose header cell starts with `title_prefix`, as {first cell: [cells]}."""
    lines = README.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith(f"| {title_prefix}"))
    rows = {}
    for ln in lines[start + 2:]:
        if not ln.startswith("|"):
            break
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        rows[cells[0]] = cells[1:]
    return rows


def frac(cell):
    a, b = re.fullmatch(r"(\d+) / (\d+)", cell).groups()
    return int(a), int(b)


def test_heldout_table_equals_the_reports():
    rows = table_rows("Held-out (48 turns)")
    header = next(ln for ln in README.splitlines() if ln.startswith("| Held-out (48 turns)"))
    assert "live run on the final rules" in header
    assert "`2026-11-19-gemini-3.5-flash-lite-heldout-run3.json`" in header
    rules = report("report_rules.json")["splits"]["heldout"]["summary"]
    live = report(HELDOUT_FINAL)["splits"]["heldout"]["summary"]
    n = rules["n"]
    assert n == live["n"] == 48
    assert [frac(c) for c in rows["Final outcome correct"]] == [(rules["final_correct"], n), (live["final_correct"], n)]
    raw = rows["Raw model routing correct (before the policy; Gemini was called on 48 turns)"]
    assert frac(raw[1]) == (live["raw_model_correct"], live["model_calls"]) == (25, 48)
    assert live["rules_only_correct"] == rules["final_correct"]    # same rules in both columns
    wins = rows["Wins (rules wrong, final right) / regressions (rules right, final wrong)"][1]
    assert wins == f"{live['wins']} / {live['regressions']}"
    assert rows["Fallbacks (model failures)"][1] == str(live["fallbacks"])
    assert rows["Safety violations"] == [str(rules["safety_violations"]), str(live["safety_violations"])]
    for label, key in (("English", "en"), ("Persian", "fa")):
        assert [frac(c) for c in rows[label]] == [
            (rules["by_lang"][key]["final_correct"], rules["by_lang"][key]["n"]),
            (live["by_lang"][key]["final_correct"], live["by_lang"][key]["n"])]
    kinds = {"explain (includes out of scope)": "explain"}
    for label in ("propose", "clarify", "decline", "compare", "explain (includes out of scope)",
                  "confirm", "cancel"):
        k = kinds.get(label, label)
        assert [frac(c) for c in rows[label]] == [
            (rules["by_kind"][k]["final_correct"], rules["by_kind"][k]["n"]),
            (live["by_kind"][k]["final_correct"], live["by_kind"][k]["n"])]
    # The by-language and by-kind rows each add up to the total.
    assert sum(frac(c)[0] for c in rows["English"][:1] + rows["Persian"][:1]) == rules["final_correct"]
    assert sum(frac(r[1])[0] for k, r in rows.items() if k in kinds or k in (
        "propose", "clarify", "decline", "compare", "confirm", "cancel")) == live["final_correct"]


def test_development_table_equals_the_reports():
    rows = table_rows("Development (used for tuning)")
    rules = report("report_rules.json")["splits"]["dev"]["summary"]
    run1 = report("live/2026-11-18-gemini-3.5-flash-lite-dev.json")["splits"]["dev"]["summary"]
    run2 = report("live/2026-11-18-gemini-3.5-flash-lite-dev-run2.json")["splits"]["dev"]["summary"]
    run3 = report(DEV_PRE)["splits"]["dev"]["summary"]
    run4 = report(DEV_BEFORE_FIFTH)["splits"]["dev"]["summary"]
    run5 = report(DEV_FINAL)["splits"]["dev"]["summary"]
    replay = report("report_replay.json")["splits"]["dev"]["summary"]
    got = {k.split(" (")[0]: v for k, v in rows.items()}
    # the rules the live runs used, and the final rules, are both shown and labelled
    assert frac(got["Rules only, the rules used in the live runs"][0]) == (
        run1["rules_only_correct"], run1["n"]) == (run2["rules_only_correct"], run2["n"])
    assert frac(got["Rules only, current rules"][0]) == (rules["final_correct"], rules["n"])
    assert frac(got["Rules only, the rules used in live run 3"][0]) == (
        run3["rules_only_correct"], run3["n"])
    assert "rules before the gate tightening" in " ".join(rows)
    for name, s in (("Live run 1, first prompt", run1), ("Live run 2, second prompt", run2),
                    ("Live run 3, second prompt", run3), ("Live run 4, second prompt", run4),
                    ("Live run 5, second prompt", run5),
                    ("Scripted replay with injected failures", replay)):
        row = got[name]
        assert frac(row[0]) == (s["final_correct"], s["n"])
        assert row[1] == f"{s['wins']} / {s['regressions']}"
        assert row[2] == str(s["fallbacks"])
        assert row[3] == str(s["safety_violations"])
    assert (run1["wins"], run1["regressions"], run2["wins"], run2["regressions"]) == (4, 8, 4, 0)
    assert frac(got["Live run 3, second prompt"][0]) == (109, 115) and run3["rules_only_correct"] == 105
    # run 4 predates the third review's rule change: its rules-only count is the earlier one
    assert (run4["rules_only_correct"], run4["n"]) == (211, 221)
    assert (rules["final_correct"], rules["n"]) == (326, 336)
    assert "and in live run 4 on 3 turns" in " ".join(section("Evaluation of the language interface").split())
    assert run4["model_failures"] == 3 == run4["model_failures_rules_resolved"] == run4["model_failure_final_correct"]
    # run 5 is on the final rules: same rules-only count as the committed rules report
    assert (run5["final_correct"], run5["rules_only_correct"], run5["n"]) == (330, rules["final_correct"], 336)
    assert (run5["wins"], run5["regressions"], run5["safety_violations"]) == (4, 0, 0)
    # its one model failure is its one fallback: the rules had no answer and the final answer was right
    assert run5["model_failures"] == run5["fallbacks"] == run5["fallbacks_final_correct"] == 1
    assert run5["model_failures_rules_resolved"] == 0 and run5["model_failure_final_correct"] == 1
    assert "In live run 5 the model failed on 1 turn" in " ".join(
        section("Evaluation of the language interface").split())
    # the rules only column now covers more turns than the live runs did
    assert rules["n"] == 336 and rules["n"] > run3["n"]
    assert rules["rules_only_correct"] == rules["final_correct"]


def test_first_run_disclosure_matches_the_frozen_report():
    first = report("report_rules_first_run.json")["splits"]["heldout"]["summary"]
    now = report("report_rules.json")["splits"]["heldout"]["summary"]
    text = " ".join(section("Evaluation of the language interface").split())
    assert f"scored {first['final_correct']} / {first['n']} with one safety violation" in text
    assert first["safety_violations"] == 1
    assert now["safety_violations"] == 0
    # the change after the first run gave the count the live files recorded as rules only
    after_first = report(HELDOUT_PRE)["splits"]["heldout"]["summary"]
    assert f"gave {after_first['rules_only_correct']} / {now['n']} and 0 violations" in text
    assert after_first["safety_violations"] == 0
    assert (f"fell from {after_first['rules_only_correct']} / {now['n']} to "
            f"{now['final_correct']} / {now['n']} with 0 safety violations") in text


LIVE_RUNS = ("2026-11-18-gemini-3.5-flash-lite-dev", "2026-11-18-gemini-3.5-flash-lite-dev-run2",
             "2026-11-18-gemini-3.5-flash-lite-heldout", "2026-11-19-gemini-3.5-flash-lite-dev",
             "2026-11-19-gemini-3.5-flash-lite-heldout", "2026-11-19-gemini-3.5-flash-lite-dev-run2",
             "2026-11-19-gemini-3.5-flash-lite-heldout-run2", "2026-11-19-gemini-3.5-flash-lite-dev-run3",
             "2026-11-19-gemini-3.5-flash-lite-heldout-run3")


def test_final_rules_heldout_repeat_equals_the_earlier_run():
    before = report(HELDOUT_BEFORE_FIFTH)["splits"]["heldout"]
    final = report(HELDOUT_FINAL)["splits"]["heldout"]
    assert before["summary"] == final["summary"]
    same = ("id", "correct", "final_intent", "rules_intent", "source", "fallback", "model_failure")
    assert [[t[k] for k in same] for t in before["turns"]] == [[t[k] for k in same] for t in final["turns"]]
    differ = sum(a["model_raw"] != b["model_raw"] for a, b in zip(before["turns"], final["turns"]))
    assert differ == 6 and "differs on 6 of the 48 turns" in " ".join(
        section("Evaluation of the language interface").split())
    used = [t for t in final["turns"] if t["source"] != "rules"]
    assert (len(used), sum(t["correct"] for t in used)) == (10, 5)


def test_live_runs_are_stamped_as_described():
    for name in LIVE_RUNS:
        stamp = report(f"live/{name}.json")["stamp"]
        assert stamp["model"] == "gemini-3.5-flash-lite" and stamp["utc_date"] == name[:10]
        assert stamp["temperature"] == 0 and stamp["python"].startswith("3.13")
        assert not stamp["git_revision"]
    text = " ".join(section("Evaluation of the language interface").split())
    assert "gemini-3.5-flash-lite" in text and "2026-11-18 and 2026-11-19" in text and "Python 3.13" in text


def test_all_live_runs_table_equals_the_reports():
    lines = [ln.strip() for ln in section("Evaluation of the language interface").splitlines()]
    start = next(i for i, ln in enumerate(lines) if ln.startswith("| Date (UTC)"))
    rows = []
    for ln in lines[start + 2:]:
        if not ln.startswith("|"):
            break
        rows.append([c.strip() for c in ln.strip("|").split("|")])
    assert not any("pending" in c for r in rows for c in r)
    reports = [report(f"live/{n}.json") for n in LIVE_RUNS]
    assert len(rows) == len(reports) == len([f for f in EVALS.joinpath("live").glob("*.json") if not f.name.startswith("._")])
    prompts = {}
    for row, rep in zip(rows, reports):
        split, = rep["splits"]
        s = rep["splits"][split]["summary"]
        prompts.setdefault(rep["stamp"]["system_prompt_sha256"], len(prompts) + 1)
        assert row[0] == rep["stamp"]["utc_date"]
        assert row[1] == ("held-out" if split == "heldout" else split)
        assert row[3] == str(prompts[rep["stamp"]["system_prompt_sha256"]])
        assert frac(row[4]) == (s["final_correct"], s["n"])
        assert frac(row[5]) == (s["rules_only_correct"], s["n"])
        assert row[6] == f"{s['wins']} / {s['regressions']}"
    # rules state: the 2026-11-18 runs predate the second post-held-out change
    assert [r[2] for r in rows] == (["before the second post-held-out change"] * 3
                                    + ["before the gate tightening"] * 2
                                    + ["before the fifth post-held-out change"] * 2
                                    + ["final rules (after the fifth post-held-out change)"] * 2)


def turns(role):
    return [t for t in REVISION["sessions"][0]["turns"] if t["role"] == role]


def test_walkthrough_numbers_equal_the_trace():
    sec = " ".join(section("Example: revising a comfort limit").split())
    program = [t["text"] for t in turns("program")]
    users = [t["text"] for t in turns("user")]
    assert len(REVISION["sessions"]) == 1 and len(users) == 6
    for q in ('"What does preheating save today?"', '"Try a 23.5 maximum"', '"yes"',
              '"What would a tighter 21:00 floor cost?"', '"Let it go up to 24"', '"no"'):
        assert q.strip('"') in users
    # Step 1: the daily-cost card.
    card = program[0]
    for env, label in (("current", "current house"), ("insulated", "better-insulated house")):
        r = rec(22.5, env)
        b, o = r["baseline"]["cost_eur"], r["optimised"]["cost_eur"]
        assert f"{label} €{b:.2f} → €{o:.2f} (€{r['saving_eur']:.2f} saved)" in sec
        assert f"€{b:.2f} → €{o:.2f} for the day (€{r['saving_eur']:.2f} saved)" in card
    # Step 2: the single tool call and its result.
    tool = turns("tool")
    assert len(tool) == 1 and tool[0]["arguments"] == {"ceiling_c": 23.5}
    res = tool[0]["result"]["envelopes"]
    cur, ins = res["current"], res["insulated"]
    assert f"the current house avoids {cur['avoided_kwh']:.2f} kWh ({cur['avoided_pct']:.1f}%) and saves €{cur['saving_eur']:.2f}" in sec
    assert f"the better-insulated house avoids {ins['avoided_kwh']:.2f} kWh ({ins['avoided_pct']:.1f}%) and saves €{ins['saving_eur']:.2f}" in sec
    c35 = rec(23.5, "current")
    assert abs(cur["avoided_kwh"] - c35["avoided_kwh"]) < 1e-6   # results.json is rounded to 6 places
    assert f"goes from {c35['baseline']['elec_kwh']:.2f} to {c35['optimised']['elec_kwh']:.2f} kWh" in sec
    assert c35["optimised"]["elec_kwh"] > c35["baseline"]["elec_kwh"]    # kWh up while the bill falls
    assert c35["optimised"]["cost_eur"] < c35["baseline"]["cost_eur"]
    assert "Maximum 23.5 °C, all day — correct? (yes/no)" in program and "Maximum 23.5 °C, all day — correct? (yes/no)" in sec
    # Step 3: the floor answer carries the diagnostics numbers.
    floor = program[3]
    for row in DIAG["tighter_floor"]["rows"]:
        assert f"€{row['cost_base']:.2f} to €{row['cost_plus_0_1']:.2f}" in floor
        assert f"€{row['dual_eur_per_k']:.2f} per °C" in floor
    # Step 4: a second proposal, cancelled, with no further solve.
    assert program[4] == "Maximum 24.0 °C, all day — correct? (yes/no)"
    assert program[5] == "Cancelled. Nothing was calculated."
    assert "Cancelled. Nothing was calculated." in sec and "no solve runs" in sec
    assert [t["role"] for t in REVISION["sessions"][0]["turns"]].count("tool") == 1


def test_tighter_floor_section_equals_diagnostics():
    sec = " ".join(section("What would a tighter 21:00 floor cost?").split())
    cur, ins = DIAG["tighter_floor"]["rows"]
    assert (cur["envelope"], ins["envelope"]) == ("current", "insulated")
    for row, name in ((cur, "Current house"), (ins, "Better-insulated house")):
        assert row["agree"] and row["hour"] == 21
        assert f"€{row['cost_base']:.3f} to €{row['cost_plus_0_1']:.3f}" in sec
        assert f"€{row['dual_eur_per_k']:.3f} per °C" in sec
        assert f"€{row['fd_eur_per_k']:.3f} per °C" in sec
        # The cost is convex in the floor: a finite step costs at least dual * step.
        step = row["cost_plus_0_1"] - row["cost_base"]
        assert step >= row["dual_eur_per_k"] * DIAG["tighter_floor"]["raise_k"] - 1e-6
    assert "re-solve" in sec and "one day and one setting" in sec
    ins_step = ins["cost_plus_0_1"] - ins["cost_base"]
    assert f"€{ins_step:.4f} against €{ins['dual_eur_per_k'] * 0.1:.4f}" in sec


def test_energy_counts_are_computed_not_typed():
    n, lower, higher = energy_counts()
    assert (n, lower + higher) == (84, 84)
    assert f"in {lower} of the {n} pairs and higher in {higher}" in " ".join(README.split())


BANNED = (r"\bagents?\b", r"agentic", r"live-tested", r"most of the saving is foresight",
          r"rather than saving", r"shifts energy rather", r"No live model", r"no live evaluation",
          r"All numbers are for the nominal", r"PREHEAT_LLM", r"byte for byte, and a test checks "
          r"this\. Another")


def test_banned_phrases_are_absent():
    for pattern in BANNED:
        assert not re.search(pattern, README, re.I), pattern
    # "evaluated live on held-out cases" needs a stamped held-out live report; it exists.
    assert (EVALS / "live" / "2026-11-18-gemini-3.5-flash-lite-heldout.json").exists()


def test_readme_scopes_its_claims():
    flat = " ".join(README.split())
    assert "Savings shrink against a day-ahead, daily-kWh-minimising comparator" in flat
    assert flat.index("Savings shrink against") < flat.index("The two measures disagree")
    assert "Results are nominal unless stated otherwise" in flat
    assert "In the verified environment" in flat and "Python 3.13" in flat
    assert "needs no external network" in flat
    assert not re.search(r"annual|per year|a year|/yr|yearly", README, re.I)


def test_python_guard_runs_before_any_third_party_import():
    source = (ROOT / "preheat" / "__main__.py").read_text(encoding="utf-8").splitlines()
    guard = next(i for i, line in enumerate(source) if "sys.version_info" in line)
    imports = [i for i, line in enumerate(source)
               if line.startswith(("from .", "import numpy", "import scipy", "from scipy",
                                   "from numpy", "import matplotlib", "from pydantic"))]
    assert imports and guard < min(imports)


def test_heldout_limits_are_stated_with_computed_numbers():
    live = report(HELDOUT_FIRST)["splits"]["heldout"]
    called = live["summary"]["model_calls"]
    text = " ".join(section("Evaluation of the language interface").split())
    assert f"Gemini was called on {called} of the {live['summary']['n']} turns" in text
    assert f"raw routing accuracy is {live['summary']['raw_model_correct']} / {called}" in text
    confirms = [i for i, r in enumerate(live["turns"]) if r["expected"]["kind"] == "confirm"]
    assert len(confirms) == 3
    for i in confirms:        # each follows a proposal turn the rules missed, so nothing was pending
        before = live["turns"][i - 1]
        assert before["expected"]["kind"] == "propose" and not before["correct"]
        assert live["turns"][i]["model_raw"] is not None
    for phrase in ("previously inspected set", "not a clean blind result", "prefix-level check",
                   "second held-out live run on 2026-11-19, with rules from before the gate tightening"):
        assert phrase in text
    assert "still to be made" not in text
    # The second run (before the gate tightening) gave the same counts, as the README says.
    final = report(HELDOUT_PRE)["splits"]["heldout"]["summary"]
    for key in ("final_correct", "rules_only_correct", "wins", "regressions", "fallbacks",
                "model_calls", "raw_model_correct", "safety_violations"):
        assert final[key] == live["summary"][key], key
    assert "same held-out counts as the first" in text


def test_the_gate_tightening_only_lowers_heldout_rules_only_outcomes_it_cannot_raise():
    """Counts only. The live files hold the rules of before the tightening."""
    now = report("report_rules.json")["splits"]["heldout"]["turns"]
    for name in (HELDOUT_FIRST, HELDOUT_PRE):
        live = report(name)["splits"]["heldout"]["turns"]
        assert [(r["id"], r["turn"]) for r in live] == [(r["id"], r["turn"]) for r in now]
        before = sum(r["rules_only_correct"] for r in live)
        after = sum(r["correct"] for r in now)
        assert after < before
        # no turn that the old rules got wrong is right now, except a confirm or cancel
        # that follows a proposal and so depends on the state of the earlier turn
        gained = [r for r, o in zip(now, live) if r["correct"] and not o["rules_only_correct"]]
        assert all(r["expected"]["kind"] in ("confirm", "cancel") for r in gained)
    assert all(not r["safety"] for r in now)
    # the run on the final rules recorded exactly the rules-only outcomes of the current rules
    final = report(HELDOUT_FINAL)["splits"]["heldout"]["turns"]
    assert [r["rules_only_correct"] for r in final] == [r["correct"] for r in now]
    proposals = lambda rows: sum(r["rules_only_correct"] for r in rows if r["expected"]["kind"] == "propose")
    assert (proposals(report(HELDOUT_PRE)["splits"]["heldout"]["turns"]), proposals(final)) == (3, 1)
    text = " ".join(section("Evaluation of the language interface").split())
    assert "from 3 / 6 to 1 / 6" in text and "safety over coverage" in text


def test_the_policy_used_the_model_on_a_stated_number_of_heldout_turns():
    live = report(HELDOUT_FINAL)["splits"]["heldout"]["turns"]
    used = [r for r in live if r["source"] == "gemini"]
    assert all(r["rules_intent"] == {"kind": "unresolved"} for r in used)
    right = sum(r["correct"] for r in used)
    assert (len(used), right) == (10, 5)
    text = " ".join(section("Evaluation of the language interface").split())
    assert (f"the policy used the model's choice on {len(used)} of the {len(live)} turns") in text
    assert f"The final answer was right on {right} of those {len(used)}" in text
    summary = report(HELDOUT_FINAL)["splits"]["heldout"]["summary"]
    assert summary["wins"] + summary["regressions"] <= len(used)
    assert all(r["rules_only_correct"] == r["correct"] for r in live if r["source"] != "gemini")


def test_persian_development_count_is_computed_from_the_dev_file():
    dev = json.loads((EVALS / "dev.json").read_text(encoding="utf-8"))
    persian = sum(len(c["turns"]) for c in dev["cases"] if c["lang"] == "fa")
    held = report("report_rules.json")["splits"]["heldout"]["summary"]["by_lang"]["fa"]["n"]
    flat = " ".join(README.split())
    assert f"Persian coverage is small ({held} held-out and {persian} development turns)" in flat
    turns = sum(len(c["turns"]) for c in dev["cases"])
    assert f"{len(dev['cases'])} conversations, {turns} turns in all" in flat


def test_two_heldout_live_runs_agree_on_raw_choices_except_stated_turns():
    first = report(HELDOUT_FIRST)["splits"]["heldout"]["turns"]
    final = report(HELDOUT_PRE)["splits"]["heldout"]["turns"]
    assert [(r["id"], r["turn"]) for r in first] == [(r["id"], r["turn"]) for r in final]
    same = sum(a["model_raw"] == b["model_raw"] for a, b in zip(first, final))
    differ = len(first) - same
    assert differ == 1      # counts only; no case text is printed or asserted on
    assert [a["correct"] for a in first] == [b["correct"] for b in final]
    text = " ".join(section("Evaluation of the language interface").split())
    assert f"differs on {differ} of the {len(first)} turns" in text


def test_dev_extension_keeps_earlier_dev_outcomes():
    live = report("live/2026-11-18-gemini-3.5-flash-lite-dev.json")["splits"]["dev"]["turns"]
    now = {(r["id"], r["turn"]): r for r in report("report_rules.json")["splits"]["dev"]["turns"]}
    for r in live:
        if r["rules_only_correct"]:
            assert now[(r["id"], r["turn"])]["correct"], r["user"]
    new = [r for key, r in now.items() if key[0].startswith("dev-rr-")]
    assert len(new) == 27 and all(r["correct"] for r in new)


def test_replay_summary_separates_failures_from_fallback_outcomes():
    summary = report("report_replay.json")["splits"]["dev"]["summary"]
    text = " ".join(section("Evaluation of the language interface").split())
    assert f"the model failed on {summary['model_failures']} turns" in text
    assert (f"On {summary['fallbacks']} of them the rules had no answer, so the policy fell back") in text
    assert summary["fallbacks_final_correct"] == summary["fallbacks"]
    assert summary["model_failure_final_correct"] == summary["model_failures"]
    # a failure on a turn the rules had resolved is not a fallback
    assert summary["model_failures"] - summary["fallbacks"] == summary["model_failures_rules_resolved"]


def test_measured_cap_count_replaces_rarely_binds():
    from preheat import fixture as fx, optimise
    n = sum(max(optimise.solve(fx.day(k, e), c).p) >= fx.day(k, e).P_MAX - 1e-6
            for c in fx.CEILINGS for e in fx.ENVELOPES for k in fx.CASES)
    assert n == 48
    for path in (ROOT / "README.md", ROOT / "docs" / "model.md"):
        text = " ".join(path.read_text(encoding="utf-8").split())
        assert "rarely binds" not in text and "48 of the 84" in text
    assert "one comparison request" in README and "optimiser runs once" not in README


def test_known_limitations_section_matches_the_reports():
    sec = " ".join(section("Known limitations").split())
    rules = report("report_rules.json")["splits"]["heldout"]["summary"]
    live = report(HELDOUT_FINAL)["splits"]["heldout"]["summary"]
    n = rules["n"]
    assert f"{live['final_correct']} / {n} with Gemini against {rules['final_correct']} / {n}" in sec
    for pattern in BANNED:
        assert not re.search(pattern, sec, re.I), pattern
