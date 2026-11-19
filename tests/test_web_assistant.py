import http.client
import io
import json
import re
import threading
from email.message import Message
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from preheat import assistant, fixture, gemini, intent, optimise, web

ROOT = Path(__file__).parent.parent
KEY = {"key": "example_test_key", "model": "gemini-3.5-flash-lite"}
INTERPRET_KEYS = {"text", "comparison", "ceiling", "source", "note"}


@pytest.fixture(autouse=True)
def fresh_cache():
    web.scenario.cache_clear()
    yield
    web.scenario.cache_clear()


def ask(text, selected=None, **credentials):
    payload = {"messages": [{"role": "user", "content": text}], **credentials}
    if selected:
        payload["scenario"] = selected
    return web.interpret_with_source(payload)


def tool_body(name, arguments):
    return {"choices": [{"message": {"tool_calls": [
        {"id": "c", "type": "function", "function": {"name": name, "arguments": arguments}}]}}]}


def gemini_reply(body, text="tell me something odd", selected=None):
    """Run one request with Gemini answering `body` (a decoded response or a Failure-making error)."""
    with patch.object(gemini._OPENER, "open") as opener:
        opener.return_value.__enter__.return_value.read.return_value = json.dumps(body).encode()
        return ask(text, selected, **KEY), opener


class CountSolves:
    """Spy on the LP: records the ceiling of every compare_pair call."""

    def __init__(self, monkeypatch):
        self.ceilings = []
        real = optimise.compare_pair

        def spy(ceiling, day, *a, **k):
            self.ceilings.append(ceiling)
            return real(ceiling, day, *a, **k)

        monkeypatch.setattr(web.optimise, "compare_pair", spy)


# --- Built-in rules -----------------------------------------------------------------------

def test_insulation_question_compares_the_two_houses():
    selected = {"ceiling": 23, "case": "outdoor_minus3"}
    reply = ask("How much does better insulation save?", selected)
    env = web.scenario(selected)["envelopes"]
    cur, ins = env["current"], env["insulated"]
    rows = {row["label"]: row for row in reply["comparison"]["rows"]}
    rule_diff = cur["baseline"]["cost_eur"] - ins["baseline"]["cost_eur"]
    opt_diff = cur["optimised"]["cost_eur"] - ins["optimised"]["cost_eur"]
    assert rows["Day cost, one-hour rule"]["value"] == f"€{rule_diff:.2f} less"
    assert rows["Day cost, cost-minimising schedule"]["value"] == f"€{opt_diff:.2f} less"
    assert rows["Preheating saving within each house"]["value"] == (
        f"€{cur['saving_eur']:.2f} / €{ins['saving_eur']:.2f}")
    assert "23.0 °C" in reply["comparison"]["title"] and reply["source"] == "rules"


def test_every_rules_reply_is_grounded_in_every_scenario():
    questions = ["How much does better insulation save?", "How much peak electricity do we avoid?",
                 "How much do I save?", "What are the assumptions?", "What is the tariff?",
                 "What is the comfort range?", "Set the minimum to 22", "Try 22 or 23",
                 "Try 25", "max 23 at night", "max 23 only in the evening", "keep it at 22",
                 "a bit warmer please", "don't set it to 23", "72 °F", "22.45",
                 "would 22 save money?", "what would a tighter 21:00 floor cost?",
                 "عایق بهتر چقدر صرفه‌جویی داره؟", "فرض‌ها چیه؟", "تعرفه چیه؟", "هزینه چقدره؟",
                 "مصرف برق عصر چقدر کم میشه؟", "حداکثر ۲۳ ولی شب ۱۸", "۷۲ درجه فارنهایت",
                 "بین ۲۲ و ۲۳", "سقف ۲۲٫۴۵", "tell me a joke"]
    for case in fixture.CASES:
        for ceiling in fixture.CEILINGS:
            results = web.scenario({"ceiling": ceiling, "case": case})
            for q in questions:
                reply = assistant.local_reply(q, results)
                shown = assistant.with_topic_data(intent.decide(q).intent, results)
                _, problems = assistant.ground(reply, shown, bool(assistant.PERSIAN.search(q)))
                assert problems == [], (case, ceiling, q, problems)


