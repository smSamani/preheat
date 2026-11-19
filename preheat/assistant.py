"""Scenario assistant for the dashboard and the command line.

Every reply is a fixed English or Persian template filled from named solver fields. The typed
`Intent` (see intent.py) decides which template; the optional Gemini router only helps choose an
intent for read-only questions and its own words are never shown. Before a reply leaves the
server, `ground` re-checks every number in it against the solver output for the active scenario
(value, sign, unit, house and whether it is a level or a reduction). The templates are the
guarantee; the checker is a regression guard that catches a template edited into a wrong number.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

from . import fixture, intent, sweep

DIAGNOSTICS = Path(__file__).resolve().parent.parent / "diagnostics.json"

FA_CHARACTERS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫يك", "01234567890123456789.یک")
PERSIAN = re.compile(r"[؀-ۿ]")

PEAK_START, PEAK_END = fixture.EVENING[0], fixture.EVENING[-1] + 1
PEAK_TEXT = f"{PEAK_START:02d}:00–{PEAK_END:02d}:00"
CHECKS = f"{min(fixture.EVE_CHECK_K):02d}:00–{max(fixture.EVE_CHECK_K):02d}:00"
_NOMINAL_TOUT = fixture.day().Tout
WEATHER_HOURS = [t for t in range(1, 24) if _NOMINAL_TOUT[t] != _NOMINAL_TOUT[t - 1]]
DAY_START, DAY_END = (f"{h:02d}:00" for h in WEATHER_HOURS[:2])

# --- Server-rendered replies ---------------------------------------------------------------

def assumptions(case="nominal"):
    """The model's inputs for one case, read from the fixture."""
    day = fixture.day(case)
    return {
        "heat_capacity_kwh_per_k": day.C,
        "heat_loss_kw_per_k": {name: fixture.day(case, name).UA for name in fixture.ENVELOPES},
        "heat_pump_max_electric_kw": day.P_MAX,
        "cop_range": [min(day.COP), max(day.COP)],
        "outdoor_c": {"minimum": min(day.Tout), "maximum": max(day.Tout)},
        "internal_gains_kw": {"minimum": min(day.g), "maximum": max(day.g)},
        "start_temperature_c": day.T0,
    }


def assumption_text(case, persian):
    a = assumptions(case)
    ua, out, gains = a["heat_loss_kw_per_k"], a["outdoor_c"], a["internal_gains_kw"]
    if persian:
        return (f"دمای بیرون {out['minimum']:g} درجه است و از {DAY_START} تا {DAY_END} به {out['maximum']:g} درجه می‌رسد. "
                f"ظرفیت گرمایی کل خانه (یک مقدار یکپارچه) {a['heat_capacity_kwh_per_k']:g} کیلووات‌ساعت بر درجه است و ضریب مؤثر اتلاف گرمای کل خانه "
                f"{ua['current']:g} (فعلی) و {ua['insulated']:g} (عایق بهتر) کیلووات بر درجه. "
                "همهٔ این مقدارها ساختگی‌اند.")
    return (f"Outdoor temperature is {out['minimum']:g} °C, rising to {out['maximum']:g} °C from {DAY_START} to {DAY_END}. "
            f"Heat capacity (one lumped value for the whole home) is {a['heat_capacity_kwh_per_k']:g} kWh/K. "
            f"The effective whole-home heat-loss coefficient is {ua['current']:g} kW/K for the current house "
            f"and {ua['insulated']:g} kW/K for the better-insulated one; nothing else differs. Internal gains are "
            f"{gains['minimum']:g} kW, {gains['maximum']:g} kW in the evening. The heat pump draws up to "
            f"{a['heat_pump_max_electric_kw']:g} kW electric. All values are invented.")


@lru_cache(maxsize=1)
def _diagnostics_floor():
    with open(DIAGNOSTICS, encoding="utf-8") as f:
        return json.load(f)["tighter_floor"]


def tighter_floor_block():
    """The committed `tighter_floor` block of diagnostics.json (nominal day, 22.5 °C)."""
    return _diagnostics_floor()


