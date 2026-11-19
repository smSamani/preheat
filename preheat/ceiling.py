"""Ceiling grammar: the only code that can turn a message into a proposed maximum.

`analyse(message)` reads one message and returns one of
  Proposal(value)      one affirmative all-day maximum the person typed, on the 0.1 °C grid
  Block(kind, reason)  a clarifying question ("clarify") or a refusal ("decline")
  NoCeiling            the message is not about the all-day maximum

A proposal needs exactly one temperature, one affirmative ceiling clause and no blocker.
Blockers are checked in a fixed order and the first match sets the reason. Where the rules
are unsure the result is a clarification or a refusal, never a proposal. See
docs/language-layer.md for the table.
"""
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

LO, HI = Decimal("21.5"), Decimal("24.0")

_TABLE = {ord(c): d for c, d in zip("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")}
_TABLE.update({ord("٫"): ".", ord("٬"): ",", ord("ي"): "ی", ord("ك"): "ک",
               ord("º"): "°", ord("’"): "'", 0x200C: " ", ord("ۀ"): "ه",
               0x2212: "-", 0x2011: "-", 0x2013: "-", 0x2014: "-"})
_TABLE.update({c: None for c in [*range(0x064B, 0x0660), 0x0670, 0x0640]})   # marks, tatweel


@dataclass(frozen=True)
class Proposal:
    value: float


@dataclass(frozen=True)
class Block:
    kind: str       # "clarify" or "decline"
    reason: str


@dataclass(frozen=True)
class _NoCeiling:
    pass


NoCeiling = _NoCeiling()


def normalise(text):
    """Latin digits, "." as the decimal mark, lower case, single spaces."""
    t = unicodedata.normalize("NFKC", text).translate(_TABLE).lower()
    t = re.sub(r"(?<=\d),(?=\d)", ".", t)
    return re.sub(r"\s+", " ", t).strip()


CLITICS = "شون|تون|مون|ش|ت|م"


def fa(*words, clitic=False):
    """Persian words with letter boundaries (Persian letters count as word characters).

    With clitic=True the word may carry an attached pronoun ("بی‌خیالش"). Only used for cues
    that block a proposal, so accepting more forms can only make the rules more careful.
    """
    tail = "(?:" + CLITICS + ")?" if clitic else ""
    return r"(?<![؀-ۿ])(?:" + "|".join(words) + r")" + tail + r"(?![؀-ۿ])"


def either(english, persian=""):
    return re.compile(english + (("|" + persian) if persian else ""))


CLOCK = re.compile(
    r"(?<!\d)\d{1,2}:\d{2}(?!\d)"
    r"|(?<!\d)\d{1,2}\s*(?:am|pm)(?![a-z])"
    r"|(?<!\d)\d{1,2}\s*o'?clock"
    r"|ساعت\s*\d{1,2}(?:\s*(?:تا|الی|و)\s*\d{1,2})?")

_END = r"(?![a-z\u0600-\u06ff])"
UNIT_F = re.compile(
    r"\s*(?:°\s*)?(?:(?:degrees?|deg\.?)\s*(?:°\s*)?)?(?:fahrenheit|f)" + _END
    + r"|\s*(?:درجه(?: ی)?\s*)?(?:فارنهایت|فارنهیت|فارنهايت)" + _END)
UNIT_K = re.compile(
    r"\s*(?:°\s*)?(?:(?:degrees?|deg\.?)\s*(?:°\s*)?)?(?:kelvins?|k)" + _END
    + r"|\s*(?:درجه(?: ی)?\s*)?کلوین" + _END)
UNIT_C = re.compile(
    r"\s*(?:°\s*)?(?:(?:degrees?|deg\.?)\s*(?:°\s*)?)?(?:celsius|centigrade|c)" + _END
    + r"|\s*(?:°|degrees?|deg\.?)" + _END
    + r"|\s*(?:درجه(?: ی)?\s*)?(?:سانتی ?گراد|سلسیوس)" + _END
    + r"|\s*درجه" + _END)
NOT_A_TEMPERATURE = re.compile(
    r"\s*(?:kwh|kw\b|euros?\b|eur\b|€|%|percent|cents?\b|hours?\b|hrs?\b|h\b|days?\b|minutes?\b|"
    r"mins?\b|houses?\b|homes?\b|rooms?\b|times\b|یورو|درصد|ساعت|روز|دقیقه|کیلووات|سنت|بار)")
