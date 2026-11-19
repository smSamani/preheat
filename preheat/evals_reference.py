"""Expected reply text for the evaluation, written separately from the product.

Nothing here imports `assistant` or `ask`. Each reply kind has its own small table of sentences
(English and Persian) filled from the solver (`optimise.compare_pair`), `diagnostics.json` and the
fixture constants. The number-free explanation topics are read from the stored copy in
`evals/fixtures/expected_topics.json`. Production wording that changes must be changed here too,
on purpose: that is what makes this a check and not an echo.
"""
import json
import re
from pathlib import Path

from . import fixture, optimise

ROOT = Path(__file__).resolve().parent.parent
TOPICS_FILE = ROOT / "evals" / "fixtures" / "expected_topics.json"
LO, HI = 21.5, 24.0                    # the range the product accepts
FLOOR_STEP = 0.01                      # K, the re-solve step quoted in the floor text

HOUSES = {False: ("Current house", "Better-insulated house"),
          True: ("خانه با عایق فعلی", "خانه با عایق بهتر")}


def _hhmm(hour):
    return f"{hour:02d}:00"


PEAK = f"{_hhmm(fixture.EVENING[0])}–{_hhmm(fixture.EVENING[-1] + 1)}"
CHECKS = f"{_hhmm(min(fixture.EVE_CHECK_K))}–{_hhmm(max(fixture.EVE_CHECK_K))}"


def _money(x):
    s = f"{x:.2f}"
    return "0.00" if s == "-0.00" else s


def _pairs(ceiling_c, case="nominal"):
    return [optimise.compare_pair(ceiling_c, fixture.day(case, env)) for env in fixture.ENVELOPES]


def _topics():
    return json.loads(TOPICS_FILE.read_text(encoding="utf-8"))["topics"]


# --- Clarify and decline: one sentence per reason ---------------------------------------------

def _clarify(reason, fa):
    lo, hi = f"{LO:g}", f"{HI:.1f}"
    if fa:
        return {
            "unit": f"فقط درجهٔ سانتی‌گراد رو می‌فهمم. سقف رو به °C بگو، بین {lo} و {hi} درجه.",
            "out_of_range": f"سقف دمای کل روز باید بین {lo} و {hi} درجه باشه. یک عدد تو این بازه بگو.",
            "precision": f"سقف رو حداکثر با یک رقم اعشار بگو. یک عدد بین {lo} و {hi} درجه بده.",
            "several_values": f"فقط یک عدد لازم دارم. کدوم سقف دمای کل روز، بین {lo} و {hi} درجه، رو پیشنهاد بدم؟",
            "strict_bound": f"سقف خودِ عددش رو هم شامل می‌شه. بالاترین دمایی که قبول داری رو به‌عنوان سقف بگو، بین {lo} و {hi} درجه.",
            "target_or_ceiling": f"اینجا فقط سقف دمای کل روز قابل تغییره، نه دمای هدف. بالاترین دمایی که قبول داری رو به‌عنوان سقف بگو، بین {lo} و {hi} درجه.",
            "question_with_value": "برای دیدن یک عدد، اون رو به‌صورت درخواست بنویس، مثلاً «سقف رو بذار روی ... درجه»، یا نوار سقف رو جابه‌جا کن.",
            "type_one_value": f"کدوم عدد رو به‌عنوان سقف دمای کل روز امتحان کنیم؟ یک عدد بین {lo} و {hi} درجه انتخاب کن.",
        }[reason]
    return {
        "unit": f"I only read Celsius. Give the maximum in °C, between {lo} and {hi} °C.",
        "out_of_range": f"The all-day maximum must be between {lo} and {hi} °C. Choose a value in that range.",
        "precision": f"Use at most one decimal place. Give one value between {lo} and {hi} °C.",
        "several_values": f"I need one value. Which single all-day maximum between {lo} and {hi} °C should I propose?",
        "strict_bound": f"A maximum includes its own value. Give the highest temperature you would accept as the maximum, between {lo} and {hi} °C.",
        "target_or_ceiling": f"Only the all-day maximum can be changed here, not a target temperature. Give the highest temperature you would accept as the maximum, between {lo} and {hi} °C.",
        "question_with_value": "To see a value, ask for it directly, for example “set the maximum to” followed by the temperature, or move the ceiling slider.",
        "type_one_value": f"Which single all-day maximum should I propose? Choose a value between {lo} and {hi} °C.",
    }[reason]


