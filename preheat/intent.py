"""The typed boundary between language and the program.

Every message, from the rules or from the optional Gemini router, ends up as one `Intent`.
Only `ceiling.analyse` can create a `ProposeCeiling`, and only from a value typed in the
message. `ModelChoice` has no numeric field, so the model has no way to send a number.
`decide` is the routing policy; `NOTES` holds the only texts that ever describe a model failure.
"""
import re
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

from . import ceiling

METRICS = ("peak_electricity", "daily_cost", "insulation_difference")
TOPICS = ("preheating", "insulation", "tariff", "comfort", "assumptions", "baseline", "limits",
          "tighter_floor", "out_of_scope")
CLARIFY_REASONS = ("unit", "out_of_range", "precision", "several_values", "strict_bound",
                   "target_or_ceiling", "question_with_value", "type_one_value")
DECLINE_REASONS = ("negated_action", "unsupported_floor", "time_limited")


class _M(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class ProposeCeiling(_M):
    kind: Literal["propose"]
    value_c: float = Field(ge=21.5, le=24.0, allow_inf_nan=False)   # built only by ceiling.py

    @field_validator("value_c")
    @classmethod
    def _on_the_grid(cls, value):
        if round(value * 10) / 10 != value:
            raise ValueError("value_c must be a multiple of 0.1")
        return value


class Compare(_M):
    kind: Literal["compare"]
    metric: Literal["peak_electricity", "daily_cost", "insulation_difference"]


class Explain(_M):
    kind: Literal["explain"]
    topic: Literal["preheating", "insulation", "tariff", "comfort", "assumptions", "baseline",
                   "limits", "tighter_floor", "out_of_scope"]


class Clarify(_M):
    kind: Literal["clarify"]
    reason: Literal["unit", "out_of_range", "precision", "several_values", "strict_bound",
                    "target_or_ceiling", "question_with_value", "type_one_value"]


class Decline(_M):
    kind: Literal["decline"]
    reason: Literal["negated_action", "unsupported_floor", "time_limited"]


class Unresolved(_M):
    kind: Literal["unresolved"]


class CeilingRequest(_M):
    kind: Literal["ceiling_request"]      # model only, no fields


Intent = Annotated[ProposeCeiling | Compare | Explain | Clarify | Decline | Unresolved,
                   Field(discriminator="kind")]
ModelChoice = Annotated[Compare | Explain | Decline | CeilingRequest, Field(discriminator="kind")]
INTENT = TypeAdapter(Intent)
MODEL_CHOICE = TypeAdapter(ModelChoice)

TOOL_TO_KIND = {"show_comparison": "compare", "explain": "explain",
                "decline": "decline", "request_ceiling_change": "ceiling_request"}


@dataclass(frozen=True)
class Failure:
    """A model reply that could not be used. `code` is a key of NOTES."""
    code: str


# The only texts that describe a model problem. Provider text never reaches a reply.
NOTES = {
    "unavailable": "Gemini could not be reached or did not accept the request",
    "timeout": "Gemini did not answer in time",
    "text_only": "Gemini gave no tool choice",
    "multiple_calls": "Gemini gave more than one choice",
    "unknown_tool": "Gemini chose something this dashboard does not offer",
    "invalid_args": "Gemini's choice was not valid",
    "number_check": "A reply failed the number check and was withheld",
}


# --- Read-only rules (no numbers, no ceiling) -------------------------------------------------

_ASSUME = re.compile(r"assum|outdoor|outside|inputs|parameter|فرض|بیرون|ورودی")
_INSULATION = re.compile(r"insulat|عایق")
_COST = re.compile(r"sav|cheaper|cost|bill|spend|euro|€|هزینه|صرفه|ارزون|پول")
_HOW = re.compile(r"\b(why|how(?! much| many)|explain)\b|چرا|چطور|چجور|توضیح")
_HOW_MUCH = re.compile(r"how much|how many|چقدر")
_BASELINE = re.compile(r"baseline|one-hour rule|compared (?:to|with) what|fair|benchmark|مبنا")
_PEAK = re.compile(r"tariff|peak|expensive hours|evening|تعرفه|اوج|ساعت.های گر|عصر")
_ELECTRICITY = re.compile(r"electricity|kwh|consum|avoid|use\b|برق|مصرف")
_COMPARE = re.compile(r"compar|difference|saving|cheaper|cost|bill|spend|electricity|kwh|percent"
                      r"|چقدر|فرق|مقایسه|مصرف|برق|صرفه|هزینه")
_LIMITS = re.compile(r"\b(real|annual|year|yearly|accurate|realistic|limitation|limits)\b"
                     r"|واقعی|سالانه|سال|محدودیت")
_COMFORT = re.compile(r"comfort|temperatur|ceilings?|floor|minimum|warm|cold|راحتی|دمایی|دما|درجه|گرم|سرد")
_RETRACT = re.compile(r"\b(?:forget (?:it|that|about)|never ?mind|changed my mind|scratch that|"
                      r"cancel that|ignore that)\b|بیخیال|بی خیال|فراموش|منصرف|ولش کن")
_FLOOR_COST = re.compile(r"cost|price|expensive|pay|extra|how much|what would|what if|هزینه|قیمت|"
                         r"چقدر|گرون|چی میشه")
_FLOOR_ACTION = re.compile(
    r"\b(set|change|make|raise|lower|switch|turn|drop|put|increase|reduce|cut|stop|warmer|colder|"
    r"cooler|higher|lower|up|down|off)\b|بذار|بگذار|تنظیم|خاموش|کم کن|زیاد کن|گرم تر|سرد تر|"
    r"بالا|پایین|عوض|تغییر")


def rules_intent(message):
    """Read-only rules: Compare, Explain, Decline or Unresolved. Never a ceiling proposal."""
    m = ceiling.normalise(message)
    if _RETRACT.search(m):
        return Decline(kind="decline", reason="negated_action")
    if ceiling.FLOOR.search(m):
        if _FLOOR_COST.search(m):
            return Explain(kind="explain", topic="tighter_floor")
        if _FLOOR_ACTION.search(m):
            return Decline(kind="decline", reason="unsupported_floor")
    if _ASSUME.search(m):
        return Explain(kind="explain", topic="assumptions")
    if _INSULATION.search(m):
        if _HOW.search(m) and not _HOW_MUCH.search(m):
            return Explain(kind="explain", topic="insulation")
        return Compare(kind="compare", metric="insulation_difference")
    if _PEAK.search(m) and _ELECTRICITY.search(m):
        return Compare(kind="compare", metric="peak_electricity")
    if _PEAK.search(m):
        return Explain(kind="explain", topic="tariff")
    if _BASELINE.search(m):
        return Explain(kind="explain", topic="baseline")
    if _HOW.search(m) and not _HOW_MUCH.search(m):
        return Explain(kind="explain", topic="preheating")
    if _COST.search(m):
        return Compare(kind="compare", metric="daily_cost")
    if _COMPARE.search(m):
        return Compare(kind="compare", metric="peak_electricity")
    if _LIMITS.search(m):
        return Explain(kind="explain", topic="limits")
    if _COMFORT.search(m):
        return Explain(kind="explain", topic="comfort")
    return Unresolved(kind="unresolved")


# --- Routing policy ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Decision:
    intent: object          # an Intent (never Unresolved)
    source: str             # "rules" or "gemini"
    code: str = ""          # failure code when the model was asked and could not be used
    rules: object = None    # what the rules returned (a grammar result or a rules intent)
    model: object = None    # the raw model choice or Failure, if the model was asked

    @property
    def note(self):
        return NOTES.get(self.code, "")


def _grammar_intent(result):
    if isinstance(result, ceiling.Proposal):
        return ProposeCeiling(kind="propose", value_c=result.value)
    if result.kind == "clarify":
        return Clarify(kind="clarify", reason=result.reason)
    return Decline(kind="decline", reason=result.reason)


def _checked(choice):
    """A model callback's result must be a Failure or a valid ModelChoice, nothing else.

    A proposal, a dict, None or any other object becomes Failure("invalid_args")."""
    if isinstance(choice, Failure):
        return choice
    try:
        return MODEL_CHOICE.validate_python(choice, strict=True)
    except ValidationError:
        return Failure("invalid_args")


def decide(message, ask=None, *, always_ask=False):
    """Apply the routing policy to the latest message. No solver is involved.

    1. A grammar Proposal or Block is final.
    2. A resolved read-only rule is final.
    3. If the rules return Unresolved: with no `ask`, out_of_scope; with a valid model choice,
       that choice (request_ceiling_change becomes a question); on a model failure,
       out_of_scope plus the failure code.
    `ask(message)` returns a ModelChoice or a Failure. It is called only for Unresolved
    messages, or for every message when `always_ask` is set (evaluation logs the raw choice
    and never uses it for a message the rules resolved)."""
    grammar = ceiling.analyse(message)
    if grammar is not ceiling.NoCeiling:
        model = _checked(ask(message)) if (ask and always_ask) else None
        return Decision(_grammar_intent(grammar), "rules", rules=grammar, model=model)
    rules = rules_intent(message)
    resolved = not isinstance(rules, Unresolved)
    model = _checked(ask(message)) if (ask and (always_ask or not resolved)) else None
    if resolved:
        return Decision(rules, "rules", rules=rules, model=model)
    fallback = Explain(kind="explain", topic="out_of_scope")
    if model is None:
        return Decision(fallback, "rules", rules=rules)
    if isinstance(model, Failure):
        return Decision(fallback, "rules", code=model.code, rules=rules, model=model)
    if isinstance(model, CeilingRequest):
        return Decision(Clarify(kind="clarify", reason="type_one_value"), "gemini",
                        rules=rules, model=model)
    return Decision(model, "gemini", rules=rules, model=model)