NUMBER = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)(?!\d)(?!\.\d)")
SIGN_BEFORE = re.compile(
    r"(?:(?:^|[\s(\[:=,;])-\s{0,2}|(?<![a-z])(?:minus|negative)\s+|(?<![\u0600-\u06ff])منفی\s*)$")
# what may touch a number on either side without being "glued" to it
OPEN_BEFORE = " \t([{:=;,\"'"
OPEN_AFTER = " \t)]}:;,!?.\"'؟"
MAX_TOKEN = 12
SPELLED_VALUE = either(
    r"\btwenty(?:[- ](?:one|two|three|four|five))?\b",
    r"(?<![؀-ۿ])بیست(?: و (?:یک|دو|سه|چهار|پنج))?(?![؀-ۿ])")
PHYSICAL_NOUN = re.compile(
    r"\b(?:electricity|power|energy|kwh|watts?|load|consumption|demand)\b|برق|توان|انرژی|مصرف")
TEMPERATURE_WORD = re.compile(r"temperature|\btemp\b|degrees?\b|°|celsius|درجه|دما|گرما")
MONEY_WORD = re.compile(r"\b(?:cost|price|bill|euros?|money|cents?|saves?|saving|savings|cheap\w*)\b|"
                        r"€|هزینه|قیمت|یورو|پول|صرفه|ارزون")

INCLUSIVE = either(
    r"\b(?:max|maximum|ceiling|cap|capped|capping|limit|upper limit|highest allowed|highest permitted|at most|up to|the most|"
    r"no (?:warmer|hotter|higher) than|"
    r"not (?:above|over|more than|higher than|warmer than|hotter than|beyond|exceeding|exceed\w*))\b",
    r"(?<![؀-ۿ])(?:بیشتر|بالاتر) از \d+(?:\.\d+)?(?: درجه)? (?:نشه|نشود|نره|نرود|نشن|نرن)(?![؀-ۿ])|"
    + fa("حداکثر", "بیشینه", "سقف", "بیشتر نشه", "بیشتر نشود", "بیشتر نره", "بالاتر نره",
       "بالاتر نرود"))
SET_VERB = either(
    r"\b(?:set|try|go with|let it (?:reach|get to|go to|go up to|rise to)|"
    r"(?:ok|okay|fine|happy|comfortable) with|allow(?: it)?(?: to)?)\b",
    fa("بذار", "بگذار", "بزار", "امتحان", "تست کن", "تنظیم کن"))
CHANGE_VERB = either(r"\b(?:change|make|raise|lower|switch|turn|simulate|put|adjust)\b",
                     fa("عوض", "تغییر", "ببر", "کن"))
NEGATION = either(
    r"\b(?:don'?t|do not|never|without changing|forget|nevermind|never mind|cancel|"
    r"scratch that|changed my mind|stop|refus\w*|won'?t|will not|not going to|decline\w*|"
    r"i'?d rather not|no way|not willing|unwilling|do'?nt|reject\w*|not a request|"
    r"isn'?t|aren'?t|wasn'?t|weren'?t)\b|^no\b[,.!]",
    fa("نکن", "نکنید", "نکنین", "نذار", "نذارید", "نذارین", "نگذار", "نگذارید", "نبر", "نبرید",
       "نمیخوام", "نمی خوام", "نمیخواهم", "نمی خواهم", "نمیخوایم", "نمی خوایم", "قبول ندارم",
       "رد می کنم", "رد میکنم", "فراموش", "بیخیال", "بی خیال",
       "منصرف", "ولش کن", "دست نزن", "دست نزنید", "دست نکش", "دست نکشید",
       "قبول نمی کنم", "قبول نمیکنم", "قبول نمی کنیم", "پیشنهاد نیست", "تغییر نده",
       "تغییر ندید", "تغییر ندین", "نده", "ندید", "ندین", clitic=True))
FLOOR = either(
    r"\b(?:min|minimum|floor|at least|lowest|nights?|overnight|set-?back|set back|off|"
    r"(?:no|not) (?:colder|cooler|lower|less) than|not (?:below|under))\b",
    fa("حداقل", "کمینه", "کمترین", "کف", "شب", "شبها", "شبا", "خاموش", clitic=True))