def _decline(reason, fa):
    lo, hi = f"{LO:g}", f"{HI:.1f}"
    base, eve = f"{fixture.FLOOR_BASE:g}", f"{fixture.FLOOR_EVE:g}"
    if fa:
        return {
            "negated_action": "باشه، چیزی تغییر نکرد و چیزی محاسبه نشد.",
            "unsupported_floor": f"اینجا فقط سقف دمای کل روز قابل تغییره. حداقل دما ثابته: {base} درجه، و {eve} درجه در نقاط بررسی {CHECKS}.",
            "time_limited": f"سقف برای کل روز اعمال می‌شه و برای بخشی از روز قابل تنظیم نیست. یک سقف کل‌روزه بین {lo} و {hi} درجه انتخاب کن.",
        }[reason]
    return {
        "negated_action": "Understood. Nothing was changed and nothing was calculated.",
        "unsupported_floor": f"Only the all-day maximum can be changed here. The minimum is fixed: {base} °C, and {eve} °C at the {CHECKS} checkpoints.",
        "time_limited": f"The maximum applies to the whole day and cannot be set for part of it. Choose one all-day maximum between {lo} and {hi} °C.",
    }[reason]


# --- Compare ------------------------------------------------------------------------------------

def _compare(metric, fa):
    ceiling_c = fixture.REFERENCE_CEILING
    pairs = _pairs(ceiling_c)
    if metric == "insulation_difference":
        return _insulation(pairs, fa)
    head = (f"با سقف {ceiling_c:.1f} درجه در سناریوی فعلی، در مقایسه با قاعدهٔ یک‌ساعته:" if fa
            else f"At a {ceiling_c:.1f} °C ceiling in this scenario, against the one-hour rule:")
    lines = []
    for name, p in zip(HOUSES[fa], pairs):
        if p["status"] != "ok":
            lines.append(f"{name}: " + ("نتیجه در دسترس نیست." if fa else "result unavailable."))
            continue
        b, o = _money(p["baseline"].cost_eur), _money(p["optimised"].cost_eur)
        saved, avoided = _money(p["saving_eur"]), _money(p["avoided_kwh"])
        if fa:
            line = f"{name}: هزینهٔ روز از {b} به {o} یورو می‌رسه و {saved} یورو کمتر می‌شه."
            if metric == "peak_electricity":
                line += f" مصرف برق عصر {avoided} کیلووات‌ساعت کمتر می‌شه."
        else:
            line = f"{name}: €{b} → €{o} for the day (€{saved} saved)."
            if metric == "peak_electricity":
                line += f" {avoided} kWh less evening electricity."
        lines.append(line)
    return "\n\n".join([head, *lines])


def _insulation(pairs, fa):
    cur, ins = pairs
    if cur["status"] != "ok" or ins["status"] != "ok":
        return ("نتیجهٔ هر دو خانه در دسترس نیست." if fa
                else "Results for both houses are not available in this scenario.")
    ceiling_c = fixture.REFERENCE_CEILING

    def euro(a, b):
        diff = a - b
        if fa:
            return (f"{_money(abs(diff))} یورو {'کمتر' if diff >= 0 else 'بیشتر'}",
                    f"از {_money(a)} به {_money(b)} یورو")
        return (f"€{_money(abs(diff))} {'less' if diff >= 0 else 'more'}",
                f"€{_money(a)} → €{_money(b)}")

    rule_value, rule_move = euro(cur["baseline"].cost_eur, ins["baseline"].cost_eur)
    opt_value, opt_move = euro(cur["optimised"].cost_eur, ins["optimised"].cost_eur)
    if fa:
        return (f"عایق بهتر در برابر عایق فعلی، سقف {ceiling_c:.1f} درجه. هزینهٔ روز با قاعدهٔ "
                f"یک‌ساعته {rule_value} ({rule_move})؛ با پیش‌گرمایش {opt_value} ({opt_move}).")
    return (f"Better insulation vs the current house, {ceiling_c:.1f} °C ceiling: day cost with "
            f"the one-hour rule is {rule_value} ({rule_move}), and with the cost-minimising "
            f"schedule {opt_value} ({opt_move}).")