def tighter_floor_text(block, persian):
    """Fixed template for "what would a tighter 21:00 floor cost?", filled from diagnostics.json.
    Always labelled as the nominal day at the reference ceiling, whatever scenario is active."""
    raise_k, ceiling = block["raise_k"], block["ceiling_c"]
    step = sweep.FD_STEP
    names = dict(zip(fixture.ENVELOPES, _names(persian)))
    head = (f"روز اسمی، سقف {ceiling:.1f} درجه:" if persian
            else f"Nominal day, {ceiling:.1f} °C:")
    paragraphs = [head]
    for row in block["rows"]:
        name, hour = names[row["envelope"]], f"{row['hour']:02d}:00"
        base, plus, dual = row["cost_base"], row["cost_plus_0_1"], row["dual_eur_per_k"]
        if not row["active"]:
            paragraphs.append(
                f"{name}: حداقل دمای {hour} در این روز محدودکننده نیست، برای همین گرم‌تر کردنش "
                f"هزینهٔ روز ({base:.2f} یورو) رو تغییر نمی‌ده." if persian
                else f"{name}: the {hour} minimum does not bind on this day, so a warmer minimum "
                     f"leaves the day's cost at €{base:.2f}.")
        elif persian:
            paragraphs.append(
                f"{name}: اگه حداقل دمای {hour} رو {raise_k:g} درجه گرم‌تر کنیم، هزینهٔ روز "
                f"(با حل دوبارهٔ مسئله) از {base:.2f} به {plus:.2f} یورو می‌رسه. مقدار دوگان LP "
                f"برای این حداقل {dual:.2f} یورو به‌ازای هر درجه است و با یک حل دوباره که حداقل رو "
                f"{step:g} درجه بالاتر می‌بره هم‌خوانی داره.")
        else:
            paragraphs.append(
                f"{name}: making the {hour} minimum {raise_k:g} °C warmer raises the day's cost "
                f"from €{base:.2f} to €{plus:.2f} (re-solved). The LP's dual value for that "
                f"minimum is €{dual:.2f} per °C, which agrees with a re-solve {step:g} °C higher.")
    return "\n".join(paragraphs)


