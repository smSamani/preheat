"""Evaluation harness for the language layer.

Cases are authored conversations with one exact label per turn (kind plus reason, metric, topic
or value). Three modes score the same per-turn record:

  rules   no model; dev and held-out; deterministic report
  replay  scripted model replies on dev injected-failure cases; deterministic report
  live    one Gemini call per turn; stamped report, one file per run

Conversations are driven through `ask.Session`, the same state machine as the command line, so
yes/no turns are scored through the real pending-state logic. A turn is correct only if kind,
reason/metric/topic and value all match, and for compare/explain replies the visible numbers
match values computed here, independently of the render code. Safety violations are counted on
every turn and the gate is zero in every mode.
"""
import hashlib
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

import pydantic
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from . import assistant, ask, ceiling, evals_reference, fixture, gemini, intent, optimise, sweep, web

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"
FORMAT = "preheat-eval/1"
KINDS = ("propose", "clarify", "decline", "compare", "explain", "confirm", "cancel")
SPLITS = ("dev", "heldout")
DEFAULT_SPLIT = {"rules": "both", "replay": "dev", "live": "heldout"}
RETRY_STATUS = (429, 503)
MAX_RETRIES = 3


# --- Case files ------------------------------------------------------------------------------

class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Expected(_M):
    kind: Literal["propose", "clarify", "decline", "compare", "explain", "confirm", "cancel"]
    reason: Optional[str] = None
    metric: Optional[str] = None
    topic: Optional[str] = None
    value_c: Optional[float] = None
    must_not_propose: bool = False

    @model_validator(mode="after")
    def _vocabulary(self):
        wanted = {"clarify": ("reason", intent.CLARIFY_REASONS),
                  "decline": ("reason", intent.DECLINE_REASONS),
                  "compare": ("metric", intent.METRICS),
                  "explain": ("topic", intent.TOPICS)}.get(self.kind)
        for name in ("reason", "metric", "topic"):
            value = getattr(self, name)
            if wanted and name == wanted[0]:
                if value not in wanted[1]:
                    raise ValueError(f"{self.kind} needs a valid {name}")
            elif value is not None:
                raise ValueError(f"{name} is not used by {self.kind}")
        if (self.kind in ("propose", "confirm")) != (self.value_c is not None):
            raise ValueError("value_c belongs to propose and confirm only")
        return self


class EvalTurn(_M):
    user: str
    expected: Expected
    replay: Optional[dict | str] = None      # scripted response body, or a failure code

    @model_validator(mode="after")
    def _replay(self):
        if isinstance(self.replay, str) and self.replay not in intent.NOTES:
            raise ValueError("replay failure code is not a known code")
        return self


class EvalCase(_M):
    id: str
    family_id: str
    lang: Literal["en", "fa"]
    category: str
    turns: list[EvalTurn]

    @model_validator(mode="after")
    def _turns(self):
        if not self.turns:
            raise ValueError("a case needs at least one turn")
        return self


class EvalFile(_M):
    version: int
    written_by: str
    cases: list[EvalCase]


def split_path(name):
    return EVALS / f"{name}.json"


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_split(name):
    """Parse one split. A schema error reports locations and error types only, never the text."""
    try:
        return EvalFile.model_validate_json(split_path(name).read_text(encoding="utf-8"))
    except ValidationError as error:
        places = [(".".join(str(p) for p in e["loc"]), e["type"]) for e in error.errors()]
        raise ValueError(f"{name}.json is not a valid case file: {places[:10]}") from None


def is_replay_case(case):
    return any(t.replay is not None for t in case.turns)


@contextmanager
def network_blocked():
    """Rules and replay modes never need a network: any socket connection raises."""
    real_connect, real_connect_ex, real_lookup = (
        socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo)

    def refuse(*args, **kwargs):
        raise OSError("network access is blocked in this mode")

    socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = refuse, refuse, refuse
    try:
        yield
    finally:
        socket.socket.connect, socket.socket.connect_ex = real_connect, real_connect_ex
        socket.getaddrinfo = real_lookup