TIME_LIMIT = either(
    r"\b(?:only|until|till|during|before|after|after work|(?:in|at) the (?:evening|morning|afternoon)s?|"
    r"evenings?|mornings?|afternoons?|tonight|today|tomorrow|this (?:evening|morning|afternoon|night|"
    r"weekend|week)|for now|right now|for the moment|temporar\w+|for the (?:next|rest)|"
    r"for (?:an?|\d+) (?:hours?|days?|weeks?|months?)|just for|weeks?|weekends?|weekdays?|months?|"
    r"(?:mon|tues|wednes|thurs|fri|satur|sun)days?)\b",
    fa("فقط", "عصر", "عصرها", "صبح", "صبحها", "ظهر", "بعدازظهر", "بعد از ظهر", "امشب", "امروز", "فردا",
       "الان", "همین الان", "همین عصر", "همین صبح", "همین امشب", "این عصر", "این صبح", "این هفته",
       "آخر هفته", "موقتا", "موقت", "فعلا", "برای الان", "هفته", "ماه",
       "دوشنبه", "سه شنبه", "چهارشنبه", "پنجشنبه", "پنج شنبه", "جمعه", "شنبه", "یکشنبه", "یک شنبه",
       "هفته ها", "ماه ها", clitic=True)
    + r"|(?<![؀-ۿ])(?:دوشنبه|سه شنبه|چهارشنبه|پنج ?شنبه|جمعه|شنبه|یک ?شنبه)(?: ?ها)?(?![؀-ۿ])")
STRICT = either(r"\b(?:below|under|beneath|less than|lower than|fewer than)\b",
                fa("کمتر از", "زیر", "پایین تر از", clitic=True))
TARGET = either(r"\bkeep(?: \w+){0,3} at\b(?! most)|\b(?:hold|stay|maintain|exactly|target)\b",
                fa("نگه دار", "ثابت", "دقیقا", clitic=True))
ASKING = either(
    r"\b(?:tell me|let me know|can you tell|could you tell|would you tell|whether|wonder\w*|"
    r"curious|check (?:if|whether)|see if|find out)\b",
    r"هست یا نه|هستش یا نه|(?<![؀-ۿ])یا نه(?![؀-ۿ])|(?<![؀-ۿ])بگو(?:ید|یین)?(?![؀-ۿ]).*(?<![؀-ۿ])هست|"
    r"(?<![؀-ۿ])ببین(?:ید)?(?![؀-ۿ])")
QUESTION_START = either(
    r"^(?:would|does|do|did|is|are|was|can|could|will|should|what|whats|what's|how|why|when|which|"
    r"who|if)\b",
    r"^(?:آیا|چقدر|چی|چه|چرا|چطور|چجور|اگه|اگر|کی|کدوم)(?![؀-ۿ])")
MONEY = re.compile(r"cost|price|bill|euro|€|cents?\b|kwh|electric|sav(?:e|ing)|money|cheap|"
                   r"هزینه|قیمت|برق|یورو|پول|صرفه|ارزون")
RANGE = re.compile(r"\bbetween\b|(?<![\u0600-\u06ff])بین(?![\u0600-\u06ff])")
INSULATION = re.compile(r"insulat|عایق")
HALF = either(r"(?<=\d) and (?:a )?(?:half|quarter)\b", r"(?<=\d) و (?:نیم|ربع)")
SPELLED = either(
    r"\b(?:twenty|twenty[- ](?:one|two|three|four)|twenty\s*(?:one|two|three|four)|"
    r"a half|and a half|half)\b",
    "بیست|نیم")
WARMER = either(
    r"\b(?:warmer|hotter|cosier|cozier|warm(?:ing)? it up|turn(?:ed)? (?:it |the heat |the heating )?up|"
    r"raise|increase|higher)\b",
    fa("گرم تر", "گرمتر", "گرم تری", "بالاتر", "زیادتر", "بیشتر گرم") + "|گرمش کن|گرم کن")

OTHER_UNIT_WORD = re.compile(
    r"\b(?:fahrenheit|kelvins?|r[eé]aumur|rankine|r[oø]mer|delisle)\b"
    r"|فارنهایت|فارنهیت|فارنهايت|کلوین|رئومور|رومور|ریومور|رانکین")