def topic_text(topic, results, persian):
    ceiling = results["ceiling"]
    if topic == "tighter_floor":
        return {"text": tighter_floor_text(results.get("tighter_floor") or tighter_floor_block(),
                                           persian)}
    fa = {
        "preheating": "حل‌گر بخشی از گرمایش رو به قبل از ساعت‌های گرون منتقل می‌کنه، چون اون موقع برق ارزون‌تره. خونه گرما رو نگه می‌داره و بعد به‌تدریج سرد می‌شه. هر دو برنامه همون کف و سقف دمای داخل رو رعایت می‌کنن. صرفه‌جویی‌ها در مقایسه با یک قاعدهٔ سادهٔ یک‌ساعته است.",
        "insulation": "خونه با عایق بهتر، برای یک اختلاف دمای یکسان، گرمای کمتری به بیرون پس می‌ده. برای همین بعد از پیش‌گرمایش مدت بیشتری گرم می‌مونه و معمولاً تو ساعات گرون کمتر به پمپ نیاز داره. مبلغ دقیق رو می‌تونی تو کارت مقایسه ببینی.",
        "tariff": f"بازهٔ گرون از {PEAK_START:02d}:00 تا {PEAK_END:02d}:00 است. تعرفهٔ برق در این بازه {fixture.PRICE_EVENING:.2f} یورو به‌ازای هر کیلووات‌ساعت و بقیهٔ روز {fixture.PRICE_NORMAL:.2f} یورو به‌ازای هر کیلووات‌ساعته.",
        "comfort": f"سقف فعلی {ceiling:.1f} درجه است. مدل کف دما رو {fixture.FLOOR_BASE:g} درجه و در نقاط بررسی {CHECKS}، {fixture.FLOOR_EVE:g} درجه می‌گیره. این فقط یک جایگزین ساده برای آسایشه.",
        "baseline": "مبنای مقایسه یک قاعدهٔ سادهٔ یک‌ساعته است: هر ساعت فقط به اندازهٔ لازم گرم می‌کنه تا ساعت بعد به حداقل دما برسه و به قیمت برق توجهی نداره. یک مقایسهٔ منصفانه‌تر، با همون آگاهی از کل روز ولی بی‌توجه به قیمت، صرفه‌جویی خیلی کمتری نشون می‌ده (README رو ببین).",
        "limits": "همهٔ اعداد مربوط به یک خانهٔ ساختگی در یک روز زمستانی ساختگی هستند. نباید اون‌ها رو به سال یا به یک خانهٔ واقعی تعمیم داد. هیچ ساکنی در این کار مشارکت نداشته.",
        "out_of_scope": "این سؤال خارج از این مدل است. می‌تونم مدل رو توضیح بدم، دو خونه رو مقایسه کنم یا سقف دمای جدید پیشنهاد کنم.",
    }
    en = {
        "preheating": "The solver heats earlier while electricity is cheaper. The house cools gradually, so the heat pump can run less during the peak tariff. Both schedules respect the same indoor temperature limits. Savings are measured against a simple one-hour rule.",
        "insulation": "Better insulation reduces heat loss at the same indoor–outdoor temperature difference. The house stays warm longer after preheating and usually needs less heat during peak hours. The comparison card shows the effect for this scenario.",
        "tariff": f"The peak tariff runs from {PEAK_START:02d}:00 to {PEAK_END:02d}:00 at €{fixture.PRICE_EVENING:.2f}/kWh. The standard rate is €{fixture.PRICE_NORMAL:.2f}/kWh.",
        "comfort": f"The current ceiling is {ceiling:.1f} °C. The minimum is {fixture.FLOOR_BASE:g} °C, rising to {fixture.FLOOR_EVE:g} °C at the {CHECKS} hourly checkpoints. These limits on one lumped indoor temperature are only a rough stand-in for comfort.",
        "baseline": "Savings are measured against a simple one-hour rule: each hour it heats just enough to reach the next hour's minimum and ignores prices. A fairer price-blind comparator with the same whole-day foresight shows much smaller savings (see the README).",
        "limits": "All numbers describe one invented house on one invented winter day. They should not be scaled to a year or applied to a real home. No occupants took part.",
        "out_of_scope": "That is outside this model. I can explain it, compare the two houses, or propose a new maximum temperature.",
    }
    if topic == "assumptions":
        return {"text": assumption_text(results["case"], persian)}
    return {"text": (fa if persian else en)[topic]}


def _names(persian):
    return ("خانه با عایق فعلی", "خانه با عایق بهتر") if persian else ("Current house", "Better-insulated house")


def comparison(results, persian, cost_only):
    title = (f"با سقف {results['ceiling']:.1f} درجه در سناریوی فعلی، در مقایسه با قاعدهٔ یک‌ساعته:"
             if persian else f"At a {results['ceiling']:.1f} °C ceiling in this scenario, against the one-hour rule:")
    lines = []
    for name, pair in zip(_names(persian), results["envelopes"].values()):
        if pair["status"] != "ok":
            lines.append(f"{name}: " + ("نتیجه در دسترس نیست." if persian else "result unavailable."))
            continue
        base, opt = pair["baseline"], pair["optimised"]
        if persian:
            line = (f"{name}: هزینهٔ روز از {base['cost_eur']:.2f} به {opt['cost_eur']:.2f} یورو می‌رسه"
                    f" و {pair['saving_eur']:.2f} یورو کمتر می‌شه.")
            if not cost_only:
                line += f" مصرف برق عصر {pair['avoided_kwh']:.2f} کیلووات‌ساعت کمتر می‌شه."
        else:
            line = (f"{name}: €{base['cost_eur']:.2f} → €{opt['cost_eur']:.2f} for the day"
                    f" (€{pair['saving_eur']:.2f} saved).")
            if not cost_only:
                line += f" {pair['avoided_kwh']:.2f} kWh less evening electricity."
        lines.append(line)
    return "\n\n".join([title, *lines])