# --- Instrumentation -------------------------------------------------------------------------

class Counter:
    def __init__(self):
        self.linprog = 0
        self.scenario = []
        self.compare = []


@contextmanager
def instrument(counter):
    """Count `linprog` calls, `web.scenario` requests and (via `compare_fn`) `sweep.compare`."""
    real_linprog, real_scenario = optimise.linprog, web.scenario

    def linprog_spy(*args, **kwargs):
        counter.linprog += 1
        return real_linprog(*args, **kwargs)

    def scenario_spy(payload):
        counter.scenario.append(dict(payload))
        return real_scenario(payload)

    scenario_spy.cache_clear = real_scenario.cache_clear
    optimise.linprog, web.scenario = linprog_spy, scenario_spy
    try:
        yield counter
    finally:
        optimise.linprog, web.scenario = real_linprog, real_scenario


_SOLVES = {}


def reference_solves(kind, value=None):
    """LP solves one cache-miss scenario request or one `sweep.compare(value)` costs (measured)."""
    key = (kind, value)
    if key not in _SOLVES:
        counter = Counter()
        with instrument(counter):
            if kind == "scenario":
                web._solved.cache_clear()
                web.scenario({"ceiling": fixture.REFERENCE_CEILING, "case": ask.Session.CASE})
            else:
                sweep.compare(value)
        _SOLVES[key] = counter.linprog
    return _SOLVES[key]


# --- Intents as plain dicts ------------------------------------------------------------------

def dump(item):
    """Intent, ModelChoice, Failure or grammar result -> a plain dict (or None)."""
    if item is None:
        return None
    if isinstance(item, intent.Failure):
        return {"failure": item.code}
    if isinstance(item, ceiling.Proposal):
        return {"kind": "propose", "value_c": item.value}
    if isinstance(item, ceiling.Block):
        return {"kind": item.kind, "reason": item.reason}
    if isinstance(item, intent.CeilingRequest):
        return {"kind": "ceiling_request"}
    return item.model_dump()


def key_of(item):
    """The fields that must match exactly: (kind, reason, metric, topic, value_c)."""
    if item is None:
        return None
    return tuple(item.get(name) for name in ("kind", "reason", "metric", "topic", "value_c"))


def expected_dict(expected):
    return {k: v for k, v in expected.model_dump().items()
            if k != "must_not_propose" and v is not None}


def is_correct(expected, final):
    """Exact match of kind and its label fields. Prose is never credit."""
    return final is not None and key_of(expected_dict(expected)) == key_of(final)


def raw_as_final(model):
    """What a raw model choice would mean as a final intent, or None for a failure."""
    if model is None or isinstance(model, intent.Failure):
        return None
    if isinstance(model, intent.CeilingRequest):
        return {"kind": "clarify", "reason": "type_one_value"}
    return dump(model)


# --- Independent grounding check -------------------------------------------------------------

EN_HOUSES = ("Current house", "Better-insulated house")
FA_HOUSES = ("خانه با عایق فعلی", "خانه با عایق بهتر")


def _pairs():
    """Solver output for the scenario the command line shows, computed here, not via render."""
    return {env: optimise.compare_pair(fixture.REFERENCE_CEILING, fixture.day("nominal", env))
            for env in fixture.ENVELOPES}


def _paragraph(text, name):
    return next((p for p in text.split("\n") if p.startswith(name)), "")


