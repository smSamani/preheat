import json
import re
from pathlib import Path

import pytest

from preheat import ask, intent, sweep

TRACE = Path(ask.__file__).parent / "traces" / "demo.json"
REVISION = TRACE.with_name("revision.json")


def spy():
    calls = []
    return calls, lambda v: calls.append(v) or sweep.compare(v)


def test_unconfirmed_never_solves():
    trace = json.loads(TRACE.read_text(encoding="utf-8"))
    calls, fn = spy()
    keep = [s for s in trace["sessions"] if s["name"] in ("proposal cancelled", "unsupported edit")]
    ok, _ = ask.replay({"sessions": keep}, compare_fn=fn, out=lambda *_: None)
    assert ok and calls == []


def test_yes_bound_to_pending():
    calls, fn = spy()
    s = ask.Session(compare_fn=fn)
    assert s.send("max 22.5") == [ask.echo(22.5)]
    assert s.pending == (22.5, "nominal") and calls == []
    out = s.send("yes")
    assert calls == [22.5] and s.pending is None
    assert out[0].startswith("Maximum indoor temperature 22.5 °C")
    s.send("yes")                         # nothing pending any more
    assert calls == [22.5]


@pytest.mark.parametrize("yes", ["yes", "y", "YES ", "بله", "yeah", "Yep", "آره", "اره"])
def test_yes_variants(yes):
    calls, fn = spy()
    s = ask.Session(compare_fn=fn)
    s.send("try 23")
    s.send(yes)
    assert calls == [23.0]


@pytest.mark.parametrize("answer", ["no", "n", "cancel", "نه"])
def test_no_and_cancel_clear_the_proposal(answer):
    calls, fn = spy()
    s = ask.Session(compare_fn=fn)
    s.send("try 23")
    out = s.send(answer)
    assert out in ([ask.CANCELLED], [ask.CANCELLED_FA])
    assert s.pending is None and calls == []
    s.send("yes")
    assert calls == []


@pytest.mark.parametrize("other", ["what about the night?", "max 24", "how much do I save?",
                                   "yes please do", "maybe"])
def test_a_new_message_clears_the_proposal(other):
    calls, fn = spy()
    s = ask.Session(compare_fn=fn)
    s.send("try 23")
    s.send(other)
    assert calls == []
    if other == "max 24":
        assert s.pending == (24.0, "nominal")
    else:
        assert s.pending is None
        s.send("yes")
        assert calls == []


def test_persian_yes_and_echo():
    calls, fn = spy()
    s = ask.Session(compare_fn=fn)
    assert s.send("سقف رو بذار روی ۲۳ درجه") == [ask.echo(23.0, True)]
    s.send("بله")
    assert calls == [23.0]


def test_cli_prints_templates_only():
    """Model text and tool names never reach the output; only fixed templates do."""
    calls, fn = spy()
    printed = []
    hostile = ["This saves €999 a day", "€999_saved"]
    asked = []

    def model(message):
        asked.append(message)
        return intent.Failure("text_only")

    s = ask.Session(model, fn)
    printed += s.send("tell me a joke")
    printed += s.send("max 23 please, it saves €999")
    printed += s.send("no")
    text = "\n".join(printed)
    # only unresolved messages reach the model; the second message is a clarification, so "no"
    # has nothing to cancel and is unresolved too
    assert asked == ["tell me a joke", "no"]
    assert not any(h in text for h in hostile) and "999" not in text
    assert printed[0].startswith("That is outside this model")
    assert calls == []


def test_the_model_cannot_start_a_calculation():
    calls, fn = spy()
    s = ask.Session(lambda m: intent.CeilingRequest(kind="ceiling_request"), fn)
    out = s.send("make it cosy")
    assert out[0].startswith("Which single all-day maximum") and s.pending is None
    s.send("yes")
    assert calls == []


def test_only_the_latest_message_is_given_to_the_model():
    asked = []
    s = ask.Session(lambda m: asked.append(m) or intent.Failure("timeout"))
    s.send("first odd question")
    s.send("second odd question")
    assert asked == ["first odd question", "second odd question"]