# --- Explain ------------------------------------------------------------------------------------

def _tariff(fa):
    start, end = _hhmm(fixture.EVENING[0]), _hhmm(fixture.EVENING[-1] + 1)
    eve, normal = f"{fixture.PRICE_EVENING:.2f}", f"{fixture.PRICE_NORMAL:.2f}"
    if fa:
        return (f"بازهٔ گرون از {start} تا {end} است. تعرفهٔ برق در این بازه {eve} یورو به‌ازای هر "
                f"کیلووات‌ساعت و بقیهٔ روز {normal} یورو به‌ازای هر کیلووات‌ساعته.")
    return (f"The peak tariff runs from {start} to {end} at €{eve}/kWh. "
            f"The standard rate is €{normal}/kWh.")


def _comfort(fa):
    ceiling_c = f"{fixture.REFERENCE_CEILING:.1f}"
    base, eve = f"{fixture.FLOOR_BASE:g}", f"{fixture.FLOOR_EVE:g}"
    if fa:
        return (f"سقف فعلی {ceiling_c} درجه است. مدل کف دما رو {base} درجه و در نقاط بررسی "
                f"{CHECKS}، {eve} درجه می‌گیره. این فقط یک جایگزین ساده برای آسایشه.")
    return (f"The current ceiling is {ceiling_c} °C. The minimum is {base} °C, rising to {eve} °C "
            f"at the {CHECKS} hourly checkpoints. These limits on one lumped indoor temperature "
            f"are only a rough stand-in for comfort.")


def _assumptions(fa):
    day = fixture.day("nominal")
    ua = fixture.ENVELOPES
    changes = [t for t in range(1, 24) if day.Tout[t] != day.Tout[t - 1]]
    first, last = _hhmm(changes[0]), _hhmm(changes[1])
    cold, mild = f"{min(day.Tout):g}", f"{max(day.Tout):g}"
    if fa:
        return (f"دمای بیرون {cold} درجه است و از {first} تا {last} به {mild} درجه می‌رسد. "
                f"ظرفیت گرمایی کل خانه (یک مقدار یکپارچه) {day.C:g} کیلووات‌ساعت بر درجه است و "
                f"ضریب مؤثر اتلاف گرمای کل خانه {ua['current']:g} (فعلی) و {ua['insulated']:g} "
                f"(عایق بهتر) کیلووات بر درجه. همهٔ این مقدارها ساختگی‌اند.")
    return (f"Outdoor temperature is {cold} °C, rising to {mild} °C from {first} to {last}. "
            f"Heat capacity (one lumped value for the whole home) is {day.C:g} kWh/K. "
            f"The effective whole-home heat-loss coefficient is {ua['current']:g} kW/K for the "
            f"current house and {ua['insulated']:g} kW/K for the better-insulated one; nothing "
            f"else differs. Internal gains are {min(day.g):g} kW, {max(day.g):g} kW in the "
            f"evening. The heat pump draws up to {day.P_MAX:g} kW electric. All values are invented.")


