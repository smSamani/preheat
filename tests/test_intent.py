import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from preheat import assistant, gemini, intent, sweep, web
from preheat.intent import (CeilingRequest, Clarify, Compare, Decline, Explain, Failure,
                            ProposeCeiling, Unresolved)

ENVELOPE = json.loads((Path(__file__).parent.parent / "evals" / "fixtures"
                       / "gemini_envelope.json").read_text(encoding="utf-8"))


def body(name, arguments, *, calls=1, content=None):
    call = {"id": "call_1", "type": "function",
            "function": {"name": name, "arguments": arguments}}
    message = {"role": "assistant", "tool_calls": [call] * calls} if calls else {"role": "assistant"}
    if content is not None:
        message["content"] = content
    return {"choices": [{"index": 0, "finish_reason": "tool_calls", "message": message}]}


# --- Strictness ---------------------------------------------------------------------------------

def test_strict_float_rules():
    assert ProposeCeiling(kind="propose", value_c=22).value_c == 22          # int is accepted
    assert ProposeCeiling(kind="propose", value_c=22.5).value_c == 22.5
    for bad in (True, "22", float("nan"), float("inf"), 21.4, 24.1, None):
        with pytest.raises(ValidationError):
            ProposeCeiling(kind="propose", value_c=bad)


def test_models_are_frozen_and_forbid_extra_keys():
    item = Compare(kind="compare", metric="daily_cost")
    with pytest.raises(ValidationError):
        item.metric = "peak_electricity"
    with pytest.raises(ValidationError):
        Compare(kind="compare", metric="daily_cost", value_c=22.0)
    with pytest.raises(ValidationError):
        Compare(kind="compare", metric="cost")
    with pytest.raises(ValidationError):
        Clarify(kind="clarify", reason="because")
    with pytest.raises(ValidationError):
        Decline(kind="decline", reason="unit")


def test_unions_are_discriminated():
    assert intent.INTENT.validate_python({"kind": "propose", "value_c": 22.5}).value_c == 22.5
    assert isinstance(intent.INTENT.validate_python({"kind": "unresolved"}), Unresolved)
    with pytest.raises(ValidationError):
        intent.INTENT.validate_python({"kind": "ceiling_request"})     # model-only
    with pytest.raises(ValidationError):
        intent.MODEL_CHOICE.validate_python({"kind": "propose", "value_c": 22.5})
    with pytest.raises(ValidationError):
        intent.MODEL_CHOICE.validate_python({"kind": "clarify", "reason": "unit"})


# --- Tool allow-list and the model boundary ------------------------------------------------------

def test_allow_list_mapping():
    assert intent.TOOL_TO_KIND == {"show_comparison": "compare", "explain": "explain",
                                   "decline": "decline", "request_ceiling_change": "ceiling_request"}
    assert gemini.parse(body("show_comparison", '{"metric": "peak_electricity"}')) == Compare(
        kind="compare", metric="peak_electricity")
    assert gemini.parse(body("explain", '{"topic": "tighter_floor"}')) == Explain(
        kind="explain", topic="tighter_floor")
    assert gemini.parse(body("decline", '{"reason": "time_limited"}')) == Decline(
        kind="decline", reason="time_limited")
    assert gemini.parse(body("request_ceiling_change", "{}")) == CeilingRequest(kind="ceiling_request")


@pytest.mark.parametrize("response, code", [
    ({"nope": 1}, "unavailable"),
    ({"choices": []}, "unavailable"),
    ([], "unavailable"),
    (body("explain", '{"topic": "tariff"}', calls=2), "multiple_calls"),
    (body("x", "{}", calls=0, content="This saves €999"), "text_only"),
    (body("x", "{}", calls=0), "text_only"),
    (body("propose", '{"value_c": 22.5}'), "unknown_tool"),
    (body("compare", '{"ceiling_c": 22.5}'), "unknown_tool"),
    (body("€999_saved", "{}"), "unknown_tool"),
    (body("explain", "not json"), "invalid_args"),
    (body("explain", "[1]"), "invalid_args"),
    (body("explain", '{"topic": "tariff", "kind": "propose"}'), "invalid_args"),
    (body("explain", '{"topic": "money"}'), "invalid_args"),
    (body("explain", "{}"), "invalid_args"),
    (body("explain", '{"topic": "tariff", "value_c": 22.5}'), "invalid_args"),
    (body("request_ceiling_change", '{"value_c": 23}'), "invalid_args"),
    (body("show_comparison", '{"metric": "daily_cost", "value_c": 23}'), "invalid_args"),
    (body("explain", {"topic": "tariff"}), "invalid_args"),
])
def test_parse_failures(response, code):
    assert gemini.parse(response) == Failure(code)