def test_clarify_and_decline_templates_exist_in_both_languages():
    results = {"ceiling": 22.5, "case": "nominal", "envelopes": {}}
    seen = set()
    for reason in intent.CLARIFY_REASONS:
        for persian in (False, True):
            reply = assistant.render(intent.Clarify(kind="clarify", reason=reason), results, persian)
            assert reply["text"] and reply["text"] not in seen
            seen.add(reply["text"])
            assert bool(assistant.PERSIAN.search(reply["text"])) == persian
    for reason in intent.DECLINE_REASONS:
        for persian in (False, True):
            reply = assistant.render(intent.Decline(kind="decline", reason=reason), results, persian)
            assert reply["text"] and reply["text"] not in seen
            seen.add(reply["text"])
            assert bool(assistant.PERSIAN.search(reply["text"])) == persian
    for topic in intent.TOPICS:
        for persian in (False, True):
            reply = assistant.render(intent.Explain(kind="explain", topic=topic), results, persian)
            assert reply["text"]


def test_rules_mode_reports_its_source():
    assert ask("How much does better insulation save?")["source"] == "rules"


def test_a_proposal_is_returned_without_a_solve(monkeypatch):
    spy = CountSolves(monkeypatch)
    assert ask("max 23") == {"ceiling": 23.0, "source": "rules"}
    assert ask("سقف رو بذار روی ۲۳٫۵ درجه") == {"ceiling": 23.5, "source": "rules"}
    assert spy.ceilings == []


def test_blocks_and_topics_run_no_solver(monkeypatch):
    spy = CountSolves(monkeypatch)
    for text in ("max 23 at night", "don't set it to 23", "72 °F", "what is the tariff?",
                 "is the house comfortable?", "tell me a joke", "what are the assumptions?"):
        reply = ask(text, {"ceiling": 22.5, "case": "capacity_8"})
        assert "text" in reply and "ceiling" not in reply
    assert spy.ceilings == []


def test_comparison_solves_once_per_scenario(monkeypatch):
    spy = CountSolves(monkeypatch)
    selected = {"ceiling": 23, "case": "capacity_3"}
    ask("How much do I save?", selected)
    first = len(spy.ceilings)
    assert first == len(fixture.ENVELOPES)
    ask("How much peak electricity do we avoid?", selected)
    ask("How much does better insulation save?", selected)
    assert len(spy.ceilings) == first                  # served from the cache
    ask("How much do I save?", {"ceiling": 23.5, "case": "capacity_3"})
    assert len(spy.ceilings) == 2 * first


def test_invalid_scenarios_and_payloads_are_rejected():
    for selected in ({"ceiling": 30}, {"ceiling": "23"}, {"ceiling": True}, {"ceiling": 23, "case": "x"}):
        with pytest.raises(ValueError):
            ask("How much do I save?", selected)
    with pytest.raises(ValueError):
        web.interpret_with_source({"messages": []})
    with pytest.raises(ValueError):
        web.interpret_with_source({"messages": [{"role": "assistant", "content": "x"}]})
    with pytest.raises(ValueError):
        ask("x" * 801)
    with pytest.raises(ValueError):
        ask("hi", key="bad key", model="gemini-x")
    with pytest.raises(ValueError):
        ask("hi", key="example_test_key", model="example-model")


def test_the_browser_history_is_accepted_but_not_used():
    history = [{"role": "user", "content": "How much do I save?"},
               {"role": "assistant", "content": "answer"},
               {"role": "user", "content": "max 23"}]
    assert web.interpret_with_source({"messages": history}) == {"ceiling": 23.0, "source": "rules"}


# --- Number grounding ---------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "This saves 999 euros.",
    "This saves €999 on this day.",
    "The better-insulated house saves €0.54 a day.",        # real number, wrong house
    "The current house saves €6.61 a day.",                 # real number, wrong metric
    "The current house costs €0.54 to heat.",               # saving stated as a cost
    "The current house avoids 3.38 kW.",                    # right value, wrong unit
    "The current house saves 3.38 €.",
    "Savings are €-0.54.",                                  # wrong sign
    "Preheating starts at 14:00.",                          # invented clock time
    "It saves 54 cents.",
    "The better-insulated house avoids 56.3%.",
    "It costs €7 a day.",                                   # rounded to a misleading integer
    "۹۹۹ یورو صرفه‌جویی",
    "خانه با عایق بهتر 0.54 یورو کمتر می‌شه.",
])
def test_ungrounded_numbers_are_caught(text):
    results = web.scenario({"ceiling": 22.5})
    assert assistant.ungrounded_numbers(text, results)
    reply, problems = assistant.ground({"text": text}, results, False)
    assert problems and reply == {"text": assistant.SAFE_TEXT[False]}


@pytest.mark.parametrize("text", [
    "The current house saves €0.54 a day.",
    "The current house avoids 3.38 kWh (56.3%).",
    "The peak tariff runs from 17:00 to 22:00 at €0.38/kWh.",
    "The ceiling is 22.5 °C.",
])
def test_grounded_numbers_pass(text):
    assert assistant.ungrounded_numbers(text, web.scenario({"ceiling": 22.5})) == []