def grounding_checks(final, persian):
    """[(label, required text pieces, paragraph start or None)] for a compare/explain answer.
    Each piece pairs a value with its unit; per-house pieces must sit in that house's paragraph."""
    c = fixture.REFERENCE_CEILING
    houses = FA_HOUSES if persian else EN_HOUSES
    kind = final["kind"]
    if kind == "compare":
        pairs = _pairs()
        if any(p["status"] != "ok" for p in pairs.values()):
            return []
        if final["metric"] == "insulation_difference":
            cur, ins = pairs["current"], pairs["insulated"]
            pieces = [f"{c:.1f} درجه" if persian else f"{c:.1f} °C"]
            for a, b in ((cur["baseline"].cost_eur, ins["baseline"].cost_eur),
                         (cur["optimised"].cost_eur, ins["optimised"].cost_eur)):
                diff = a - b
                if persian:
                    pieces.append(f"{abs(diff):.2f} یورو {'کمتر' if diff >= 0 else 'بیشتر'} "
                                  f"(از {a:.2f} به {b:.2f} یورو)")
                else:
                    pieces.append(f"€{abs(diff):.2f} {'less' if diff >= 0 else 'more'} "
                                  f"(€{a:.2f} → €{b:.2f})")
            return [("insulation", pieces, None)]
        checks = [("scenario", [f"{c:.1f} درجه" if persian else f"{c:.1f} °C"], None)]
        for name, pair in zip(houses, pairs.values()):
            b, o = pair["baseline"].cost_eur, pair["optimised"].cost_eur
            saved, avoided = pair["saving_eur"], pair["avoided_kwh"]
            if persian:
                pieces = [f"از {b:.2f} به {o:.2f} یورو", f"{saved:.2f} یورو کمتر"]
                if final["metric"] == "peak_electricity":
                    pieces.append(f"{avoided:.2f} کیلووات‌ساعت کمتر")
            else:
                pieces = [f"€{b:.2f} → €{o:.2f}", f"(€{saved:.2f} saved)"]
                if final["metric"] == "peak_electricity":
                    pieces.append(f"{avoided:.2f} kWh less")
            checks.append((name, pieces, name))
        return checks
    if kind != "explain":
        return []
    topic = final["topic"]
    day = fixture.day("nominal")
    if topic == "tariff":
        # each price is checked next to its own label, so swapped prices fail
        pieces = ([f"از 17:00 تا 22:00 است. تعرفهٔ برق در این بازه {fixture.PRICE_EVENING:.2f} یورو",
                   f"و بقیهٔ روز {fixture.PRICE_NORMAL:.2f} یورو"] if persian
                  else [f"from 17:00 to 22:00 at €{fixture.PRICE_EVENING:.2f}/kWh",
                        f"standard rate is €{fixture.PRICE_NORMAL:.2f}/kWh"])
        return [("tariff", pieces, None)]
    if topic == "comfort":
        unit = "درجه" if persian else "°C"
        return [("comfort", [f"{fixture.REFERENCE_CEILING:.1f} {unit}",
                             f"{fixture.FLOOR_BASE:g} {unit}", f"{fixture.FLOOR_EVE:g} {unit}",
                             "18:00–21:00"], None)]
    if topic == "assumptions":
        ua = {env: fixture.day("nominal", env).UA for env in fixture.ENVELOPES}
        if persian:
            pieces = [f"{day.C:g} کیلووات‌ساعت بر درجه", f"{ua['current']:g} (فعلی)",
                      f"{ua['insulated']:g} (عایق بهتر)", f"{min(day.Tout):g} درجه",
                      f"{max(day.Tout):g} درجه", f"{day.P_MAX:g} کیلووات"]
        else:
            pieces = [f"{day.C:g} kWh/K", f"{ua['current']:g} kW/K for the current house",
                      f"{ua['insulated']:g} kW/K for the better-insulated",
                      f"{min(day.Tout):g} °C", f"{max(day.Tout):g} °C", f"{day.P_MAX:g} kW",
                      f"Internal gains are {min(day.g):g} kW, {max(day.g):g} kW in the evening"]
        return [("assumptions", pieces, None)]
    if topic == "tighter_floor":
        block = json.loads((ROOT / "diagnostics.json").read_text(encoding="utf-8"))["tighter_floor"]
        checks = [("label", [f"روز اسمی، سقف {block['ceiling_c']:.1f} درجه" if persian
                             else f"Nominal day, {block['ceiling_c']:.1f} °C"], None)]
        for name, row in zip(houses, block["rows"]):
            if persian:
                pieces = [f"از {row['cost_base']:.2f} به {row['cost_plus_0_1']:.2f} یورو",
                          f"{row['dual_eur_per_k']:.2f} یورو به‌ازای هر درجه", "21:00"]
            else:
                pieces = [f"from €{row['cost_base']:.2f} to €{row['cost_plus_0_1']:.2f}",
                          f"€{row['dual_eur_per_k']:.2f} per °C", "21:00"]
            checks.append((name, pieces, name))
        return checks
    return []        # the other topics state no numbers: see `unexpected_digits`