def test_model_cannot_propose():
    """No tool takes a number, so no reply can become a ceiling proposal."""
    for response in (body("request_ceiling_change", '{"value_c": 23}'),
                     body("propose", '{"value_c": 23}'),
                     body("explain", '{"topic": "comfort", "value_c": 23}')):
        assert isinstance(gemini.parse(response), Failure)
    for tool in gemini.TOOLS:
        assert "value_c" not in json.dumps(tool)
        for prop in tool["function"]["parameters"]["properties"].values():
            assert "enum" in prop and "type" in prop and set(prop) == {"enum", "type"}
    decision = intent.decide("hmm, whatever", lambda m: CeilingRequest(kind="ceiling_request"))
    assert decision.intent == Clarify(kind="clarify", reason="type_one_value")
    assert decision.source == "gemini"


def test_envelope_fixture_parses():
    assert gemini.parse(ENVELOPE) == Compare(kind="compare", metric="daily_cost")
    assert "extra_content" in ENVELOPE["choices"][0]["message"]["tool_calls"][0]


def test_schema_has_no_ref():
    text = json.dumps(gemini.TOOLS)
    assert "$ref" not in text and "$defs" not in text and "anyOf" not in text
    names = [t["function"]["name"] for t in gemini.TOOLS]
    assert names == ["show_comparison", "explain", "decline", "request_ceiling_change"]
    for tool in gemini.TOOLS:
        params = tool["function"]["parameters"]
        assert params["type"] == "object" and "kind" not in params["properties"]
    assert gemini.TOOLS[3]["function"]["parameters"] == {"type": "object", "properties": {},
                                                          "required": []}


def test_request_shape():
    active = gemini.settings(22.5, "outdoor_minus3")
    req = gemini.build_request("is it expensive?", active, "gemini-3.5-flash-lite")
    assert {k: req[k] for k in ("model", "temperature", "max_tokens", "tool_choice")} == {
        "model": "gemini-3.5-flash-lite", "temperature": 0, "max_tokens": 200,
        "tool_choice": "required"}
    assert req["tools"] == gemini.TOOLS and len(req["tools"]) == 4
    assert gemini.TIMEOUT_S == 20 and gemini.MAX_BYTES == 1_000_000
    assert gemini.ENDPOINT.startswith("https://")
    assert set(gemini.STAMP) == {"endpoint", "temperature", "tool_choice", "max_tokens",
                                 "system_prompt_sha256", "tools_sha256"}
    assert len(gemini.STAMP["tools_sha256"]) == 64


def test_payload_has_no_history():
    sent = []

    def fake_open(request, timeout):
        sent.append((json.loads(request.data), timeout, request.full_url))
        raise OSError("stop")

    messages = [{"role": "user", "content": "SECRET EARLIER QUESTION"},
                {"role": "assistant", "content": "SECRET EARLIER ANSWER"},
                {"role": "user", "content": "hmm, something odd"}]
    with patch.object(gemini._OPENER, "open", fake_open):
        reply = web.interpret_with_source({"messages": messages, "key": "example_test_key",
                                           "model": "gemini-3.5-flash-lite",
                                           "scenario": {"ceiling": 23, "case": "capacity_8"}})
    (request, timeout, url), = sent
    assert timeout == 20 and url == gemini.ENDPOINT
    assert [m["role"] for m in request["messages"]] == ["system", "user"]
    assert request["messages"][1]["content"] == "hmm, something odd"
    text = json.dumps(request, ensure_ascii=False)
    assert "SECRET" not in text
    system = request["messages"][0]["content"].removeprefix(gemini.SYSTEM_PROMPT)
    assert json.loads(system) == {"scenario": assistant.fixture.CASE_LABELS["capacity_8"],
                                  "ceiling_c": 23.0, "ceiling_range_c": [21.5, 24.0]}
    assert reply["source"] == "rules" and reply["note"] == intent.NOTES["unavailable"]