def test_a_card_with_a_wrong_house_number_is_withheld():
    results = web.scenario({"ceiling": 22.5})
    reply = assistant.comparison_reply(results, False, False, True)
    rows = reply["comparison"]["rows"]                # each house now shows the other's saving
    rows[0]["value"], rows[1]["value"] = rows[1]["value"], rows[0]["value"]
    guarded, problems = assistant.ground(reply, results, False)
    assert problems and "comparison" not in guarded




# --- Gemini: routing only, never text ---------------------------------------------------------

def test_gemini_is_not_called_when_the_rules_resolve_the_message():
    for text in ("max 23", "max 23 at night", "How much do I save?", "what is the tariff?"):
        with patch.object(gemini._OPENER, "open") as opener:
            reply = ask(text, **KEY)
        assert not opener.called and reply["source"] == "rules" and "note" not in reply


def test_gemini_routes_an_unplaced_question():
    reply, opener = gemini_reply(tool_body("show_comparison", '{"metric": "peak_electricity"}'))
    assert opener.called and reply["source"] == "gemini" and "note" not in reply
    assert reply["comparison"] == ask("How much peak electricity do we avoid?")["comparison"]
    reply, _ = gemini_reply(tool_body("explain", '{"topic": "tariff"}'))
    assert reply["source"] == "gemini"
    assert reply["text"] == assistant.topic_text("tariff", {"ceiling": 22.5, "case": "nominal"}, False)["text"]


def test_gemini_ceiling_request_becomes_a_question_not_a_proposal(monkeypatch):
    spy = CountSolves(monkeypatch)
    reply, _ = gemini_reply(tool_body("request_ceiling_change", "{}"), "make it cosy")
    assert reply == {"text": assistant.clarify_text("type_one_value", False), "source": "gemini"}
    reply, _ = gemini_reply(tool_body("request_ceiling_change", '{"value_c": 23}'), "make it cosy")
    assert "ceiling" not in reply and reply["source"] == "rules"
    assert reply["note"] == intent.NOTES["invalid_args"]
    assert spy.ceilings == []


@pytest.mark.parametrize("body, code", [
    (tool_body("propose", '{"value_c": 23}'), "unknown_tool"),
    (tool_body("explain", '{"topic": "money"}'), "invalid_args"),
    ({"choices": [{"message": {"content": "This saves €999"}}]}, "text_only"),
    ({"nope": 1}, "unavailable"),
])
def test_a_gemini_failure_gives_the_out_of_scope_text_and_a_fixed_note(body, code):
    reply, _ = gemini_reply(body)
    assert reply == {"text": assistant.topic_text("out_of_scope", {"ceiling": 22.5, "case": "nominal"},
                                                   False)["text"],
                     "source": "rules", "note": intent.NOTES[code]}


def test_gemini_cannot_turn_a_minimum_request_into_a_ceiling():
    reply, opener = gemini_reply(tool_body("request_ceiling_change", "{}"), "Set the minimum to 22 °C")
    assert not opener.called and "ceiling" not in reply and "minimum" in reply["text"]


# --- Apply path ---------------------------------------------------------------------------------

def call_handler(path, payload, method="POST", port=8765):
    """Run the real request handler in memory: no socket."""
    handler = Dashboard.__new__(Dashboard)
    raw = json.dumps(payload).encode()
    headers = Message()
    headers["Host"] = f"127.0.0.1:{port}"
    headers["Content-Type"] = "application/json"
    headers["Content-Length"] = str(len(raw))
    handler.headers, handler.path, handler.command = headers, path, method
    handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
    handler.server = SimpleNamespace(server_port=port)
    handler.request_version, handler.requestline = "HTTP/1.1", f"{method} {path} HTTP/1.1"
    handler.client_address = ("127.0.0.1", 1)
    getattr(handler, f"do_{method}")()
    head, _, body = handler.wfile.getvalue().partition(b"\r\n\r\n")
    status = int(head.split(b" ", 2)[1])
    return status, json.loads(body)


Dashboard = web.Dashboard