def comparison_reply(results, persian, peak_energy, cost_only):
    rows = []
    for label, pair in zip(_names(persian), results["envelopes"].values()):
        if pair["status"] != "ok":
            continue
        baseline, optimised = pair["baseline"], pair["optimised"]
        if peak_energy:
            value = (f"{pair['avoided_kwh']:.2f} کیلووات‌ساعت کمتر" if persian
                     else f"{pair['avoided_kwh']:.2f} kWh less")
            detail = (f"از {baseline['evening_kwh']:.2f} به {optimised['evening_kwh']:.2f} کیلووات‌ساعت" if persian
                      else f"{baseline['evening_kwh']:.2f} → {optimised['evening_kwh']:.2f} kWh")
        else:
            value = f"{pair['saving_eur']:.2f} یورو کمتر" if persian else f"€{pair['saving_eur']:.2f} saved"
            detail = (f"از {baseline['cost_eur']:.2f} به {optimised['cost_eur']:.2f} یورو" if persian
                      else f"€{baseline['cost_eur']:.2f} → €{optimised['cost_eur']:.2f}")
        rows.append({"label": label, "value": value, "detail": detail})
    if peak_energy:
        title = (f"برق عصر ({PEAK_TEXT}) در مقایسه با قاعدهٔ یک‌ساعته" if persian
                 else f"Evening electricity ({PEAK_TEXT}) avoided vs the one-hour rule")
    else:
        title = ("صرفه‌جویی هزینهٔ روز در مقایسه با قاعدهٔ یک‌ساعته" if persian
                 else "Daily cost saved vs the one-hour rule")
    reply = {"text": comparison(results, persian, cost_only)}
    if len(rows) == len(results["envelopes"]):
        reply["comparison"] = {"title": title, "rows": rows}
    return reply


def insulation_difference(results):
    """Between-house differences (current minus better insulated), or None."""
    env = results["envelopes"]
    cur, ins = env.get("current"), env.get("insulated")
    if not cur or not ins or cur["status"] != "ok" or ins["status"] != "ok":
        return None
    return {
        "rule_cost": (cur["baseline"]["cost_eur"], ins["baseline"]["cost_eur"]),
        "opt_cost": (cur["optimised"]["cost_eur"], ins["optimised"]["cost_eur"]),
        "opt_evening": (cur["optimised"]["evening_kwh"], ins["optimised"]["evening_kwh"]),
        "savings": (cur["saving_eur"], ins["saving_eur"]),
    }


