"""Optional language layer: sentence -> one proposed setting -> confirm -> same calculation.

The model only proposes `ceiling_c` (or asks / declines). The program echoes the proposal,
waits for an explicit "yes", calls `compare` in exactly one place, and renders every
number itself from the tool output.
"""
import json
import math
import os
import re
import sys
import urllib.request

from . import sweep

FALLBACK = ("Please tell me the highest indoor temperature you would accept, "
            "between 21.5 and 24 °C.")
CANCELLED = "Cancelled. Nothing was calculated."
LIVE_HELP = ('Live mode needs PREHEAT_LLM_API_KEY and PREHEAT_LLM_MODEL. '
             'Run "python -m preheat ask --offline" to replay the recorded session.')
NUMBER_GUARD = re.compile(r"€|%|kWh|EUR|cost|sav", re.I)

TOOL = {
    "name": "compare",
    "description": ("Compare price-blind heating with cost-minimising pre-heating, for the "
                    "current and the better-insulated house, at one maximum indoor "
                    "temperature that applies all day."),
    "input_schema": {
        "type": "object",
        "properties": {"ceiling_c": {
            "type": "number", "minimum": 21.5, "maximum": 24.0,
            "description": "Maximum indoor temperature allowed all day, in °C."}},
        "required": ["ceiling_c"], "additionalProperties": False},
}

SYSTEM_PROMPT = (
    "You translate one request about the maximum indoor temperature into a call to "
    "compare(ceiling_c). The valid range is 21.5 to 24 degrees C and the setting applies "
    "all day. If the value is unclear (for example 'a bit warmer'), ask one short "
    "clarifying question and do not call the tool. If the request is for anything else "
    "(night setbacks, a different floor, turning the heat pump off, prices, "
    "recommendations), say briefly that only the maximum temperature can be changed, and "
    "do not call the tool. Never state energy, cost or percentage figures. Never "
    "recommend or rank options.")