def test_only_https_and_no_redirects():
    assert gemini.fetch("x", {}, "k", "m", "http://example.test/") == Failure("unavailable")
    request = gemini.urllib.request.Request("https://example.test/")
    assert gemini._NoRedirect().redirect_request(request, None, 302, "Found", {}, "https://x") is None


def test_transport_failures_become_codes():
    import http.client
    import urllib.error

    class Reply:
        def __init__(self, data):
            self.data = data

        def read(self, n=-1):
            return self.data[:n] if n >= 0 else self.data

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def run(action):
        with patch.object(gemini._OPENER, "open", action):
            return gemini.ask("x", {}, "k", "m")

    def raising(error):
        def action(*a, **k):
            raise error
        return action

    assert run(raising(TimeoutError())) == Failure("timeout")
    assert run(raising(urllib.error.URLError(TimeoutError()))) == Failure("timeout")
    assert run(raising(urllib.error.URLError("refused"))) == Failure("unavailable")
    assert run(raising(http.client.IncompleteRead(b"ab", 10))) == Failure("unavailable")
    assert run(raising(ConnectionResetError())) == Failure("unavailable")
    assert run(lambda *a, **k: Reply(b"x" * (gemini.MAX_BYTES + 5))) == Failure("unavailable")
    assert run(lambda *a, **k: Reply(b"not json")) == Failure("unavailable")
    assert run(lambda *a, **k: Reply(json.dumps(ENVELOPE).encode())) == Compare(
        kind="compare", metric="daily_cost")


# --- Policy -------------------------------------------------------------------------------------

def never(_message):
    raise AssertionError("the model must not be asked")


def test_policy_table():
    explain_comfort = Explain(kind="explain", topic="comfort")
    # grammar Proposal or Block: final, model not asked
    d = intent.decide("max 23", never)
    assert d.intent == ProposeCeiling(kind="propose", value_c=23.0) and d.source == "rules"
    d = intent.decide("max 23 at night", never)
    assert d.intent == Decline(kind="decline", reason="unsupported_floor") and d.source == "rules"
    # resolved read-only rule: final, model not asked
    d = intent.decide("How much do I save?", never)
    assert d.intent == Compare(kind="compare", metric="daily_cost") and d.source == "rules"
    # Unresolved, no key
    d = intent.decide("tell me a joke")
    assert d.intent == Explain(kind="explain", topic="out_of_scope")
    assert (d.source, d.code, d.note) == ("rules", "", "")
    # Unresolved, valid choices
    for choice in (Compare(kind="compare", metric="peak_electricity"), explain_comfort,
                   Decline(kind="decline", reason="negated_action")):
        d = intent.decide("tell me a joke", lambda m, c=choice: c)
        assert d.intent == choice and d.source == "gemini" and d.note == ""
    d = intent.decide("tell me a joke", lambda m: CeilingRequest(kind="ceiling_request"))
    assert d.intent == Clarify(kind="clarify", reason="type_one_value") and d.source == "gemini"
    # Unresolved, failure
    for code in ("unavailable", "timeout", "text_only", "multiple_calls", "unknown_tool",
                 "invalid_args"):
        d = intent.decide("tell me a joke", lambda m, c=code: Failure(c))
        assert d.intent == Explain(kind="explain", topic="out_of_scope")
        assert d.source == "rules" and d.code == code and d.note == intent.NOTES[code]