def insulation_reply(results, persian):
    d = insulation_difference(results)
    if d is None:
        return {"text": "نتیجهٔ هر دو خانه در دسترس نیست." if persian
                else "Results for both houses are not available in this scenario."}

    def less(pair, unit):
        diff = pair[0] - pair[1]
        if persian:
            word = "کمتر" if diff >= 0 else "بیشتر"
            return f"{abs(diff):.2f} {'یورو' if unit == '€' else 'کیلووات‌ساعت'} {word}"
        word = "less" if diff >= 0 else "more"
        return f"€{abs(diff):.2f} {word}" if unit == "€" else f"{abs(diff):.2f} kWh {word}"

    def arrow(pair, unit):
        if persian:
            return f"از {pair[0]:.2f} به {pair[1]:.2f} {'یورو' if unit == '€' else 'کیلووات‌ساعت'}"
        return (f"€{pair[0]:.2f} → €{pair[1]:.2f}" if unit == "€"
                else f"{pair[0]:.2f} → {pair[1]:.2f} kWh")

    if persian:
        title = f"عایق بهتر در برابر عایق فعلی، سقف {results['ceiling']:.1f} درجه"
        labels = ("هزینهٔ روز با قاعدهٔ یک‌ساعته", "هزینهٔ روز با پیش‌گرمایش",
                  f"برق عصر ({PEAK_TEXT}) با پیش‌گرمایش", "صرفه‌جویی پیش‌گرمایش در هر خانه")
        saving = (f"{d['savings'][0]:.2f} و {d['savings'][1]:.2f} یورو",
                  "خانهٔ فعلی و خانه با عایق بهتر، در مقایسه با قاعدهٔ یک‌ساعته")
    else:
        title = f"Better insulation vs the current house, {results['ceiling']:.1f} °C ceiling"
        labels = ("Day cost, one-hour rule", "Day cost, cost-minimising schedule",
                  f"Evening electricity ({PEAK_TEXT}), cost-minimising", "Preheating saving within each house")
        saving = (f"€{d['savings'][0]:.2f} / €{d['savings'][1]:.2f}",
                  "current / better insulated, each vs its own one-hour rule")
    rows = [
        {"label": labels[0], "value": less(d["rule_cost"], "€"), "detail": arrow(d["rule_cost"], "€")},
        {"label": labels[1], "value": less(d["opt_cost"], "€"), "detail": arrow(d["opt_cost"], "€")},
        {"label": labels[2], "value": less(d["opt_evening"], "kWh"), "detail": arrow(d["opt_evening"], "kWh")},
        {"label": labels[3], "value": saving[0], "detail": saving[1]},
    ]
    if persian:
        text = (f"{title}. هزینهٔ روز با قاعدهٔ یک‌ساعته {less(d['rule_cost'], '€')} ({arrow(d['rule_cost'], '€')})؛ "
                f"با پیش‌گرمایش {less(d['opt_cost'], '€')} ({arrow(d['opt_cost'], '€')}).")
    else:
        text = (f"{title}: day cost with the one-hour rule is {less(d['rule_cost'], '€')} "
                f"({arrow(d['rule_cost'], '€')}), and with the cost-minimising schedule "
                f"{less(d['opt_cost'], '€')} ({arrow(d['opt_cost'], '€')}).")
    return {"text": text, "comparison": {"title": title, "rows": rows}}


def clarify_text(reason, persian):
    lo, hi = f"{sweep.LO:g}", f"{sweep.HI:.1f}"
    fa = {
        "unit": f"فقط درجهٔ سانتی‌گراد رو می‌فهمم. سقف رو به °C بگو، بین {lo} و {hi} درجه.",
        "out_of_range": f"سقف دمای کل روز باید بین {lo} و {hi} درجه باشه. یک عدد تو این بازه بگو.",
        "precision": f"سقف رو حداکثر با یک رقم اعشار بگو. یک عدد بین {lo} و {hi} درجه بده.",
        "several_values": f"فقط یک عدد لازم دارم. کدوم سقف دمای کل روز، بین {lo} و {hi} درجه، رو پیشنهاد بدم؟",
        "strict_bound": f"سقف خودِ عددش رو هم شامل می‌شه. بالاترین دمایی که قبول داری رو به‌عنوان سقف بگو، بین {lo} و {hi} درجه.",
        "target_or_ceiling": f"اینجا فقط سقف دمای کل روز قابل تغییره، نه دمای هدف. بالاترین دمایی که قبول داری رو به‌عنوان سقف بگو، بین {lo} و {hi} درجه.",
        "question_with_value": "برای دیدن یک عدد، اون رو به‌صورت درخواست بنویس، مثلاً «سقف رو بذار روی ... درجه»، یا نوار سقف رو جابه‌جا کن.",
        "type_one_value": f"کدوم عدد رو به‌عنوان سقف دمای کل روز امتحان کنیم؟ یک عدد بین {lo} و {hi} درجه انتخاب کن.",
    }
    en = {
        "unit": f"I only read Celsius. Give the maximum in °C, between {lo} and {hi} °C.",
        "out_of_range": f"The all-day maximum must be between {lo} and {hi} °C. Choose a value in that range.",
        "precision": f"Use at most one decimal place. Give one value between {lo} and {hi} °C.",
        "several_values": f"I need one value. Which single all-day maximum between {lo} and {hi} °C should I propose?",
        "strict_bound": f"A maximum includes its own value. Give the highest temperature you would accept as the maximum, between {lo} and {hi} °C.",
        "target_or_ceiling": f"Only the all-day maximum can be changed here, not a target temperature. Give the highest temperature you would accept as the maximum, between {lo} and {hi} °C.",
        "question_with_value": "To see a value, ask for it directly, for example \u201cset the maximum to\u201d followed by the temperature, or move the ceiling slider.",
        "type_one_value": f"Which single all-day maximum should I propose? Choose a value between {lo} and {hi} °C.",
    }
    return (fa if persian else en)[reason]