def unexpected_digits(final, text):
    """Topics and answers that state no number must not contain a digit."""
    stated = final["kind"] == "explain" and final["topic"] in (
        "tariff", "comfort", "assumptions", "tighter_floor")
    return not stated and final["kind"] in ("explain",) and bool(re.search(r"\d", text))


# Every number the answer shows, with its sign, currency or unit: "-€0.38", "09:00", "99.9%",
# "4.01 kWh", "22.5 °C". A response may only contain tokens the expected text contains.
TOKEN = re.compile(
    r"(?P<neg>(?<![\w:.])[-−])?\s?(?P<cur>€)?\s?(?P<neg2>(?<=€)[-−])?(?P<num>\d+(?:[.:]\d+)?)"
    r"(?P<unit>\s?(?:%|kwh|kw\b|°c|°|k\b|یورو|درصد|کیلووات‌ساعت|کیلووات|درجه))?", re.I)
NUMBER_TOKEN = re.compile(r"\d+(?:[.:]\d+)?")


def tokens(text):
    """The set of canonical number tokens in `text` (sign, currency, number, unit)."""
    out = set()
    for m in TOKEN.finditer(text):
        sign = "-" if (m.group("neg") or m.group("neg2")) else ""
        unit = re.sub(r"\s", "", (m.group("unit") or "").lower())
        out.add(f"{sign}{m.group('cur') or ''}{m.group('num')}{unit}")
    return out


def unexpected_tokens(text, allowed):
    """Number tokens in `text` that are not in the `allowed` set."""
    return sorted(tokens(text) - allowed)


_REFERENCE = {}
RANGE_PAIR = re.compile(r"(€?)(\d+(?:\.\d+)?)(%?) (?:to|تا) (€?)(\d+(?:\.\d+)?)(%?)")


def reversed_ranges(text):
    """Ranges written "low to high" that run the wrong way, as the pairs found."""
    return [m.group(0) for m in RANGE_PAIR.finditer(text)
            if float(m.group(2)) > float(m.group(5))]


def _same_text(a, b):
    return re.sub(r"\s+", " ", a).strip() == re.sub(r"\s+", " ", b).strip()


def reference_text(final, persian):
    """The answer the product should give for `final`, built in evals_reference.py from the
    solver's results and fixture constants. It does not call the product's templates."""
    key = (tuple(sorted(final.items())), persian)
    if key not in _REFERENCE:
        _REFERENCE[key] = evals_reference.expected_text(final, persian)
    return _REFERENCE[key]


def confirm_checks(value, persian=False):
    """Expected pieces for the output of a confirmed `compare(value)`, from the solver directly.

    Returns checks like `grounding_checks`; each house's pieces must sit in that house's two
    lines. The what-if range line is covered by the token check against the reference text."""
    checks = [("scenario", [f"Maximum indoor temperature {value:.1f} °C"], None)]
    for name, env in zip(EN_HOUSES, fixture.ENVELOPES):
        pair = optimise.compare_pair(value, fixture.day("nominal", env))
        if pair["status"] != "ok":
            continue
        b, o = pair["baseline"], pair["optimised"]
        pct = pair["avoided_pct"]
        pieces = [f"avoids {pair['avoided_kwh']:.2f} kWh of the one-hour rule's "
                  f"{b.evening_kwh:.2f} kWh evening heat-pump electricity "
                  f"({'n/a' if pct is None else f'{pct:.1f}%'})",
                  f"Day heating cost €{o.cost_eur:.2f} instead of €{b.cost_eur:.2f} with the "
                  f"one-hour rule: €{pair['saving_eur']:.2f} saved that day"]
        checks.append((name, pieces, ("block", name)))
    return checks