def test_model_is_logged_but_not_used_when_asked_for_every_message():
    asked = []
    choice = Explain(kind="explain", topic="tariff")
    d = intent.decide("max 23", lambda m: asked.append(m) or choice, always_ask=True)
    assert d.intent.kind == "propose" and d.model == choice and asked == ["max 23"]
    d = intent.decide("How much do I save?", lambda m: choice, always_ask=True)
    assert d.intent.kind == "compare" and d.source == "rules" and d.model == choice


def test_rules_intent_is_read_only():
    for text in ("max 23", "set it to 22.5", "try 23", "22"):
        assert isinstance(intent.rules_intent(text), (Unresolved, Explain, Compare, Decline))
        assert intent.rules_intent(text).kind != "propose"
    assert intent.rules_intent("tell me a joke") == Unresolved(kind="unresolved")
    assert intent.rules_intent("what would a tighter 21:00 floor cost?") == Explain(
        kind="explain", topic="tighter_floor")
    assert intent.rules_intent("switch the heating off") == Decline(
        kind="decline", reason="unsupported_floor")
    assert intent.rules_intent("never mind") == Decline(kind="decline", reason="negated_action")


@pytest.mark.parametrize("text, expected", [
    ("Is the house warm at 22:00?", Explain(kind="explain", topic="comfort")),
    ("What happens at 22:00?", Explain(kind="explain", topic="out_of_scope")),
    ("How much does better insulation save?", Compare(kind="compare", metric="insulation_difference")),
    ("Compare the two insulation levels.", Compare(kind="compare", metric="insulation_difference")),
    ("Why does insulation help?", Explain(kind="explain", topic="insulation")),
    ("How much peak electricity do we avoid?", Compare(kind="compare", metric="peak_electricity")),
    ("How much do I save?", Compare(kind="compare", metric="daily_cost")),
    ("What is the baseline?", Explain(kind="explain", topic="baseline")),
    ("What are the assumptions?", Explain(kind="explain", topic="assumptions")),
    ("What is the tariff?", Explain(kind="explain", topic="tariff")),
    ("Is this realistic for a whole year?", Explain(kind="explain", topic="limits")),
    ("Why preheat at all?", Explain(kind="explain", topic="preheating")),
    ("عایق بهتر چقدر صرفه‌جویی داره؟", Compare(kind="compare", metric="insulation_difference")),
    ("فرض‌ها چیه؟", Explain(kind="explain", topic="assumptions")),
    ("تعرفه چیه؟", Explain(kind="explain", topic="tariff")),
    ("هزینه چقدره؟", Compare(kind="compare", metric="daily_cost")),
    ("مصرف برق عصر چقدر کم میشه؟", Compare(kind="compare", metric="peak_electricity")),
    ("هزینه یه کف ۲۱ درجه‌ای تو ساعت ۲۱ چقدره؟", Decline(kind="decline", reason="unsupported_floor")),
])
def test_rules_regressions(text, expected):
    assert intent.decide(text).intent == expected


# --- Notes and provider strings -----------------------------------------------------------------

def test_notes_cover_every_failure_code():
    for code in ("unavailable", "timeout", "text_only", "multiple_calls", "unknown_tool",
                 "invalid_args", "number_check"):
        assert isinstance(intent.NOTES[code], str) and intent.NOTES[code]
    assert not any("€" in note or any(ch.isdigit() for ch in note) for note in intent.NOTES.values())


def test_provider_strings_never_visible():
    hostile = [body("€999_saved", '{"x": "This saves €999"}'),
               body("x", "{}", calls=0, content="This saves €999"),
               body("explain", '{"topic": "This saves €999"}'),
               body("explain", '{"topic": "tariff", "note": "This saves €999"}'),
               body("explain", '{"topic": "tariff"}', calls=2)]
    for response in hostile:
        with patch.object(gemini._OPENER, "open") as opener:
            opener.return_value.__enter__.return_value.read.return_value = json.dumps(response).encode()
            out = web.interpret_with_source({
                "messages": [{"role": "user", "content": "tell me a joke"}],
                "key": "example_test_key", "model": "gemini-3.5-flash-lite"})
        text = json.dumps(out, ensure_ascii=False)
        assert "999" not in text and "€" not in text
        assert out["source"] == "rules" and out["note"] in intent.NOTES.values()