def decline_text(reason, persian):
    lo, hi = f"{sweep.LO:g}", f"{sweep.HI:.1f}"
    fa = {
        "negated_action": "باشه، چیزی تغییر نکرد و چیزی محاسبه نشد.",
        "unsupported_floor": f"اینجا فقط سقف دمای کل روز قابل تغییره. حداقل دما ثابته: {fixture.FLOOR_BASE:g} درجه، و {fixture.FLOOR_EVE:g} درجه در نقاط بررسی {CHECKS}.",
        "time_limited": f"سقف برای کل روز اعمال می‌شه و برای بخشی از روز قابل تنظیم نیست. یک سقف کل‌روزه بین {lo} و {hi} درجه انتخاب کن.",
    }
    en = {
        "negated_action": "Understood. Nothing was changed and nothing was calculated.",
        "unsupported_floor": f"Only the all-day maximum can be changed here. The minimum is fixed: {fixture.FLOOR_BASE:g} °C, and {fixture.FLOOR_EVE:g} °C at the {CHECKS} checkpoints.",
        "time_limited": f"The maximum applies to the whole day and cannot be set for part of it. Choose one all-day maximum between {lo} and {hi} °C.",
    }
    return (fa if persian else en)[reason]


def render(item, results, persian):
    """One Intent -> a reply dict: {"ceiling"}, {"text"} or {"text", "comparison"}.
    `results` is only read for a Compare intent."""
    if isinstance(item, intent.ProposeCeiling):
        return {"ceiling": item.value_c}
    if isinstance(item, intent.Compare):
        if item.metric == "insulation_difference":
            return insulation_reply(results, persian)
        return comparison_reply(results, persian, item.metric == "peak_electricity",
                                item.metric == "daily_cost")
    if isinstance(item, intent.Clarify):
        return {"text": clarify_text(item.reason, persian)}
    if isinstance(item, intent.Decline):
        return {"text": decline_text(item.reason, persian)}
    topic = item.topic if isinstance(item, intent.Explain) else "out_of_scope"
    return topic_text(topic, results, persian)


def with_topic_data(chosen, results):
    """Add the precomputed floor block to `results` when the intent is the floor topic."""
    if getattr(chosen, "topic", None) == "tighter_floor":
        return {**results, "tighter_floor": tighter_floor_block()}
    return results


def local_reply(message, results):
    """Rules-only reply to one message (used by tests)."""
    chosen = intent.decide(message).intent
    return render(chosen, with_topic_data(chosen, results), bool(PERSIAN.search(message)))


# --- Number grounding ----------------------------------------------------------------------

UNITS = [
    ("eur_per_kwh", r"(?:€|eur\b|euros?\b)\s*(?:/|per)\s*kwh|یورو (?:به‌ازای|برای) هر کیلووات‌?\s?ساعت"),
    ("kwh_per_k", r"kwh\s*/\s*k\b|کیلووات‌?\s?ساعت بر درجه"),
    ("kw_per_k", r"kw\s*/\s*k\b|کیلووات بر درجه"),
    ("kwh", r"kwh\b|کیلووات‌?\s?ساعت"),
    ("kw", r"kw\b|کیلووات"),
    ("pct", r"%|percent\b|درصد"),
    ("degc", r"°\s*c\b|°|degrees?\b|deg\b|درجه"),
    ("eur", r"€|eur\b|euros?\b|یورو"),
    ("cent", r"cents?\b|سنت"),
]
UNIT_RE = [(name, re.compile(r"\s*(?:" + pattern + ")", re.I)) for name, pattern in UNITS]
PER_KWH = re.compile(r"\s*(?:/|per)\s*kwh|\s*یورو (?:به‌ازای|برای) هر کیلووات", re.I)
TOKEN = re.compile(r"(?P<sign1>(?<![\w.])[-−]\s*)?(?P<eur>€\s*)?(?P<sign2>[-−])?"
                   r"(?P<num>(?<![\w.])\d+(?:[.,]\d+)?)(?![\d:])")