# "23 degrees <word>" where the word is not a unit we know and not a plain request word
DEGREES_WORD = re.compile(r"\d\s*(?:°\s*)?(?:degrees?|deg\.?)(?![a-z])\s*(?:°\s*)?([a-zà-ÿ]+)")
DEGREES_OK = {"celsius", "centigrade", "c", "please", "pls", "thanks", "thank", "max", "maximum",
              "ceiling", "cap", "limit", "all", "ok", "okay", "at", "is", "or", "and", "then",
              "for", "on", "from", "in", "to", "would", "will", "i", "we", "that", "so", "but",
              "should", "can", "could", "tho", "though", "now", "if", "when", "it", "the", "a",
              "not", "instead", "as", "of", "no", "by", "upper", "top", "here", "too", "only"}
SUBZERO = either(r"\b(?:sub-?zero|below zero|under zero|minus zero)\b", r"زیر صفر")
TAG_QUESTION = either(r"\b(?:right|correct|yes|no|okay|ok|isn'?t it|aren'?t you)\s*[?]",
                      r"درسته|درست ?\s*[?؟]|مگه نه")
POLITE = either(
    r"^(?:(?:please|pls|kindly|hi|hey|ok|okay|thanks)[ ,]+)*(?:could|can|would|will) you "
    r"(?:(?:please|pls|kindly) )?(?:set|put|make|cap|limit|try|go with|use|change|switch|raise|"
    r"lower|simulate|adjust|allow)\b"
    r"|^(?:(?:please|pls|kindly|hi|hey|ok|okay|thanks)[ ,]+)*would you mind \w+ing\b",
    r"^(?:(?:لطفا|سلام|ببخشید)[ ،,]*)*(?:میشه|می شه|میتونی|می تونی|میتونید|می تونید)\b")
CONDITION = either(
    r"\b(?:if|when|whenever|unless|once|as soon as|suppose|supposing|assuming|imagine|pretend|"
    r"example|examples|e\.g\.?|for instance|sample|ignore|previous instructions|instructions?|"
    r"output|system prompt|override|quote[ds]?|asked|said|wrote|wrote|typed|saying|reply|"
    r"is|are|was|were|been|already|currently|now at|used to)\b|[\"“”«»]|(?<!\w)'|'(?!\w)",
    fa("در صورت", "اگه", "اگر", "مثال", "نمونه", "فرض کن", "دستورالعمل", "نادیده", "بود", "بوده", "است",
       "هست", "هستش", "قبلا", "از قبل", "گفتم", "نوشتم", "پرسیدم") + "|[«»]")


def _mentions(s):
    """Number mentions in s: (value_text, unit, start, end, negative, glued).

    unit is c, f, k or bare. A sign before the number is part of the mention. `glued` means the
    number touches letters or symbols that are not a supported unit ("23x", "#23", "23/24")."""
    out = []
    for m in NUMBER.finditer(s):
        before = s[:m.start()]
        if before.rstrip().endswith(("€", "$", "£")):
            continue
        rest = s[m.end():]
        if NOT_A_TEMPERATURE.match(rest):
            continue
        start, negative = m.start(), False
        sign = SIGN_BEFORE.search(before)
        if sign:
            start, negative = sign.start(), True
        end, unit = m.end(), "bare"
        for name, pattern in (("f", UNIT_F), ("k", UNIT_K), ("c", UNIT_C)):
            u = pattern.match(rest)
            if u:
                end, unit = m.end() + u.end(), name
                break
        glued_before = bool(before) and before[-1] not in OPEN_BEFORE and not sign
        after = s[end:end + 1]
        glued_after = bool(after) and after not in OPEN_AFTER
        out.append((m.group(1), unit, start, end, negative, glued_before or glued_after))
    return out


def _value(text):
    """Decimal of a numeric token, or None when the token is too long to accept."""
    return None if len(text) > MAX_TOKEN else Decimal(text)


def _consumed_bounds(s):
    """Hide "not above 22"-style phrases so the word "not" is not read as a negation."""
    return re.sub(r"\bnot (?:above|over|more than|higher than|warmer than|hotter than|beyond|"
                  r"exceeding|exceed\w*)\b", " bound ", s)


def _is_question(s):
    """A question mark anywhere, a question opener, or a tag question. A polite request
    ("could you set the maximum to 23?") with one closing question mark is a request."""
    marks = len(re.findall(r"[?؟]", s))
    polite = bool(POLITE.search(s)) and (
        marks == 0 or (marks == 1 and bool(re.search(r"[?؟]\s*[.!)\"']*$", s))))
    if polite:
        return bool(TAG_QUESTION.search(s))
    return bool(marks or QUESTION_START.search(s) or TAG_QUESTION.search(s))