# --- Review round: typed boundary and malformed provider responses -----------------------------

def test_the_grid_is_enforced_on_proposals():
    for bad in (23.04, 22.55, 21.51, 23.95):
        with pytest.raises(ValidationError):
            ProposeCeiling(kind="propose", value_c=bad)
    for good in (21.5, 22.0, 22.5, 23.1, 24.0, 24):
        assert ProposeCeiling(kind="propose", value_c=good).value_c == good


@pytest.mark.parametrize("returned", [
    ProposeCeiling(kind="propose", value_c=23.0), Unresolved(kind="unresolved"),
    Clarify(kind="clarify", reason="unit"), {"kind": "propose", "value_c": 23.0},
    {"kind": "compare", "metric": "invented"}, "yes", 23.0, None, 42,
])
def test_a_custom_callback_cannot_return_anything_but_a_model_choice(returned):
    decision = intent.decide("hmm, something odd", lambda message: returned)
    assert decision.intent == Explain(kind="explain", topic="out_of_scope")
    assert decision.source == "rules" and decision.code == "invalid_args"
    assert not isinstance(decision.intent, ProposeCeiling)


def test_a_callback_proposal_is_also_refused_when_the_model_is_always_asked():
    decision = intent.decide("max 23", lambda m: ProposeCeiling(kind="propose", value_c=21.5),
                             always_ask=True)
    assert decision.intent == ProposeCeiling(kind="propose", value_c=23.0)
    assert decision.model == Failure("invalid_args")


def test_a_valid_callback_choice_is_still_used():
    choice = Compare(kind="compare", metric="daily_cost")
    decision = intent.decide("hmm, something odd", lambda m: choice)
    assert decision.intent == choice and decision.source == "gemini"


def _wrap(**message):
    return {"choices": [{"message": message}]}


@pytest.mark.parametrize("response, code", [
    ({"choices": 42}, "unavailable"),
    ({"choices": "x"}, "unavailable"),
    ({"choices": {}}, "unavailable"),
    ({"choices": [42]}, "unavailable"),
    ({"choices": [{}]}, "unavailable"),
    ({"choices": [{"message": 7}]}, "unavailable"),
    ({"choices": [{"message": None}]}, "unavailable"),
    ([], "unavailable"), ("text", "unavailable"), (None, "unavailable"), (42, "unavailable"),
    (_wrap(tool_calls=42), "invalid_args"),
    (_wrap(tool_calls="x"), "invalid_args"),
    (_wrap(tool_calls={"function": {}}), "invalid_args"),
    (_wrap(tool_calls=[42]), "invalid_args"),
    (_wrap(tool_calls=[None]), "invalid_args"),
    (_wrap(tool_calls=[{}]), "invalid_args"),
    (_wrap(tool_calls=[{"function": 5}]), "invalid_args"),
    (_wrap(tool_calls=[{"function": {}}]), "unknown_tool"),
    (_wrap(tool_calls=[{"function": {"name": 5, "arguments": "{}"}}]), "unknown_tool"),
    (_wrap(tool_calls=[{"function": {"name": "explain"}}]), "invalid_args"),
    (_wrap(tool_calls=[{"function": {"name": "explain", "arguments": 5}}]), "invalid_args"),
    (_wrap(tool_calls=[{"function": {"name": "explain", "arguments": "[1]"}}]), "invalid_args"),
    (_wrap(tool_calls=[]), "text_only"),
    (_wrap(tool_calls=None, content="hello"), "text_only"),
    (_wrap(content="hello"), "text_only"),
])
def test_malformed_responses_give_codes_never_exceptions(response, code):
    assert gemini.parse(response) == Failure(code)


def test_malformed_responses_are_safe_in_the_evaluation_scorer_too():
    from preheat import evals
    for response in ({"choices": 42}, _wrap(tool_calls=42), _wrap(tool_calls=[42]), [], None,
                     {"choices": [{"message": 7}]}):
        assert evals.provider_strings(response) == []