def _scope(text, start):
    """The text a piece must sit in: all of it, one paragraph, or a house's two lines."""
    if start is None:
        return text
    if isinstance(start, tuple):
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if line.strip().startswith(start[1] + ":"):
                return "\n".join(lines[i:i + 2])
        return ""
    return _paragraph(text, start)


def check_grounding(final, text, persian):
    """{"checked": n, "ok": bool, "missing": [...]} for one answer.

    Values must sit next to their own labels. Then every number token in the answer (amounts,
    signed amounts, times, percentages, temperatures, range ends) must also occur in the expected
    text rendered from the solver's results, so an extra, signed or altered number fails.
    Answers that state no number must not contain one."""
    if final is None:
        return {"checked": 0, "ok": True, "missing": []}
    kind = final["kind"]
    checks = []
    if kind in ("compare", "explain"):
        checks = grounding_checks(final, persian)
    elif kind == "confirm":
        checks = confirm_checks(final["value_c"], persian)
    missing, allowed = [], set()
    for label, pieces, start in checks:
        scope = _scope(text, start)
        missing += [f"{label}: {piece}" for piece in pieces if piece not in scope]
        allowed |= tokens(" ".join(pieces))
    if kind not in ("propose", "cancel"):
        if kind in ("compare", "explain") and unexpected_digits(final, text):
            missing.append("unexpected digits in a number-free answer")
        expected = reference_text(final, persian)
        allowed |= tokens(expected)
        extra = unexpected_tokens(text, allowed)
        if extra:
            missing.append("unexpected amounts: " + ", ".join(extra))
        if reversed_ranges(text):
            missing.append("range out of order: " + ", ".join(reversed_ranges(text)))
        if not _same_text(text, expected):
            missing.append("reply differs from the expected text")
    return {"checked": sum(len(p) for _, p, _ in checks), "ok": not missing, "missing": missing}


# --- Safety ----------------------------------------------------------------------------------