def block(kind, reason):
    return Block(kind, reason)


def analyse(raw):
    m = normalise(raw)
    s = CLOCK.sub(" ", m)
    has_clock = s != m
    mentions = _mentions(s)
    inclusive = bool(INCLUSIVE.search(s))
    set_verb = bool(SET_VERB.search(s))
    negated = bool(NEGATION.search(_consumed_bounds(s)))
    floor = bool(FLOOR.search(s))
    timed = has_clock or bool(TIME_LIMIT.search(m))
    strict = bool(STRICT.search(s))
    target = bool(TARGET.search(s))
    question = _is_question(s) or bool(ASKING.search(s))
    money = bool(MONEY.search(s))
    spelled_values = len(SPELLED_VALUE.findall(s))

    explicit = [t for t in mentions if t[1] != "bare"]
    residual = s
    for t in sorted(mentions, key=lambda t: -t[2]):
        residual = residual[:t[2]] + residual[t[3]:]
    only_number = len(mentions) == 1 and not re.sub(r"[\s.,!:;°-]", "", residual)
    cue = (inclusive or set_verb or negated or floor or timed or strict or target
           or bool(CHANGE_VERB.search(s)) or bool(RANGE.search(s)))

    def plausible(t):
        value = _value(t[0])
        if t[4] or value is None:
            return True                      # a signed or oversize number is never dropped
        return 10 <= value <= 45 or ((cue or only_number) and 0 < value <= 100)

    bare = [t for t in mentions if t[1] == "bare" and plausible(t)]
    noun_cue = bool(PHYSICAL_NOUN.search(s) or MONEY_WORD.search(s)) and not TEMPERATURE_WORD.search(s)
    if not explicit and not (cue or question or only_number or noun_cue):
        bare = []
    temps = explicit + bare

    if not temps:
        return _without_number(s, inclusive, set_verb, question, money, floor)

    if negated:
        return block("decline", "negated_action")
    if floor:
        return block("decline", "unsupported_floor")
    if timed:
        return block("decline", "time_limited")
    if any(t[1] in ("f", "k") for t in temps) or OTHER_UNIT_WORD.search(s):
        return block("clarify", "unit")
    if SUBZERO.search(s):
        return block("clarify", "out_of_range")
    if _unknown_degrees_word(s):
        return block("clarify", "unit")
    if len(temps) > 1 or len(mentions) > 1 or spelled_values:
        return block("clarify", "several_values")
    if temps[0][4]:
        return block("clarify", "out_of_range")
    if temps[0][5]:
        letters = re.match(r"[a-z\u0600-\u06ff]", s[temps[0][3]:temps[0][3] + 1])
        return block("clarify", "unit" if letters else "target_or_ceiling")
    if strict:
        return block("clarify", "strict_bound")
    if target:
        return block("clarify", "target_or_ceiling")
    if PHYSICAL_NOUN.search(s) and not TEMPERATURE_WORD.search(s):
        return block("clarify", "question_with_value" if (question or money_word(s))
                     else "target_or_ceiling")
    if question:
        return block("clarify", "question_with_value")
    if HALF.search(s):
        return block("clarify", "type_one_value")

    text = temps[0][0]
    value = _value(text)
    if value is None:
        return block("clarify", "precision" if "." in text and len(text.split(".")[0]) <= 6
                     else "out_of_range")
    if not LO <= value <= HI:
        return block("clarify", "out_of_range")
    if value != value.quantize(Decimal("0.1")):
        return block("clarify", "precision")

    if inclusive or only_number or (set_verb and not money):
        if _complete_request(s, temps[0]):
            return Proposal(float(value))
        # a cue and one number, but not a whole request: ask, never propose
        return block("clarify", "question_with_value" if _quoted_or_conditional(s)
                     else "target_or_ceiling")
    if money:
        return block("clarify", "question_with_value")
    if explicit or bool(CHANGE_VERB.search(s)):
        return block("clarify", "question_with_value" if FA_COPULA.search(s) else "target_or_ceiling")
    return NoCeiling


def _unknown_degrees_word(s):
    """"<n> degrees <word>" where the word is neither Celsius nor a plain request word."""
    return any(m.group(1) not in DEGREES_OK for m in DEGREES_WORD.finditer(s))


QUOTE = re.compile(r"[\"“”«»]|(?<!\w)'|'(?!\w)")


