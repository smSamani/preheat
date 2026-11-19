"""Optional language layer: sentence -> one proposed setting -> confirm -> same calculation.

The rules in `ceiling.py` propose a maximum, and only from a value typed in the message. The
optional Gemini router may only pick a read-only answer. The program echoes the proposal, waits
for "yes", calls `compare` in exactly one place, and prints fixed templates filled from solver
output. Nothing the model writes is ever printed.
"""
import json
import os
import sys

from . import assistant, fixture, gemini, intent, sweep

CANCELLED = "Cancelled. Nothing was calculated."
CANCELLED_FA = "لغو شد. چیزی محاسبه نشد."
LIVE_HELP = ('Live mode needs PREHEAT_GEMINI_KEY (and optionally PREHEAT_GEMINI_MODEL). '
             'Run "python -m preheat ask --offline" to replay the recorded sessions.')
YES = ("y", "yes", "yeah", "yep", "بله", "آره", "اره")
NO = ("n", "no", "cancel", "نه", "خیر", "لغو")


def echo(v, persian=False):
    if persian:
        return f"سقف {v:.1f} درجه برای کل روز — درسته؟ (بله/نه)"
    return f"Maximum {v:.1f} °C, all day — correct? (yes/no)"


def render(result):
    """Return (text, provenance); provenance = [(shown, field_path, unit)]."""
    if result["status"] != "ok":
        return f"{result['status']}: {result.get('reason')}", []
    prov = []

    def fmt(env, path, unit):
        node = result["envelopes"][env]
        for part in path.split("."):
            node = node[part]
        if node is None:
            s = "n/a"
        elif unit == "cases":
            s = str(int(node))
        elif unit == "%":
            s = f"{node:.1f}"
        else:
            s = f"{node:.2f}"
            if s == "-0.00":
                s = "0.00"
        prov.append((s, f"envelopes.{env}.{path}", unit))
        if node is None:
            return s
        return {"%": f"{s}%", "kWh": f"{s} kWh", "€": f"€{s}", "cases": f"{s} what-if"}[unit]

    cc = f"{result['ceiling_c']:.1f}"
    prov.append((cc, "ceiling_c", "°C"))
    lines = [f"Maximum indoor temperature {cc} °C, one synthetic winter day (nominal case):"]
    names = {"current": "Current house", "insulated": "Better-insulated house"}
    for env, name in names.items():
        e = result["envelopes"][env]
        if e["status"] != "ok":
            lines.append(f"  {name}: {e['status']}: {e.get('reason')}")
            continue
        lines.append(f"  {name}: avoids {fmt(env, 'avoided_kwh', 'kWh')} of the one-hour rule's "
                     f"{fmt(env, 'baseline_evening_kwh', 'kWh')} evening heat-pump "
                     f"electricity ({fmt(env, 'avoided_pct', '%')}).")
        lines.append(f"    Day heating cost {fmt(env, 'optimised_cost_eur', '€')} instead of "
                     f"{fmt(env, 'baseline_cost_eur', '€')} with the one-hour rule: "
                     f"{fmt(env, 'saving_eur', '€')} saved that day.")
    parts = []
    for env in names:
        e = result["envelopes"][env]
        if e["status"] != "ok" or not e["case_range"].get("n_cases_ok"):
            continue
        r = "case_range."
        rng = e["case_range"]
        pct = (f"avoided {fmt(env, r + 'avoided_pct_min', '%')} to "
               f"{fmt(env, r + 'avoided_pct_max', '%')}, "
               if "avoided_pct_min" in rng else "")
        parts.append(
            f"{pct}saved "
            f"{fmt(env, r + 'saving_eur_min', '€')} to {fmt(env, r + 'saving_eur_max', '€')} "
            f"({env}, {fmt(env, r + 'n_cases_ok', 'cases')} cases)")
    if parts:
        lines.append("  Across the what-if cases: " + "; ".join(parts) + ".")
    lines.append("Both comparisons are against the one-hour rule. The two measures can rank "
                 "the houses differently. The tool does not recommend a setting.")
    return "\n".join(lines), prov


class Session:
    """Confirm-then-call state machine. `compare_fn` is called only in the yes branch.

    `ask` is None (rules only) or a callable(message) -> ModelChoice | Failure. Only the latest
    message is passed on. The pending proposal is the pair (value, case)."""

    CASE = "nominal"

    def __init__(self, ask=None, compare_fn=None, always_ask=False):
        self.ask = ask
        self.always_ask = always_ask      # evaluation only: log the model's choice for every message
        self.compare_fn = compare_fn or sweep.compare
        self.pending = None
        self.log = []
        self.last_decision = None         # the intent.Decision of the latest message, if any
        self.last_action = None           # ("confirm", value) or ("cancel", None) for yes / no

    def _say(self, text):
        self.log.append({"role": "program", "text": text})
        return text

    def _reply(self, decision, persian):
        item = decision.intent
        if isinstance(item, intent.Compare):
            results = _results()
        else:
            results = {"ceiling": fixture.REFERENCE_CEILING, "case": self.CASE, "envelopes": {}}
        return assistant.render(item, results, persian)["text"]

    def send(self, text):
        """Handle one user message; return the printed lines."""
        self.log.append({"role": "user", "text": text})
        self.last_decision = self.last_action = None
        persian = bool(assistant.PERSIAN.search(text))
        if self.pending is not None:
            (v, case), answer = self.pending, text.strip().lower()
            self.pending = None              # any message ends the pending proposal
            if answer in YES and case == self.CASE:
                self.last_action = ("confirm", v)
                result = self.compare_fn(v)
                self.log.append({"role": "tool", "name": "compare",
                                 "arguments": {"ceiling_c": v}, "result": result})
                return [self._say(render(result)[0])]
            if answer in NO:
                self.last_action = ("cancel", None)
                return [self._say(CANCELLED_FA if persian else CANCELLED)]
        decision = self.last_decision = intent.decide(text, self.ask, always_ask=self.always_ask)
        if decision.model is not None:
            model = decision.model
            self.log.append({"role": "model", "output": (
                {"failure": model.code} if isinstance(model, intent.Failure) else model.model_dump())})
        item = decision.intent
        if isinstance(item, intent.ProposeCeiling):
            self.pending = (item.value_c, self.CASE)
            return [self._say(echo(item.value_c, persian))]
        return [self._say(self._reply(decision, persian))]