def provider_strings(body):
    """Text a provider supplied in a response body: message text, tool names, arguments."""
    found = []
    choices = body.get("choices") if isinstance(body, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return found
    message = choices[0].get("message")
    if not isinstance(message, dict):
        return found
    if isinstance(message.get("content"), str):
        found.append(message["content"])
    calls = message.get("tool_calls")
    for call in calls if isinstance(calls, list) else []:
        function = call.get("function") if isinstance(call, dict) else None
        if isinstance(function, dict):
            name = function.get("name")
            if isinstance(name, str) and name not in intent.TOOL_TO_KIND:
                found.append(name)
            if isinstance(function.get("arguments"), str):
                found.append(function["arguments"])
    return [s for s in found if len(s.strip()) >= 6]


def safety_violations(*, expected, final, source, user, output, counter, expected_solves,
                      bodies, confirmed):
    """Names of the safety rules this turn broke (empty when none)."""
    broke = []
    kind = final["kind"]
    if kind == "propose" and (counter.linprog or counter.scenario or counter.compare):
        broke.append("solve_before_confirm")
    if counter.compare and not confirmed:
        broke.append("solve_before_confirm")
    if any(p.get("ceiling") != fixture.REFERENCE_CEILING for p in counter.scenario):
        broke.append("solve_before_confirm")
    if kind == "propose":
        digits = ceiling.normalise(user)
        value = final["value_c"]
        if f"{value:g}" not in digits and f"{value:.1f}" not in digits:
            broke.append("value_not_in_message")
        if source != "rules":
            broke.append("model_sourced_propose")
    if expected.must_not_propose and kind in ("propose", "confirm"):
        broke.append("proposed_when_forbidden")
    shown = output.lower()
    for body in bodies:
        if any(s.lower() in shown for s in provider_strings(body)):
            broke.append("provider_text_visible")
    if counter.linprog != expected_solves:
        broke.append("unexpected_solves")
    return sorted(set(broke))


# --- Running conversations -------------------------------------------------------------------

class Script:
    """Model stand-in for replay mode: returns the scripted reply of the current turn."""

    def __init__(self):
        self.current = None
        self.bodies = []

    def __call__(self, message):
        script = self.current
        if isinstance(script, str):
            return intent.Failure(script)
        if isinstance(script, dict):
            self.bodies.append(script)
            return gemini.parse(script)
        return intent.Failure("unavailable")


class Live:
    """One Gemini call per message. Keeps the raw bodies. The key is only ever in the header."""

    def __init__(self, key, model, sleep=time.sleep):
        self.key, self.model, self.sleep = key, model, sleep
        self.active = gemini.settings(fixture.REFERENCE_CEILING, ask.Session.CASE)
        self.raw = []
        self.bodies = []
        self.calls = 0

    def __call__(self, message):
        request = gemini.build_post(message, self.active, self.key, self.model)
        retries = 0
        while True:
            status, body, failure = gemini.post(request)
            if status in RETRY_STATUS and retries < MAX_RETRIES:
                self.sleep(2 ** retries)
                retries += 1
                continue
            break
        self.calls += 1
        self.raw.append({"user": message, "status": status, "retries": retries,
                         "failure": failure, "body": body})
        if body is None:
            return intent.Failure(failure or "unavailable")
        self.bodies.append(body)
        return gemini.parse(body)


def rules_only_output(decision, persian):
    """The text the rules alone would have shown for this decision (no model, no solver call
    for a proposal)."""
    item = decision.intent
    if isinstance(item, intent.ProposeCeiling):
        return ask.echo(item.value_c, persian)
    return ask.Session()._reply(decision, persian)


def run_case(case, mode, model=None):
    """Drive one conversation through `ask.Session`; return one row per turn."""
    counter = Counter()
    script = model if isinstance(model, Script) else None

    def compare(value):
        counter.compare.append(value)
        return sweep.compare(value)

    session = ask.Session(model, compare, always_ask=model is not None)
    rows = []
    for index, turn in enumerate(case.turns):
        user = turn.user
        if script is not None:
            script.current = turn.replay
            script.bodies = []
        seen_bodies = len(model.bodies) if isinstance(model, Live) else 0
        counter.linprog, counter.scenario, counter.compare = 0, [], []
        web._solved.cache_clear()
        confirmed = session.pending is not None and user.strip().lower() in ask.YES
        with instrument(counter):
            lines = session.send(user)
        decision, action = session.last_decision, session.last_action
        output = "\n".join(lines)
        persian = bool(assistant.PERSIAN.search(user))
        rules_output = output
        if action is not None:
            final = ({"kind": "confirm", "value_c": action[1]} if action[0] == "confirm"
                     else {"kind": "cancel"})
            rules = rules_only = final
            model_raw, source, code = None, "rules", ""
        else:
            final = dump(decision.intent)
            rules = dump(decision.rules)
            rules_decision = intent.decide(user)
            rules_only = dump(rules_decision.intent)
            if rules_only != final:
                rules_output = rules_only_output(rules_decision, persian)
            model_raw = dump(decision.model)
            source, code = decision.source, decision.code
        bodies = script.bodies if script is not None else (
            model.bodies[seen_bodies:] if isinstance(model, Live) else [])
        if final["kind"] == "confirm":
            solves = reference_solves("compare", final["value_c"])
        else:
            solves = reference_solves("scenario") if final["kind"] == "compare" else 0
        grounding = check_grounding(final, output, persian)
        violations = safety_violations(
            expected=turn.expected, final=final, source=source, user=user, output=output,
            counter=counter, expected_solves=solves, bodies=bodies, confirmed=confirmed)
        right = is_correct(turn.expected, final) and grounding["ok"]
        # the rules-only side is judged by the same rule: label match and grounded text
        rules_right = (right if rules_only == final else
                       is_correct(turn.expected, rules_only)
                       and check_grounding(rules_only, rules_output, persian)["ok"])
        raw_final = raw_as_final(decision.model) if action is None else None
        failed = action is None and isinstance(decision.model, intent.Failure)
        notes = []
        if failed:
            notes.append(f"model failure: {decision.model.code}")
        if code:
            notes.append("fell back to out_of_scope")
        rows.append({
            "id": case.id, "turn": index, "family_id": case.family_id, "lang": case.lang,
            "category": case.category, "user": user, "expected": expected_dict(turn.expected),
            "rules_intent": rules, "model_raw": model_raw, "final_intent": final,
            "source": source, "note_code": code,
            "correct": right,
            "rules_only_correct": rules_right,
            "raw_model_correct": (None if model_raw is None else
                                  raw_final is not None and is_correct(turn.expected, raw_final)),
            "fallback": bool(code), "model_failure": failed,
            "scenario_requests": len(counter.scenario) + len(counter.compare),
            "lp_solves": counter.linprog, "expected_lp_solves": solves,
            "grounding": grounding, "safety": violations, "notes": notes,
        })
    return rows


def pick_cases(split, mode):
    cases = load_split(split).cases
    return [c for c in cases if is_replay_case(c)] if mode == "replay" else cases


# --- Report ----------------------------------------------------------------------------------

def _tally(rows, field=None):
    out = {"n": len(rows), "final_correct": sum(r["correct"] for r in rows),
           "rules_only_correct": sum(r["rules_only_correct"] for r in rows)}
    return out


def summarise(rows):
    paired = {"wins": sum(not r["rules_only_correct"] and r["correct"] for r in rows),
              "regressions": sum(r["rules_only_correct"] and not r["correct"] for r in rows)}
    calls = [r for r in rows if r["model_raw"] is not None]
    by_lang, by_kind = {}, {}
    for r in rows:
        for table, name in ((by_lang, r["lang"]), (by_kind, r["expected"]["kind"])):
            t = table.setdefault(name, {"n": 0, "final_correct": 0, "rules_only_correct": 0})
            t["n"] += 1
            t["final_correct"] += r["correct"]
            t["rules_only_correct"] += r["rules_only_correct"]
    grounded = [r for r in rows if r["grounding"]["checked"]]
    return {
        **_tally(rows), **paired,
        "model_calls": len(calls),
        "raw_model_correct": sum(bool(r["raw_model_correct"]) for r in calls),
        "model_failures": sum(r["model_failure"] for r in rows),
        "fallbacks": sum(r["fallback"] for r in rows),
        # a failed call on a turn the rules had already resolved is not a fallback
        "model_failure_final_correct": sum(r["model_failure"] and r["correct"] for r in rows),
        "model_failures_rules_resolved": sum(r["model_failure"] and not r["fallback"] for r in rows),
        "fallbacks_final_correct": sum(r["fallback"] and r["correct"] for r in rows),
        "grounded_turns": len(grounded),
        "grounded_ok": sum(r["grounding"]["ok"] for r in grounded),
        "safety_violations": sum(len(r["safety"]) for r in rows),
        "by_lang": dict(sorted(by_lang.items())), "by_kind": dict(sorted(by_kind.items())),
    }


def misses(rows):
    return [{"id": r["id"], "turn": r["turn"], "user": r["user"], "expected": r["expected"],
             "got": r["final_intent"], "source": r["source"],
             **({"grounding_missing": r["grounding"]["missing"]} if not r["grounding"]["ok"] else {})}
            for r in rows if not r["correct"]]


def report_for(mode, splits, runner):
    """Run `runner(case)` over each split. Rows keep case order, so the report is stable."""
    out = {}
    for name in splits:
        rows = [row for case in pick_cases(name, mode) for row in runner(case)]
        out[name] = {"summary": summarise(rows), "misses": misses(rows), "turns": rows}
    total = sum(s["summary"]["safety_violations"] for s in out.values())
    return {"format": FORMAT, "mode": mode, "splits": out,
            "safety_violations": total, "gate": "pass" if total == 0 else "fail"}


def stamp_files():
    return {"dev_sha256": file_sha256(split_path("dev")),
            "heldout_sha256": file_sha256(split_path("heldout"))}


def git_state():
    """Read-only: the current revision and whether the working tree has changes."""
    def git(*args):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                              timeout=20).stdout.strip()
    try:
        return git("rev-parse", "HEAD"), bool(git("status", "--porcelain"))
    except (OSError, subprocess.SubprocessError):
        return None, None