def test_numbers_from_tool_output():
    result = sweep.compare(22.5)
    text, prov = ask.render(result)
    shown = {p[0] for p in prov}
    for tok in re.findall(r"\d+(?:[.,]\d+)?", text):
        assert tok in shown, tok
    after = {"kWh": r"{} kWh", "%": r"{}%", "€": r"€{}", "°C": r"{} °C", "cases": r"{} what-if"}
    labels = {"avoided_kwh": "kWh", "baseline_evening_kwh": "kWh", "avoided_pct": "%",
              "optimised_cost_eur": "€", "baseline_cost_eur": "€", "saving_eur": "€",
              "avoided_pct_min": "%", "avoided_pct_max": "%", "saving_eur_min": "€",
              "saving_eur_max": "€", "n_cases_ok": "cases", "ceiling_c": "°C"}
    for s, path, unit in prov:
        node = result
        for part in path.split("."):
            node = node[part]
        want = f"{int(node)}" if unit == "cases" else f"{node:.1f}" if unit in ("%", "°C") \
            else f"{node:.2f}"
        assert s == want
        assert labels[path.split(".")[-1]] == unit
        assert after[unit].format(s) in text


def test_replay_identical():
    trace = json.loads(TRACE.read_text(encoding="utf-8"))
    calls, fn = spy()
    ok, msg = ask.replay(trace, compare_fn=fn, out=lambda *_: None)
    assert ok, msg
    assert len(calls) == sum(1 for s in trace["sessions"] for t in s["turns"]
                             if t["role"] == "tool")


def test_replay_detects_a_changed_reply():
    trace = json.loads(TRACE.read_text(encoding="utf-8"))
    trace["sessions"][0]["turns"][1]["text"] += " changed"
    ok, _ = ask.replay(trace, out=lambda *_: None)
    assert not ok


def test_replay_feeds_recorded_model_choices():
    trace = {"sessions": [{"name": "model routed", "turns": [
        {"role": "user", "text": "tell me something odd"},
        {"role": "model", "output": {"kind": "explain", "topic": "tariff"}},
        {"role": "program", "text": ask.assistant.topic_text(
            "tariff", {"ceiling": 22.5, "case": "nominal"}, False)["text"]}]}]}
    assert ask.replay(trace, out=lambda *_: None)[0]


def test_render_handles_an_undefined_percentage():
    result = sweep.compare(22.5)
    result["envelopes"]["insulated"]["avoided_pct"] = None
    text, _ = ask.render(result)
    assert "(n/a)" in text


def test_live_settings_come_from_the_gemini_variables(monkeypatch):
    monkeypatch.delenv("PREHEAT_GEMINI_KEY", raising=False)
    monkeypatch.delenv("PREHEAT_GEMINI_MODEL", raising=False)
    assert ask.live_settings() is None
    monkeypatch.setenv("PREHEAT_GEMINI_KEY", "example_test_key")
    assert ask.live_settings() == {"key": "example_test_key", "model": "gemini-3.5-flash-lite"}
    monkeypatch.setenv("PREHEAT_GEMINI_MODEL", "gemini-test")
    assert ask.live_settings()["model"] == "gemini-test"


def test_old_helpers_are_gone():
    for name in ("text_is_safe", "NUMBER_GUARD", "score_item", "run_eval", "request_model",
                 "llm_settings", "normalise"):
        assert not hasattr(ask, name)


def test_revision_trace_replays_identically():
    trace = json.loads(REVISION.read_text(encoding="utf-8"))
    calls, fn = spy()
    ok, msg = ask.replay(trace, compare_fn=fn, out=lambda *_: None)
    assert ok, msg
    assert calls == [23.5]          # one solve, for the confirmed 23.5 maximum only


def test_revision_trace_is_rules_only_and_cancels_without_a_solve():
    trace = json.loads(REVISION.read_text(encoding="utf-8"))
    assert trace["source"] == "hand-written" and trace["model"] is None
    turns = trace["sessions"][0]["turns"]
    assert not any(t["role"] == "model" for t in turns)
    assert [t["text"] for t in turns if t["role"] == "user"] == [
        "What does preheating save today?", "Try a 23.5 maximum", "yes",
        "What would a tighter 21:00 floor cost?", "Let it go up to 24", "no"]
    assert turns[-1] == {"role": "program", "text": "Cancelled. Nothing was calculated."}
    assert not any(t["role"] == "tool" for t in turns[turns.index(next(
        t for t in turns if t.get("text") == "Let it go up to 24")):])


def test_revision_replay_detects_a_changed_number():
    trace = json.loads(REVISION.read_text(encoding="utf-8"))
    tool = next(t for t in trace["sessions"][0]["turns"] if t["role"] == "tool")
    tool["result"]["envelopes"]["current"]["saving_eur"] += 0.01
    assert not ask.replay(trace, out=lambda *_: None)[0]


def test_offline_cli_replays_every_shipped_trace(capsys):
    args = type("A", (), {"offline": True, "trace": None, "record": None})
    assert ask.cli(args) == 0
    out = capsys.readouterr().out
    assert out.count("Replay identical") == 2 and "--- revising a comfort limit" in out
