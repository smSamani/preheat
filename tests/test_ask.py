import json
import re
from pathlib import Path

import pytest

from preheat import ask, sweep

TRACE = Path(ask.__file__).parent / "traces" / "demo.json"
TOOLCALL = {"type": "tool_call", "name": "compare", "arguments": {"ceiling_c": 22.5}}


def spy():
    calls = []
    return calls, lambda v: calls.append(v) or sweep.compare(v)


def scripted(*outs):
    it = iter(outs)
    return lambda messages: next(it)


def test_t12_unconfirmed_never_solves():
    trace = json.loads(TRACE.read_text(encoding="utf-8"))
    calls, fn = spy()
    keep = [s for s in trace["sessions"] if s["name"] in ("proposal cancelled", "unsupported edit")]
    ok, _ = ask.replay({"sessions": keep}, compare_fn=fn, out=lambda *_: None)
    assert ok and calls == []
    calls, fn = spy()
    s = ask.Session(scripted(TOOLCALL, {"type": "text", "text": "Only the maximum can change."},
                             {"type": "text", "text": "Which maximum?"}), fn)
    s.send("up to 22 and a half")
    assert s.pending == 22.5
    s.send("what about the night?")      # unrelated sentence: proposal discarded
    assert s.pending is None and calls == []
    s.send("yes")                        # nothing pending any more
    assert calls == []


def test_t13_numbers_from_tool_output():
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


def test_t14_replay_identical():
    trace = json.loads(TRACE.read_text(encoding="utf-8"))
    calls, fn = spy()
    ok, msg = ask.replay(trace, compare_fn=fn, out=lambda *_: None)
    assert ok, msg
    assert len(calls) == sum(1 for s in trace["sessions"] for t in s["turns"]
                             if t["role"] == "tool")


@pytest.mark.parametrize("bad", [
    {"type": "tool_call", "name": "compare", "arguments": {"ceiling_c": 27}},
    {"type": "tool_call", "name": "compare", "arguments": {"ceiling_c": "22.5"}},
    {"type": "tool_call", "name": "compare", "arguments": {"ceiling_c": 22.5, "x": 1}},
    {"type": "tool_call", "name": "delete", "arguments": {"ceiling_c": 22.5}},
])
def test_t15_malformed_tool_call(bad, capsys):
    calls, fn = spy()
    s = ask.Session(scripted(bad), fn)
    assert s.send("whatever") == [ask.FALLBACK]
    assert s.pending is None and calls == []


def test_t16_number_guard():
    s = ask.Session(scripted({"type": "text", "text": "That saves €0.50"}))
    assert s.send("hi") == [ask.FALLBACK]