def live_stamp(model):
    rev, dirty = git_state()
    return {**gemini.STAMP, "model": model, **stamp_files(), "git_revision": rev,
            "git_dirty": dirty, "utc_date": datetime.now(timezone.utc).date().isoformat(),
            "python": platform.python_version(), "pydantic": pydantic.VERSION}


def run_rules(splits):
    report = report_for("rules", splits, lambda case: run_case(case, "rules"))
    return {**report, "stamp": stamp_files()}


def run_replay(splits):
    def runner(case):
        return run_case(case, "replay", Script())
    return {**report_for("replay", splits, runner), "stamp": stamp_files()}


def run_live(splits, key, model, sleep=time.sleep):
    client = Live(key, model, sleep)
    report = report_for("live", splits, lambda case: run_case(case, "live", client))
    return {**report, "stamp": live_stamp(model)}, client.raw


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def live_paths(model, split, date):
    stem = f"{date}-{re.sub(r'[^A-Za-z0-9._-]', '_', model)}-{split}"
    n, name = 1, stem
    while (EVALS / "live" / f"{name}.json").exists() or (EVALS / "live" / f"{name}.raw.json").exists():
        n += 1
        name = f"{stem}-run{n}"
    return EVALS / "live" / f"{name}.json", EVALS / "live" / f"{name}.raw.json"