def test_apply_path(monkeypatch):
    """What the page does on a proposal: /api/interpret returns {ceiling} and solves nothing for
    it; only the following /api/scenario call (the Apply click) solves that value."""
    spy = CountSolves(monkeypatch)
    scenario = {"ceiling": 22.5, "case": "nominal"}
    status, reply = call_handler("/api/interpret", {
        "messages": [{"role": "user", "content": "max 23"}], "scenario": scenario})
    assert status == 200 and reply == {"ceiling": 23.0, "source": "rules"}
    assert 23.0 not in spy.ceilings and spy.ceilings == []
    status, data = call_handler("/api/scenario", {"ceiling": reply["ceiling"], "case": "nominal"})
    assert status == 200 and data["ceiling"] == 23.0
    assert spy.ceilings == [23.0] * len(fixture.ENVELOPES)


def test_the_apply_handler_sets_the_slider_to_the_proposal():
    """Read-only check of the locked page script."""
    source = (ROOT / "preheat" / "ui" / "app.js").read_text(encoding="utf-8")
    block = re.search(r'\$\("apply"\)\.addEventListener\("click",\s*\(\)\s*=>\s*\{(.*?)\n\}\);',
                      source, re.S)
    assert block, "apply handler not found"
    body = block.group(1)
    assert re.search(r"ceiling\.value\s*=\s*proposedCeiling", body)
    assert re.search(r"\brefresh\(\)", body)


def test_response_key_sets_match_the_documented_shapes():
    doc = (ROOT / "docs" / "dashboard.md").read_text(encoding="utf-8")
    line = next(l for l in doc.splitlines() if l.startswith("- `POST /api/interpret"))
    documented = set(re.findall(r"`(\w+)`", line.split("It also returns")[0].split(": one of")[1]))
    documented |= set(re.findall(r"`(\w+)`", line.split("It also returns")[1]))
    assert INTERPRET_KEYS <= documented | {"comparison"}
    shapes = []
    shapes.append(ask("what is the tariff?"))                         # text
    shapes.append(ask("How much do I save?"))                         # text + comparison
    shapes.append(ask("max 23"))                                      # ceiling
    shapes.append(gemini_reply({"nope": 1})[0])                       # text + note
    assert [set(s) for s in shapes] == [
        {"text", "source"}, {"text", "comparison", "source"}, {"ceiling", "source"},
        {"text", "source", "note"}]
    for shape in shapes:
        assert set(shape) <= INTERPRET_KEYS
        assert shape["source"] in ("rules", "gemini")
    assert set(shapes[1]["comparison"]) == {"title", "rows"}
    assert all(set(row) == {"label", "value", "detail"} for row in shapes[1]["comparison"]["rows"])
    status, config = call_handler("/api/config", {}, method="GET")
    assert status == 200 and set(config) == {"cases", "ceiling", "prices"}


def test_handler_errors_keep_their_shape():
    assert call_handler("/api/interpret", {"messages": []})[0] == 400
    assert call_handler("/api/interpret", {"messages": [{"role": "user", "content": "x"}],
                                           "scenario": {"ceiling": 40}})[0] == 400
    status, body = call_handler("/api/nowhere", {})
    assert status == 404 and set(body) == {"error"}
    assert call_handler("/api/scenario", {"ceiling": 22.5}, port=8765)[0] == 200


def test_the_server_sets_a_read_deadline():
    assert web.Dashboard.timeout == 10


# --- Local HTTP boundary (real socket) ----------------------------------------------------

@pytest.fixture
def server():
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", 0), web.Dashboard)
    except OSError as error:
        pytest.skip(f"cannot bind a loopback port: {error}")
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv.server_port
    srv.shutdown()
    srv.server_close()


def request(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request(method, path, body=body, headers=headers or {})
    resp = conn.getresponse()
    status = resp.status
    resp.read()
    conn.close()
    return status


@pytest.mark.loopback
def test_server_accepts_only_local_json_requests(server):
    port = server
    body = json.dumps({"ceiling": 22.5})
    local = {"Host": f"127.0.0.1:{port}", "Content-Type": "application/json"}
    assert request(port, "POST", "/api/scenario", body, local) == 200
    assert request(port, "POST", "/api/scenario", body, {**local, "Host": "evil.example"}) == 403
    assert request(port, "POST", "/api/scenario", body,
                   {**local, "Origin": "http://evil.example"}) == 403
    assert request(port, "POST", "/api/scenario", body,
                   {**local, "Content-Type": "text/plain"}) == 400
    assert request(port, "GET", "/api/config", headers={"Host": f"localhost:{port}"}) == 200
    assert request(port, "GET", "/../README.md", headers={"Host": f"localhost:{port}"}) == 404


def test_outbound_sockets_are_blocked_in_tests():
    import socket
    with pytest.raises(OSError):
        socket.create_connection(("example.com", 443), timeout=1)
    with pytest.raises(OSError):
        socket.socket().connect(("93.184.216.34", 443))