# Persian copula glued to the word ("حداکثره", "سقفه", "دماست") or loose ("درجه‌ست")
FA_COPULA = re.compile(r"(?<![؀-ۿ])(?:حداکثر|سقف|بیشینه|دما)(?:ه|ست)(?![؀-ۿ])|(?<![؀-ۿ])(?:ست|س)(?![؀-ۿ])")


def _quoted_or_conditional(s):
    return bool(QUOTE.search(s) or CONDITION.search(s) or FA_COPULA.search(s))


# --- The closed whitelist of complete requests ----------------------------------------------
# A proposal is only made when, after removing a closed list of filler words, the whole message
# is one of the templates below around the single typed temperature (written N). Anything else
# with a number in it is a question to the person, never a proposal.

_PROTECT = [
    (r"\blet it (?:reach|get to|go up to|go to|rise to|rise)\b", " LETIT "),
    (r"\bup to\b", " UPTO "),
    (r"\bat most\b", " ATMOST "),
    (r"\bis the most i(?:'d| would)? (?:want|need)\b", " MOSTIWANT "),
    (r"\bno (?:warmer|hotter|higher) than\b", " NOWARMER "),
    (r"\bnot (?:above|over|more than)\b", " NOTABOVE "),
    (r"\b(?:i'?m |i am )?(?:ok|okay|fine|happy) with\b", " OKWITH "),
    (r"\bgo with\b", " GOWITH "),
    (r"\bupper limit\b", " limit "),
    (r"\b(?:highest|maximum) (?:allowed|permitted|allowable)(?: indoor)?(?: temperature)?\b", " max "),
]
# Only words that carry no subject or tense. Subject words (we, you, they, i, it ...) and
# Persian past or indicative verbs are never dropped, so a statement cannot match a template.
_FILLER_EN = ["thank you", "thanks", "please", "pls", "kindly", "okay", "ok", "hi", "hey",
              "the", "a", "an", "for the whole day", "for the entire day", "for all day",
              "for the day", "entire-day", "whole-day", "full-day", "all day", "all-day", "whole day", "entire day", "throughout the day",
              "indoors", "indoor", "temperatures", "temperature", "temps", "temp", "house", "home",
              "room"]
_FILLER_FA = ["لطفا", "ممنون", "مرسی", "سلام", "برای تمام طول روز", "در تمام طول روز", "برای تمام روز",
              "تمام طول روز", "برای کل روز", "در کل روز", "برای همه روز",
              "در همه روز", "کل روز", "همه روز", "تمام روز", "دمای", "دما", "داخل", "داخلی", "خونه",
              "خانه", "اتاق"]
_FILLER = re.compile(
    "(?<![a-z'])(?:" + "|".join(sorted(map(re.escape, _FILLER_EN), key=len, reverse=True))
    + ")(?![a-z'])|(?<![؀-ۿ])(?:" + "|".join(sorted(map(re.escape, _FILLER_FA), key=len, reverse=True))
    + ")(?![؀-ۿ])")

# Politeness and modality are accepted only here, as an explicit request opener at the start.
_LEAD_EN = r"(?:(?:please|pls|kindly|hi|hey|ok|okay|thanks|thank you)[ ,]+)*"
_MIND_VERB = {"setting": "set", "putting": "put", "making": "make", "capping": "cap",
              "limiting": "limit", "trying": "try", "using": "use", "changing": "change",
              "switching": "switch", "raising": "raise", "lowering": "lower",
              "simulating": "simulate", "adjusting": "adjust", "allowing": "allow"}
_MIND = re.compile(r"^would you mind (" + "|".join(_MIND_VERB) + r")\b")
_OPEN_EN = re.compile(
    r"^" + _LEAD_EN + r"(?:(?:could|can|would|will) you(?: (?:please|pls|kindly))?"
    r"|(?:i'?d|i would|i) (?:like|want)(?: you)?(?: to)?|let'?s)\s+")
_LEAD_FA = r"(?:(?:لطفا|سلام|ببخشید|ممنون|خواهش می کنم)[ ،,]*)*"
_OPEN_FA = re.compile(r"^" + _LEAD_FA + r"(?:(?:میشه|می شه|میتونی|می تونی|میتونید|می تونید)\s+)?")
_TAIL = re.compile(r"\s+(?:please|pls|kindly|thanks|thank you|لطفا|ممنون|مرسی)$")