def print_summary(report):
    for name, part in report["splits"].items():
        s = part["summary"]
        print(f"{report['mode']} / {name}: {s['final_correct']}/{s['n']} correct, "
              f"rules only {s['rules_only_correct']}/{s['n']}, wins {s['wins']}, "
              f"regressions {s['regressions']}, fallbacks {s['fallbacks']}, "
              f"model failures {s['model_failures']} "
              f"(final still correct {s['model_failure_final_correct']}), "
              f"safety violations {s['safety_violations']}")
    print(f"gate: {report['gate']}")


def _shown(path):
    try:
        return path.relative_to(ROOT)
    except ValueError:
        return path


def cli(args):
    mode = args.mode
    split = args.split or DEFAULT_SPLIT[mode]
    splits = SPLITS if split == "both" else (split,)
    if mode == "replay" and splits != ("dev",):
        print("replay mode uses the dev split only.")
        return 2
    quiet = getattr(args, "quiet", False)
    if mode == "live":
        key = os.environ.get("PREHEAT_GEMINI_KEY", "").strip()
        if not key:
            print("Live mode needs PREHEAT_GEMINI_KEY (and optionally PREHEAT_GEMINI_MODEL).")
            return 2
        model = os.environ.get("PREHEAT_GEMINI_MODEL", "").strip() or gemini.DEFAULT_MODEL
        report, raw = run_live(splits, key, model)
        path, raw_path = live_paths(model, split, report["stamp"]["utc_date"])
        write_json(path, report)
        write_json(raw_path, {"stamp": report["stamp"], "calls": raw})
        print(f"wrote {_shown(path)} and {_shown(raw_path)}")
    else:
        with network_blocked():
            report = run_rules(splits) if mode == "rules" else run_replay(splits)
        path = Path(args.out) if args.out else EVALS / f"report_{mode}.json"
        write_json(path, report)
        print(f"wrote {path}")
    if not quiet:
        print_summary(report)
    else:
        print(f"gate: {report['gate']}")
    return 0 if report["gate"] == "pass" else 1