def normalise(out):
    """Reduce any model output to a tool_call(compare, ceiling_c) or a guarded text."""
    fb = {"type": "text", "text": FALLBACK}
    if not isinstance(out, dict):
        return fb
    if out.get("type") == "tool_call":
        args = out.get("arguments")
        if out.get("name") != "compare" or not isinstance(args, dict) \
                or set(args) != {"ceiling_c"}:
            return fb
        v = args["ceiling_c"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            return fb
        return {"type": "tool_call", "name": "compare", "arguments": {"ceiling_c": v}}
    if out.get("type") == "text" and isinstance(out.get("text"), str):
        t = out["text"].strip()
        return fb if (not t or NUMBER_GUARD.search(t)) else {"type": "text", "text": t}
    return fb


def echo(v):
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
        if unit == "cases":
            s = str(int(node))
        elif unit == "%":
            s = f"{node:.1f}"
        else:
            s = f"{node:.2f}"
            if s == "-0.00":
                s = "0.00"
        prov.append((s, f"envelopes.{env}.{path}", unit))
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
        lines.append(f"  {name}: avoids {fmt(env, 'avoided_kwh', 'kWh')} of "
                     f"{fmt(env, 'baseline_evening_kwh', 'kWh')} evening heat-pump "
                     f"electricity ({fmt(env, 'avoided_pct', '%')}).")
        lines.append(f"    Day heating cost {fmt(env, 'optimised_cost_eur', '€')} instead of "
                     f"{fmt(env, 'baseline_cost_eur', '€')}: "
                     f"{fmt(env, 'saving_eur', '€')} saved that day.")
    parts = []
    for env in names:
        e = result["envelopes"][env]
        if e["status"] != "ok" or not e["case_range"].get("n_cases_ok"):
            continue
        r = f"case_range."
        parts.append(
            f"avoided {fmt(env, r + 'avoided_pct_min', '%')} to "
            f"{fmt(env, r + 'avoided_pct_max', '%')}, saved "
            f"{fmt(env, r + 'saving_eur_min', '€')} to {fmt(env, r + 'saving_eur_max', '€')} "
            f"({env}, {fmt(env, r + 'n_cases_ok', 'cases')} cases)")
    if parts:
        lines.append("  Across the what-if cases: " + "; ".join(parts) + ".")
    lines.append("These are two different measures and can rank the houses differently. "
                 "The tool does not recommend a setting.")
    return "\n".join(lines), prov


class Session:
    """Confirm-then-call state machine. `compare_fn` is called only in the yes branch."""

    def __init__(self, model_fn, compare_fn=None):
        self.model_fn = model_fn
        self.compare_fn = compare_fn or sweep.compare
        self.pending = None
        self.history = []
        self.log = []

    def _say(self, text):
        self.log.append({"role": "program", "text": text})
        return text

    def send(self, text):
        """Handle one user message; return the printed lines."""
        self.log.append({"role": "user", "text": text})
        if self.pending is not None:
            v, answer = self.pending, text.strip().lower()
            if answer in ("y", "yes"):
                self.pending = None
                result = self.compare_fn(v)
                self.log.append({"role": "tool", "name": "compare",
                                 "arguments": {"ceiling_c": v}, "result": result})
                self.history.append({"role": "assistant", "content": "(calculation shown)"})
                return [self._say(render(result)[0])]
            if answer in ("n", "no", "cancel"):
                self.pending = None
                self.history.append({"role": "assistant", "content": CANCELLED})
                return [self._say(CANCELLED)]
            self.pending = None          # anything else: a new request
        self.history.append({"role": "user", "content": text})
        out = normalise(self.model_fn(list(self.history)))
        self.log.append({"role": "model", "output": out})
        if out["type"] == "text":
            self.history.append({"role": "assistant", "content": out["text"]})
            return [self._say(out["text"])]
        v = round(float(out["arguments"]["ceiling_c"]), 1)
        if not sweep.LO <= v <= sweep.HI:
            return [self._say(FALLBACK)]
        self.pending = v
        self.history.append({"role": "assistant", "content": echo(v)})
        return [self._say(echo(v))]


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

        def model_fn(_messages, models=models):
            return next(models, {"type": "text", "text": "(trace exhausted)"})

        sess = Session(model_fn, spy)
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


def call_model(messages, tools=None):
    """The single provider adapter: an OpenAI-style chat-completions tool-calling endpoint."""
    key, model = os.environ.get("PREHEAT_LLM_API_KEY"), os.environ.get("PREHEAT_LLM_MODEL")
    tools = tools or [TOOL]
    body = {"model": model, "temperature": 0,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            "tools": [{"type": "function", "function": {
                "name": t["name"], "description": t["description"],
                "parameters": t["input_schema"]}} for t in tools]}
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        msg = json.load(resp)["choices"][0]["message"]
    try:
        if msg.get("tool_calls"):
            fn = msg["tool_calls"][0]["function"]
            return {"type": "tool_call", "name": fn["name"],
                    "arguments": json.loads(fn["arguments"])}
        return {"type": "text", "text": msg.get("content") or ""}
    except (KeyError, ValueError, TypeError):
        return {"type": "text", "text": FALLBACK}


def run_eval(path):
    items = json.load(open(path, encoding="utf-8"))
    counts = {}
    failures, unconfirmed = [], 0
    for it in items:
        calls = []
        sess = Session(call_model, lambda v: calls.append(v) or sweep.compare(v))
        sess.send(it["text"])
        out = next((t["output"] for t in reversed(sess.log) if t["role"] == "model"), None)
        exp = it["expected"]
        if exp["action"] == "cancel":
            sess.send("no")
            ok = not calls
        elif exp["action"] == "propose":
            ok = out["type"] == "tool_call" and out["arguments"]["ceiling_c"] == exp["ceiling_c"]
        else:
            ok = out["type"] == "text"
        if exp["action"] != "cancel" and calls:
            unconfirmed += 1
        c = counts.setdefault(exp["action"], {"n": 0, "correct": 0})
        c["n"] += 1
        c["correct"] += ok
        if not ok:
            failures.append({"id": it["id"], "got": out})
    summary = {"model": os.environ["PREHEAT_LLM_MODEL"],
               "date": __import__("datetime").date.today().isoformat(), "n": len(items),
               "correct": sum(c["correct"] for c in counts.values()), "by_label": counts,
               "failures": failures, "compare_calls_without_confirmation": unconfirmed}
    os.makedirs("evals", exist_ok=True)
    with open("evals/live_eval.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def _trace_path():
    return os.path.join(os.path.dirname(__file__), "traces", "demo.json")


def cli(args):
    if args.offline:
        with open(args.trace or _trace_path(), encoding="utf-8") as f:
            trace = json.load(f)
        ok, msg = replay(trace)
        print(msg)
        return 0 if ok else 1
    if not (os.environ.get("PREHEAT_LLM_API_KEY") and os.environ.get("PREHEAT_LLM_MODEL")):
        print(LIVE_HELP)
        return 2
    if args.eval:
        return run_eval(args.eval)
    sess = Session(call_model)
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
        trace = {"format": "preheat-trace/1", "source": "recorded",
                 "model": os.environ["PREHEAT_LLM_MODEL"],
                 "recorded_on": __import__("datetime").date.today().isoformat(),
                 "results_format": sweep.FORMAT,
                 "sessions": [{"name": "recorded session", "turns": sess.log}]}
        with open(args.record, "w", encoding="utf-8") as f:
            json.dump(trace, f, indent=2, ensure_ascii=False)
            f.write("\n")
    return 0