def _results():
    from . import web
    return web.scenario({"ceiling": fixture.REFERENCE_CEILING, "case": Session.CASE})


def _close(a, b):
    if isinstance(a, float) or isinstance(b, float):
        return isinstance(a, (int, float)) and isinstance(b, (int, float)) \
            and abs(a - b) <= 1e-9
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_close(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_close(x, y) for x, y in zip(a, b))
    return a == b


def replay(trace, compare_fn=None, out=print):
    """Re-run a trace through the state machine. Returns (ok, message)."""
    calls = []
    base = compare_fn or sweep.compare

    def spy(v):
        calls.append(v)
        return base(v)

    for s in trace["sessions"]:
        models = iter([t["output"] for t in s["turns"] if t["role"] == "model"])

        def ask_fn(_message, models=models):
            out = next(models, {"failure": "unavailable"})
            if "failure" in out:
                return intent.Failure(out["failure"])
            return intent.MODEL_CHOICE.validate_python(out)

        sess = Session(ask_fn if any(t["role"] == "model" for t in s["turns"]) else None, spy)
        out(f"--- {s['name']}")
        for t in s["turns"]:
            if t["role"] == "user":
                out(f"> {t['text']}")
                for line in sess.send(t["text"]):
                    out(line)
        expected = [t for t in s["turns"] if t["role"] in ("program", "tool", "model")]
        got = [t for t in sess.log if t["role"] in ("program", "tool", "model")]
        if len(expected) != len(got):
            return False, f"{s['name']}: expected {len(expected)} events, got {len(got)}"
        for e, g in zip(expected, got):
            if e["role"] != g["role"]:
                return False, f"{s['name']}: expected {e['role']}, got {g['role']}"
            if e["role"] == "program" and e["text"] != g["text"]:
                return False, f"{s['name']}: program text differs:\n{e['text']}\n{g['text']}"
            if e["role"] == "tool" and not (_close(e["arguments"], g["arguments"])
                                            and _close(e["result"], g["result"])):
                return False, f"{s['name']}: tool result differs"
    n_tool = sum(1 for s in trace["sessions"] for t in s["turns"] if t["role"] == "tool")
    if len(calls) != n_tool:
        return False, f"compare called {len(calls)} times, trace has {n_tool} tool turns"
    return True, f"Replay identical ({len(trace['sessions'])} sessions)."


def live_settings():
    """The Gemini key and model from the environment, or None when live mode is not configured."""
    key = os.environ.get("PREHEAT_GEMINI_KEY", "").strip()
    if not key:
        return None
    return {"key": key, "model": os.environ.get("PREHEAT_GEMINI_MODEL", "").strip()
            or gemini.DEFAULT_MODEL}


def _trace_paths():
    folder = os.path.join(os.path.dirname(__file__), "traces")
    return [os.path.join(folder, name) for name in ("demo.json", "revision.json")]


def cli(args):
    if args.offline:
        status = 0
        for path in ([args.trace] if args.trace else _trace_paths()):
            with open(path, encoding="utf-8") as f:
                trace = json.load(f)
            ok, msg = replay(trace)
            print(msg)
            status = status or (0 if ok else 1)
        return status
    live = live_settings()
    if live is None:
        print(LIVE_HELP)
        return 2
    active = gemini.settings(fixture.REFERENCE_CEILING, Session.CASE)
    sess = Session(lambda message: gemini.ask(message, active, live["key"], live["model"]))
    print("Tell me the highest indoor temperature you would accept (quit to end).")
    while True:
        try:
            text = input("> ")
        except EOFError:
            break
        if text.strip().lower() in ("quit", "exit"):
            break
        for line in sess.send(text):
            print(line)
    if args.record:
        trace = {"format": "preheat-trace/1", "source": "recorded", "model": live["model"],
                 "recorded_on": __import__("datetime").date.today().isoformat(),
                 "results_format": sweep.FORMAT,
                 "sessions": [{"name": "recorded session", "turns": sess.log}]}
        with open(args.record, "w", encoding="utf-8") as f:
            json.dump(trace, f, indent=2, ensure_ascii=False)
            f.write("\n")
    return 0