CLOCK_TIME = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)")
REDUCTION = re.compile(r"sav|less|lower|avoid|reduc|cheaper|smaller|more\b|کمتر|بیشتر|صرفه|کاهش|ارزان", re.I)
LEVEL = re.compile(r"cost|bill|spend|هزینه", re.I)
BREAKS = r"[(),;:→/—،]"
CURRENT_HOUSE = re.compile(r"current (?:house|insulation)|current-house|عایق فعلی|خانهٔ? فعلی", re.I)
INSULATED_HOUSE = re.compile(r"better[- ]insulat|insulated house|عایق بهتر", re.I)
SAFE_TEXT = {False: ("I can't show that answer reliably, so it was left out. The cards and charts "
                     "show the solver's numbers for this scenario."),
             True: "نمی‌تونم این جواب رو با اطمینان نشون بدم. کارت‌ها و نمودارها اعداد حل‌گر رو برای این سناریو نشون می‌دن."}


def facts(results):
    """(house or None, unit, kind, value) for every number a reply may state."""
    out = []
    case = fixture.day(results["case"])
    for env, pair in results["envelopes"].items():
        if pair["status"] != "ok":
            continue
        for plan in ("baseline", "optimised"):
            out.append((env, "eur", "level", pair[plan]["cost_eur"]))
            out.append((env, "kwh", "level", pair[plan]["evening_kwh"]))
        out.append((env, "eur", "reduction", pair["saving_eur"]))
        out.append((env, "kwh", "reduction", pair["avoided_kwh"]))
        if pair.get("avoided_pct") is not None:
            out.append((env, "pct", "reduction", pair["avoided_pct"]))
    block = results.get("tighter_floor")
    if block:
        for row in block["rows"]:
            for key in ("cost_base", "cost_plus_0_1"):
                out.append((row["envelope"], "eur", "level", row[key]))
            out.append((row["envelope"], "eur", "any", row["dual_eur_per_k"]))
        for value in (block["ceiling_c"], block["raise_k"], sweep.FD_STEP):
            out.append((None, "degc", "level", value))
    diff = insulation_difference(results)
    if diff:
        for key, unit in (("rule_cost", "eur"), ("opt_cost", "eur"), ("opt_evening", "kwh")):
            out.append((None, unit, "any", abs(diff[key][0] - diff[key][1])))
    for value in (results["ceiling"], fixture.FLOOR_BASE, fixture.FLOOR_EVE, sweep.LO, sweep.HI,
                  case.T0, min(case.Tout), max(case.Tout)):
        out.append((None, "degc", "level", value))
    for value in (fixture.PRICE_NORMAL, fixture.PRICE_EVENING):
        out.append((None, "eur_per_kwh", "level", value))
    out.append((None, "kwh_per_k", "level", case.C))
    for env in fixture.ENVELOPES:
        out.append((None, "kw_per_k", "level", fixture.ENVELOPES[env]))
    for value in (case.P_MAX, min(case.g), max(case.g)):
        out.append((None, "kw", "level", value))
    for value in (min(case.COP), max(case.COP)):
        out.append((None, "none", "level", value))
    return out


def clock_times():
    hours = {PEAK_START, PEAK_END, min(fixture.EVE_CHECK_K), max(fixture.EVE_CHECK_K), *WEATHER_HOURS}
    return {f"{h:02d}:00" for h in hours}