def _tighter_floor(fa):
    block = json.loads((ROOT / "diagnostics.json").read_text(encoding="utf-8"))["tighter_floor"]
    raise_k = f"{block['raise_k']:g}"
    parts = [f"روز اسمی، سقف {block['ceiling_c']:.1f} درجه:" if fa
             else f"Nominal day, {block['ceiling_c']:.1f} °C:"]
    for name, row in zip(HOUSES[fa], block["rows"]):
        hour = _hhmm(row["hour"])
        base, plus, dual = (_money(row["cost_base"]), _money(row["cost_plus_0_1"]),
                            _money(row["dual_eur_per_k"]))
        if not row["active"]:
            parts.append(
                f"{name}: حداقل دمای {hour} در این روز محدودکننده نیست، برای همین گرم‌تر کردنش "
                f"هزینهٔ روز ({base} یورو) رو تغییر نمی‌ده." if fa
                else f"{name}: the {hour} minimum does not bind on this day, so a warmer minimum "
                     f"leaves the day's cost at €{base}.")
        elif fa:
            parts.append(
                f"{name}: اگه حداقل دمای {hour} رو {raise_k} درجه گرم‌تر کنیم، هزینهٔ روز "
                f"(با حل دوبارهٔ مسئله) از {base} به {plus} یورو می‌رسه. مقدار دوگان LP "
                f"برای این حداقل {dual} یورو به‌ازای هر درجه است و با یک حل دوباره که حداقل رو "
                f"{FLOOR_STEP:g} درجه بالاتر می‌بره هم‌خوانی داره.")
        else:
            parts.append(
                f"{name}: making the {hour} minimum {raise_k} °C warmer raises the day's cost "
                f"from €{base} to €{plus} (re-solved). The LP's dual value for that "
                f"minimum is €{dual} per °C, which agrees with a re-solve {FLOOR_STEP:g} °C higher.")
    return "\n".join(parts)


_BUILT = {"tariff": _tariff, "comfort": _comfort, "assumptions": _assumptions,
          "tighter_floor": _tighter_floor}


# --- Confirm (the full what-if answer after "yes") ----------------------------------------------

def _confirm(value, fa=False):
    """English only, like the command line. `value` is the confirmed ceiling."""
    value = round(float(value), 1)
    pairs = _pairs(value)
    names = dict(zip(fixture.ENVELOPES, HOUSES[False]))
    lines = [f"Maximum indoor temperature {value:.1f} °C, one synthetic winter day (nominal case):"]
    for (env, name), pair in zip(names.items(), pairs):
        if pair["status"] != "ok":
            lines.append(f"  {name}: {pair['status']}: {pair.get('reason')}")
            continue
        b, o = pair["baseline"], pair["optimised"]
        pct = pair["avoided_pct"]
        lines.append(f"  {name}: avoids {_money(pair['avoided_kwh'])} kWh of the one-hour rule's "
                     f"{_money(b.evening_kwh)} kWh evening heat-pump electricity "
                     f"({'n/a' if pct is None else f'{pct:.1f}%'}).")
        lines.append(f"    Day heating cost €{_money(o.cost_eur)} instead of €{_money(b.cost_eur)} "
                     f"with the one-hour rule: €{_money(pair['saving_eur'])} saved that day.")
    parts = []
    for env in fixture.ENVELOPES:
        rows = [optimise.compare_pair(value, fixture.day(k, env)) for k in fixture.CASES]
        ok = [r for r in rows if r["status"] == "ok"]
        if not ok or pairs[list(fixture.ENVELOPES).index(env)]["status"] != "ok":
            continue
        pcts = [r["avoided_pct"] for r in ok if r["avoided_pct"] is not None]
        span = (f"avoided {min(pcts):.1f}% to {max(pcts):.1f}%, " if pcts else "")
        savings = [r["saving_eur"] for r in ok]
        parts.append(f"{span}saved €{_money(min(savings))} to €{_money(max(savings))} "
                     f"({env}, {len(ok)} what-if cases)")
    if parts:
        lines.append("  Across the what-if cases: " + "; ".join(parts) + ".")
    lines.append("Both comparisons are against the one-hour rule. The two measures can rank "
                 "the houses differently. The tool does not recommend a setting.")
    return "\n".join(lines)


# --- Entry point -------------------------------------------------------------------------------

def normalise(text):
    return re.sub(r"\s+", " ", text).strip()


def expected_text(final, persian):
    """The reply text the product should give for the typed `final` intent (a plain dict)."""
    kind = final["kind"]
    if kind == "confirm":
        return _confirm(final["value_c"])
    if kind == "clarify":
        return _clarify(final["reason"], persian)
    if kind == "decline":
        return _decline(final["reason"], persian)
    if kind == "compare":
        return _compare(final["metric"], persian)
    topic = final.get("topic") if kind == "explain" else "out_of_scope"
    if topic in _BUILT:
        return _BUILT[topic](persian)
    return _topics()[topic]["fa" if persian else "en"]