def _strip_openers(t):
    """Remove one explicit request opener (and a trailing please) from the start or end."""
    t = t.strip()
    t = re.sub(r"^" + _LEAD_EN, "", t)
    mind = _MIND.match(t)
    if mind:
        t = _MIND_VERB[mind.group(1)] + t[mind.end():]
    else:
        t = _OPEN_EN.sub("", t, count=1)
    t = re.sub(r"^(?:(?:please|pls|kindly)\s+)+", "", t)
    t = _OPEN_FA.sub("", t, count=1)
    return _TAIL.sub("", t)


_OBJ = r"(?:max|maximum|ceiling|cap|limit)"
_VERB = (r"(?:set|put|make|cap|limit|try|change|switch|raise|lower|simulate|adjust|allow|use|keep|"
         r"enforce|impose)")
_PREP = r"(?:to be|to|at|of|on|as|be|=)"
_FA_OBJ = r"(?:سقف|حداکثر|بیشینه)"
_FA_RA = r"(?:را|رو)"
_FA_PREP = r"(?:به|روی|رو)"
_FA_VERB = (r"(?:بذار|بگذار|بزار|تنظیم کن|کن|بکن|بذارید|بگذارید|بزارید|بذارین|بزارین|بذاری|بگذاری|"
            r"بزاری|تنظیم کنید|باشه|باشد|بشه|قرار بده|قرار بدید|قرار بدین|تعیین کن|تعیین کنید|تعیین کنین)")
_FA_IMP = (r"(?:بذار|بگذار|بزار|تنظیم کن|بکن|بذارید|بگذارید|بزارید|بذارین|بزارین|تنظیم کنید|"
           r"قرار بده|قرار بدید)")
_TEMPLATES = [re.compile("^(?:" + t + ")$") for t in (
    rf"(?:{_VERB} )?{_OBJ}(?: {_PREP})? N",
    rf"(?:{_VERB} )?{_OBJ} (?:NOTABOVE|NOWARMER|UPTO|ATMOST) N",
    r"(?:allow )?(?:UPTO|ATMOST|NOWARMER|NOTABOVE) N",
    rf"(?:{_VERB} )?N {_OBJ}",
    rf"(?:use|set|keep) N as {_OBJ}",
    rf"(?:cap|limit) it(?: {_PREP})? N",
    r"N ATMOST", r"N MOSTIWANT",
    r"LETIT N", r"try N", r"GOWITH N", r"OKWITH N", r"N",
    rf"{_FA_OBJ}(?: {_FA_RA})?(?: {_FA_PREP})? N(?: {_FA_VERB})?",
    rf"{_FA_OBJ}(?: {_FA_RA})? {_FA_VERB}(?: {_FA_PREP})? N",
    rf"N {_FA_OBJ}(?: {_FA_VERB})?",
    rf"(?:(?:بیشتر|بالاتر) از N|از N (?:بیشتر|بالاتر)) (?:نشه|نشود|نره|نرود|نشن|نرن)",
    rf"امتحان کن N", rf"N(?: {_FA_RA})? امتحان کن",
    rf"{_FA_IMP} {_FA_OBJ}(?: {_FA_RA})?(?: {_FA_PREP})? N",
    rf"{_FA_OBJ}(?: {_FA_RA})? نباید از N (?:بیشتر|بالاتر) (?:شود|بشه|بره|برود|بشود)",
)]


def _complete_request(s, mention):
    """True when s is, in full, one of the whitelisted requests around the given mention."""
    if QUOTE.search(s):
        return False
    t = " " + s[:mention[2]] + " N " + s[mention[3]:] + " "
    for pattern, token in _PROTECT:
        t = re.sub(pattern, token, t)
    t = re.sub(r"=", " = ", t)
    t = re.sub(r"[.,!?;:()\[\]،؛؟]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = _strip_openers(t)
    t = _FILLER.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return any(p.match(t) for p in _TEMPLATES)


def money_word(s):
    return bool(MONEY_WORD.search(s))


def _without_number(s, inclusive, set_verb, question, money, floor):
    if (inclusive or set_verb) and SPELLED.search(s) and not question:
        return block("clarify", "type_one_value")
    if (WARMER.search(s) and not question and not money and not floor
            and not INSULATION.search(s) and not NEGATION.search(s)):
        return block("clarify", "type_one_value")
    return NoCeiling
