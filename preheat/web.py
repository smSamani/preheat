"""Local dashboard: solver results, built-in assistant rules and an optional Gemini intent router."""
import json
import re
from functools import lru_cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock

from . import assistant, fixture, gemini, intent, optimise, sweep

ASSETS = Path(__file__).with_name("ui")
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}
SOLVER_LOCK = Lock()


def _checked(payload):
    """(ceiling, case) from a scenario payload, or ValueError. Runs no solver."""
    ceiling = payload.get("ceiling")
    case = payload.get("case", "nominal")
    if (type(ceiling) not in (int, float) or not sweep.LO <= ceiling <= sweep.HI
            or case not in fixture.CASES):
        raise ValueError("Choose a valid winter scenario and a ceiling between 21.5 and 24 °C.")
    return round(ceiling, 1), case


@lru_cache(maxsize=64)
def _solved(ceiling, case):
    envelopes = {}
    with SOLVER_LOCK:
        for envelope in fixture.ENVELOPES:
            day = fixture.day(case, envelope)
            pair = optimise.compare_pair(ceiling, day)
            if pair["status"] != "ok":
                envelopes[envelope] = pair
                continue
            for mode in ("baseline", "optimised"):
                result = pair[mode]
                pair[mode] = {
                    "power": result.p,
                    "temperature": result.T,
                    "evening_kwh": result.evening_kwh,
                    "cost_eur": result.cost_eur,
                }
            envelopes[envelope] = pair
    return {"ceiling": ceiling, "case": case, "envelopes": envelopes,
            "floors": fixture.floors().tolist(), "evening": list(fixture.EVENING)}


def scenario(payload):
    """Solver results for one (ceiling, case), cached by that pair."""
    return _solved(*_checked(payload))


scenario.cache_clear = _solved.cache_clear


def _validated(payload):
    """(key, model, message, selected scenario) from an interpret payload, or ValueError.
    The browser also sends its recent history; only the latest message is used."""
    key, model, messages = (payload.get(field) for field in ("key", "model", "messages"))
    if key and (not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{12,256}", key)):
        raise ValueError("Enter a valid Gemini API key in Settings.")
    if key and (not isinstance(model, str) or not re.fullmatch(r"gemini-[\w.-]{1,80}", model, re.ASCII)):
        raise ValueError("Enter a valid Gemini model ID in Settings.")
    if (not isinstance(messages, list) or not 1 <= len(messages) <= 13
            or any(not isinstance(item, dict) or item.get("role") not in ("user", "assistant")
                   or not isinstance(item.get("content"), str)
                   or not 1 <= len(item["content"]) <= 1400 for item in messages)
            or messages[-1]["role"] != "user" or len(messages[-1]["content"]) > 800):
        raise ValueError("Enter a message of up to 800 characters.")
    selected = payload.get("scenario", {"ceiling": fixture.REFERENCE_CEILING})
    if not isinstance(selected, dict):
        raise ValueError("Select a valid scenario.")
    return key, model, messages[-1]["content"], selected


def _interpret(payload):
    """Return (reply, source, note); source is "rules" or "gemini".

    The routing decision is made first and runs no solver. Only a read-only comparison then asks
    for solver results (cached). A proposed ceiling is returned as is: nothing is solved for it
    until the person applies it. note is a fixed text from intent.NOTES or ""."""
    key, model, message, selected = _validated(payload)
    ceiling, case = _checked(selected)
    ask = None
    if key:
        active = gemini.settings(ceiling, case)
        ask = lambda text: gemini.ask(text, active, key, model)    # noqa: E731
    decision = intent.decide(message, ask)
    persian = bool(assistant.PERSIAN.search(message))
    if isinstance(decision.intent, intent.Compare):
        results = _solved(ceiling, case)
    else:
        results = {"ceiling": ceiling, "case": case, "envelopes": {}}
    results = assistant.with_topic_data(decision.intent, results)
    reply, problems = assistant.ground(assistant.render(decision.intent, results, persian),
                                       results, persian)
    if problems:
        return reply, "rules", intent.NOTES["number_check"]
    return reply, decision.source, decision.note


def interpret(payload):
    return _interpret(payload)[0]


def interpret_with_source(payload):
    """HTTP variant: tells the browser whether Gemini or the built-in rules produced the reply."""
    reply, source, note = _interpret(payload)
    return {**reply, "source": source, **({"note": note} if note else {})}


class Dashboard(BaseHTTPRequestHandler):
    timeout = 10        # seconds a connection may stall before the server drops it

    def send(self, status, body, media_type):
        self.send_response(status)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'self'; script-src 'self'; "
                         "frame-ancestors 'self'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def respond(self, status, data):
        self.send(status, json.dumps(data, allow_nan=False).encode(), "application/json")

    def local_request(self):
        port = self.server.server_port
        hosts = (f"127.0.0.1:{port}", f"localhost:{port}")
        origin = self.headers.get("Origin")
        if self.headers.get("Host") in hosts and (origin is None or origin == f"http://{self.headers['Host']}"):
            return True
        self.respond(HTTPStatus.FORBIDDEN, {"error": "Open the dashboard from its local address."})
        return False

    def do_GET(self):
        if not self.local_request():
            return
        if self.path == "/api/config":
            self.respond(200, {"cases": fixture.CASE_LABELS, "ceiling": fixture.REFERENCE_CEILING,
                               "prices": [fixture.PRICE_NORMAL, fixture.PRICE_EVENING]})
            return
        asset = STATIC.get(self.path)
        if asset is None or not (ASSETS / asset[0]).is_file():
            self.respond(404, {"error": "Page not found."})
            return
        name, media_type = asset
        self.send(200, (ASSETS / name).read_bytes(), media_type)

    def do_POST(self):
        if not self.local_request():
            return
        route = {"/api/scenario": scenario, "/api/interpret": interpret_with_source}.get(self.path)
        if route is None:
            self.respond(404, {"error": "Unknown endpoint."})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if self.headers.get_content_type() != "application/json" or not 0 < size <= 96_000:
                raise ValueError
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError
        except (ValueError, UnicodeError, TimeoutError):
            self.respond(400, {"error": "Invalid request."})
            return
        try:
            data = route(payload)
        except (KeyError, IndexError, TypeError):
            self.respond(502, {"error": "Could not complete the request. Try again."})
        except ValueError as error:
            self.respond(400, {"error": str(error)})
        else:
            self.respond(200, data)

    def log_request(self, code="-", size="-"):
        # Keep all user input, including key material, out of server logs.
        pass


def serve(port):
    with ThreadingHTTPServer(("127.0.0.1", port), Dashboard) as server:
        print(f"Preheat is running at http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0