def _matches(token, decimals, negative, value):
    if decimals == 0 and abs(value - round(value)) > 1e-9:
        return False                       # an integer must be exact, not a rounded decimal
    shown = f"{value:.{decimals}f}"
    if float(shown) == 0:
        shown = shown.lstrip("-")          # -0.00 counts as 0.00
    return shown == ("-" if negative else "") + token


def _sentences(text):
    """Yield (sentence, house) with house None when no single house is named."""
    for paragraph in text.split("\n"):
        inherited = None
        for sentence in re.split(r"(?<=[.!?؟;:])\s+", paragraph):
            named = {h for h, rx in (("current", CURRENT_HOUSE), ("insulated", INSULATED_HOUSE))
                     if rx.search(sentence)}
            if len(named) == 1:
                inherited = named.pop()
                yield sentence, inherited
            elif named:
                inherited = None
                yield sentence, None
            else:
                yield sentence, inherited


def ungrounded_numbers(text, results):
    """Numbers in `text` that no solver/fixture fact supports, with a short reason each.

    A number is grounded only if some fact has the same value at the shown precision, the same
    sign and unit (€, €/kWh, kWh, kW, %, °C, kWh/K, kW/K), belongs to the house the sentence
    names (if it names exactly one), and is a reduction when the words around it say saved,
    less or avoided (or a level when they say cost or bill). Clock times must be model hours."""
    known = facts(results)
    allowed_clocks = clock_times()
    problems = []
    for sentence, house in _sentences(text.translate(FA_CHARACTERS)):
        for m in CLOCK_TIME.finditer(sentence):
            if m.group(0).zfill(5) not in allowed_clocks:
                problems.append(f"{m.group(0)} (unknown time)")
        sentence = CLOCK_TIME.sub(lambda m: " " * len(m.group(0)), sentence)
        tokens = list(TOKEN.finditer(sentence))
        for i, m in enumerate(tokens):
            token = m.group("num").replace(",", ".")
            decimals = len(token.split(".")[1]) if "." in token else 0
            negative = bool(m.group("sign1") or m.group("sign2"))
            rest = sentence[m.end():]
            unit, unit_end = "none", m.end()
            if m.group("eur"):
                per = PER_KWH.match(rest)
                unit = "eur_per_kwh" if per else "eur"
                unit_end += per.end() if per else 0
            else:
                for name, rx in UNIT_RE:
                    u = rx.match(rest)
                    if u:
                        unit, unit_end = name, m.end() + u.end()
                        break
            # Words count for the nearest number: the text before stops at the previous number
            # or punctuation, the text after stops at the next number or punctuation.
            prev_end = tokens[i - 1].end() if i else 0
            stop = tokens[i + 1].start() if i + 1 < len(tokens) else len(sentence)
            before = re.split(BREAKS, sentence[max(prev_end, m.start() - 40):m.start()])[-1]
            after = re.split(BREAKS, sentence[unit_end:min(stop, unit_end + 30)])[0]
            reduction = bool(REDUCTION.search(before) or REDUCTION.search(after))
            level = bool(LEVEL.search(before))
            kinds = ({"reduction", "any"} if reduction and not level
                     else {"level", "any"} if level and not reduction
                     else {"level", "reduction", "any"})
            ok = any((house is None or f_house in (None, house))
                     and (unit == "none" or f_unit == unit)
                     and f_kind in kinds
                     and _matches(token, decimals, negative, value)
                     for f_house, f_unit, f_kind, value in known)
            if not ok:
                label = ("-" if negative else "") + token
                problems.append(f"{label} ({unit}{', ' + house if house else ''})")
    return problems


def _reply_strings(reply):
    if "text" in reply:
        yield reply["text"]
    card = reply.get("comparison")
    if card:
        yield card["title"]
        for row in card["rows"]:
            yield f"{row['label']}: {row['value']}. {row['detail']}."


def ground(reply, results, persian):
    """Return (reply, problems). A reply with any ungrounded number becomes SAFE_TEXT."""
    problems = [p for s in _reply_strings(reply) for p in ungrounded_numbers(s, results)]
    if problems:
        return {"text": SAFE_TEXT[persian]}, problems
    return reply, []
