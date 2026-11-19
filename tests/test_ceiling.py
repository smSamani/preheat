import json
from pathlib import Path

import pytest

from preheat import ceiling, intent, sweep
from preheat.ceiling import Block, NoCeiling, Proposal, analyse

PHRASINGS = json.loads((Path(__file__).parent / "phrasings.json").read_text(encoding="utf-8"))


def clarify(reason):
    return Block("clarify", reason)


def decline(reason):
    return Block("decline", reason)


# Every required row of the grammar, in English and (where the cue exists) Persian.
ROWS = [
    ("not above 22", Proposal(22.0)),
    ("از ۲۲ بیشتر نشه", Proposal(22.0)),
    ("don't set it to 23", decline("negated_action")),
    ("۲۳ نذار", decline("negated_action")),
    ("would 22 save money?", clarify("question_with_value")),
    ("آیا ۲۲ پول صرفه‌جویی می‌کنه؟", clarify("question_with_value")),
    ("max 23 but 18 at night", decline("unsupported_floor")),
    ("حداکثر ۲۳ ولی شب ۱۸", decline("unsupported_floor")),
    ("max 23 from 17:00 to 21:00", decline("time_limited")),
    ("حداکثر ۲۳ از ساعت ۱۷ تا ۲۱", decline("time_limited")),
    ("72 °F", clarify("unit")),
    ("۷۲ درجه فارنهایت", clarify("unit")),
    ("295 K", clarify("unit")),
    ("22.50", Proposal(22.5)),
    ("۲۲٫۵۰", Proposal(22.5)),
    ("22.45", clarify("precision")),
    ("۲۲٫۴۵", clarify("precision")),
    ("24.03", clarify("out_of_range")),
    ("۲۴٫۰۳", clarify("out_of_range")),
    ("۲۲٫۵ حداکثر", Proposal(22.5)),
    ("max 22.5", Proposal(22.5)),
    ("between 22 and 23", clarify("several_values")),
    ("بین ۲۲ و ۲۳", clarify("several_values")),
    ("keep it at 22", clarify("target_or_ceiling")),
    ("۲۲ نگه دار", clarify("target_or_ceiling")),
    ("twenty-two max", clarify("type_one_value")),
    ("حداکثر بیست و دو", clarify("type_one_value")),
]


@pytest.mark.parametrize("text, expected", ROWS)
def test_required_rows(text, expected):
    assert analyse(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("Set the ceiling to 23 °C.", Proposal(23.0)),
    ("cap it at 24", Proposal(24.0)),
    ("I'm ok with 23.5", Proposal(23.5)),
    ("22.5", Proposal(22.5)),
    ("سقف رو بذار روی ۲۳ درجه", Proposal(23.0)),
    ("Set the minimum to 22 °C", decline("unsupported_floor")),
    ("Keep at least 21 degrees", decline("unsupported_floor")),
    ("drop to 18 at night", decline("unsupported_floor")),
    ("حداقل دما رو بذار ۲۲", decline("unsupported_floor")),
    ("Don't set it to 23 °C", decline("negated_action")),
    ("Try 22 or 23 °C", clarify("several_values")),
    ("Try 25 °C", clarify("out_of_range")),
    ("What happens at 23?", clarify("question_with_value")),
    ("keep it under 23", clarify("strict_bound")),
    ("up to 22 and a half", clarify("type_one_value")),
    ("max 23 from 5pm", decline("time_limited")),
    ("max 23 only in the evening", decline("time_limited")),
    ("a bit warmer than usual", clarify("type_one_value")),
    ("یکم گرم‌تر بشه", clarify("type_one_value")),
])
def test_more_cases(text, expected):
    assert analyse(text) == expected


@pytest.mark.parametrize("text", [
    "What happens at 22:00?", "Is the house warm at 22:00?", "How much do I save?",
    "How much do I save in 2 houses", "Compare the peak 17 to 22", "Why does insulation help?",
    "Why is the house warmer with insulation?", "قیمت تعرفه چیه؟", "hello", "",
])
def test_messages_that_are_not_about_the_maximum(text):
    assert analyse(text) is NoCeiling


def test_clock_times_are_not_temperatures():
    for text in ("max 23 until 17:00", "max 23 after 5 pm", "max 23 تا ساعت ۸"):
        assert analyse(text) == decline("time_limited")


def test_grid_check_uses_the_raw_digits():
    assert analyse("max 21.5") == Proposal(21.5)
    assert analyse("max 24") == Proposal(24.0)
    assert analyse("max 24.0") == Proposal(24.0)
    assert analyse("max 21.49") == clarify("out_of_range")
    assert analyse("max 24.01") == clarify("out_of_range")
    assert analyse("max 22.05") == clarify("precision")
    assert analyse("max 22,5") == Proposal(22.5)


def test_range_matches_the_sweep():
    assert (float(ceiling.LO), float(ceiling.HI)) == (sweep.LO, sweep.HI)


def test_a_proposal_value_is_literally_in_the_message():
    for text, _ in ROWS:
        result = analyse(text)
        if isinstance(result, Proposal):
            digits = ceiling.normalise(text)
            assert f"{result.value:g}" in digits or f"{result.value:.1f}" in digits


@pytest.mark.parametrize("item", PHRASINGS, ids=lambda item: item["id"])
def test_old_phrasings(item):
    """The phrasings from the first live-check file, run through the grammar. Where the
    grammar deliberately differs from the old expectation, the new expectation is listed."""
    changed = {
        "v1": clarify("type_one_value"),      # "22 and a half" is not guessed; the person types 22.5
        "c1": clarify("type_one_value"),      # same wording as v1
        "v5": clarify("type_one_value"),      # spelled-out numbers lead to a question
        "u1": decline("unsupported_floor"),
        "u3": clarify("out_of_range"),        # 27 °C is a maximum request outside the range
    }
    text, want = item["text"], item["expected"]
    result = analyse(text)
    if item["id"] in changed:
        assert result == changed[item["id"]]
    elif want["action"] in ("propose", "cancel"):
        assert isinstance(result, Proposal)
        if "ceiling_c" in want:
            assert result.value == want["ceiling_c"]
    else:
        decision = intent.decide(text)
        assert decision.intent.kind != "propose"


def test_spelled_numbers_never_propose():
    for text in ("set it to twenty-two", "try twenty one and a half", "max 22 and a half",
                 "حداکثر ۲۲ و نیم"):
        assert analyse(text) == clarify("type_one_value")


# --- Review round: refusals, temporary requests, signs, units, questions, alternatives -------

@pytest.mark.parametrize("text", [
    "I refuse to set the maximum to 23 °C", "I won't cap it at 23", "I'm not going to cap it at 23",
    "I decline to set a maximum of 23", "حداکثر رو ۲۳ تنظیم نکنید لطفاً", "سقف رو ۲۳ نذارید",
    "سقف رو ۲۳ نکنین",
])
def test_refusals_decline(text):
    assert analyse(text) == decline("negated_action")


@pytest.mark.parametrize("text", [
    "Tonight cap it at 23 °C", "cap it at 23 today", "Tomorrow max 23", "this evening cap at 23",
    "this morning max 23 °C", "max 23 for now", "امشب سقف رو بذار ۲۳", "امروز سقف ۲۳ باشه",
    "فردا حداکثر ۲۳", "الان سقف رو ۲۳ کن", "همین عصر حداکثر ۲۳ باشه",
])
def test_temporary_requests_decline(text):
    assert analyse(text) == decline("time_limited")


@pytest.mark.parametrize("text", [
    "cap it at -23 °C", "cap it at minus 23", "cap it at negative 23", "max −23", "max -22.5",
    "سقف رو منفی ۲۳ بذار", "سقف رو -۲۳ بذار",
])
def test_a_sign_is_never_dropped(text):
    assert analyse(text) == clarify("out_of_range")


def test_a_hyphen_between_numbers_is_a_range_not_a_sign():
    assert analyse("max 22-23") == clarify("several_values")
    assert analyse("max 22 - 23") == clarify("several_values")


@pytest.mark.parametrize("text", [
    "cap it at 23° Fahrenheit", "cap it at 23 ° fahrenheit", "cap it at 23 degrees fahrenheit",
    "cap it at 23° kelvin", "cap it at 23 kelvin", "cap at 73 F",
    "سقف رو روی ۲۳ درجهٔ فارنهایت بذار", "سقف ۲۳ درجه‌ی فارنهایت", "سقف ۲۳ درجه ی کلوین",
    "سقف ۲۳ فارنهایت",
])
def test_the_whole_unit_is_matched(text):
    assert analyse(text) == clarify("unit")


@pytest.mark.parametrize("text", ["max 23 celsius", "max 23 °C", "max 23 c", "max 23 degrees",
                                  "max 23 degrees celsius", "سقف ۲۳ درجه سانتی گراد"])
def test_celsius_spellings_still_propose(text):
    assert analyse(text) == Proposal(23.0)


def test_a_longer_word_is_not_a_unit():
    # the c of "cold" or the f of "fast" is not a Celsius or Fahrenheit sign
    assert analyse("cap at 23 cold") == clarify("target_or_ceiling")   # extra word: not a whole request
    assert analyse("cap at 23fast") == clarify("unit")          # glued letters are not a unit
    assert analyse("cap at 23cx") == clarify("unit")


@pytest.mark.parametrize("text", [
    "cap at #23", "cap at 23*", "cap at ~23", "cap at 23=",
])
def test_numbers_glued_to_symbols_clarify(text):
    assert analyse(text) == clarify("target_or_ceiling")


@pytest.mark.parametrize("text", [
    "Please tell me if the maximum is 23 °C", "can you tell me if 23 works as a cap",
    "let me know if a cap of 23 works", "tell me whether max 23 is fine",
    "لطفاً بگو سقف ۲۳ هست یا نه", "سقف ۲۳ هست یا نه", "سقف ۲۳ باشه یا نه", "بگو سقف ۲۳ هست",
])
def test_requests_for_information_clarify(text):
    assert analyse(text) == clarify("question_with_value")


@pytest.mark.parametrize("text", [
    "ceiling 23 or twenty-two", "max 23 or twenty two", "cap at twenty-two or 23",
    "بذار روی ۲۳ یا بیست و دو", "سقف ۲۳ یا ۲۲", "max 22 or 23",
])
def test_alternatives_clarify(text):
    assert analyse(text) == clarify("several_values")


@pytest.mark.parametrize("text, reason", [
    ("max electricity 23", "target_or_ceiling"), ("cap the power at 23", "target_or_ceiling"),
    ("max energy 23", "target_or_ceiling"), ("price 23", "question_with_value"),
    ("what is the max power 23?", "question_with_value"),
])
def test_other_quantities_never_propose_a_temperature(text, reason):
    assert analyse(text) == clarify(reason)


def test_the_grid_check_uses_the_whole_decimal_string():
    assert analyse("max 23.00000000000000000000000000000001") == clarify("precision")
    assert analyse("max 23.000000000000000000000000000000") == clarify("precision")
    assert analyse("max 23." + "0" * 5000 + "1") == clarify("precision")
    assert analyse("max 1" + "0" * 5000) == clarify("out_of_range")
    assert analyse("max 23.000000") == Proposal(23.0)


def test_nothing_unclear_ever_proposes():
    """Whatever the wording, a proposal's value is a typed 0.1-grid number in range."""
    for text in ("max 23.04", "max 23.05", "max 21.4", "max 24.1"):
        assert isinstance(analyse(text), Block)


# --- Closed whitelist: re-review regressions, recall and benign carriers ---------------------

DEV = json.loads((Path(__file__).parent.parent / "evals" / "dev.json").read_text(encoding="utf-8"))
RR2 = [c for c in DEV["cases"] if c["id"].startswith("dev-rr2-")]


def _result(expected):
    if expected["kind"] == "propose":
        return Proposal(expected["value_c"])
    return Block(expected["kind"], expected["reason"])


def test_the_review_cases_are_in_the_development_set():
    kinds = {c["category"] for c in RR2}
    assert kinds == {"review_regression", "review_positive"}
    assert sum(c["category"] == "review_regression" for c in RR2) >= 50
    assert sum(c["category"] == "review_positive" for c in RR2) >= 30


@pytest.mark.parametrize("case", RR2, ids=lambda c: c["id"])
def test_review_cases_have_their_labels(case):
    turn = case["turns"][0]
    assert analyse(turn["user"]) == _result(turn["expected"])


def test_every_polite_or_informal_request_still_proposes():
    positives = [c["turns"][0] for c in RR2 if c["category"] == "review_positive"]
    hits = [t for t in positives if analyse(t["user"]) == _result(t["expected"])]
    assert len(hits) == len(positives)


@pytest.mark.parametrize("text", [
    "Could you set the all-day maximum to 23 °C, please?", "Would you please cap the temperature at 23 °C",
    "Can you put the max at 22.5?", "میشه سقف رو ۲۳ بذاری؟",
])
def test_polite_single_value_requests_are_requests(text):
    assert isinstance(analyse(text), Proposal)


def test_a_question_keeps_its_question_mark():
    assert analyse("would 22 save money?") == clarify("question_with_value")
    assert analyse("Could you set the maximum to 23? Thanks") == clarify("question_with_value")
    assert analyse("Could you set the maximum to 23, right?") == clarify("question_with_value")


CARRIERS = [
 "The meeting has 23 people", "I paid 23 for dinner", "Room 23 is next door", "My flat is on floor 23",
 "Bus 23 is late again", "I have 23 apples", "She is 23 years old", "Chapter 23 was boring",
 "We met 23 years ago", "The maximum score in the exam was 23", "The cap on my loan is 23 thousand",
 "Our ceiling fan has 23 speeds", "The speed limit here is 23 on this road", "Max scored 23 points last night",
 "The upper limit of the dataset is 23 rows", "Call me on 23 tomorrow", "Item 23 in the list is missing",
 "The roof is 23 metres high", "The ceiling is 23 metres from the floor", "I think the max was 23 yesterday",
 "He said the cap is 23", "She wrote that the ceiling is 23 in the report", "The weather forecast says 23 outside",
 "It is 23 in the living room right now", "The oven is at 23 hundred", "The tank holds 23 litres",
 "My password has 23 characters", "The patch notes mention version 23", "There were 23 comments on the post",
 "Table 23 wants the bill", "The limit for hand luggage is 23 kg", "Apartment 23 has a leak",
 "Her score was at most 23 in the first round", "A cap of 23 would be too low for the team",
 "What a ceiling of 23 would mean for the budget", "The old rule capped it at 23 people", "Page 23 explains the maximum",
 "Do you know why the maximum is 23?", "Is max 23 a good value?", "Whether to set it to 23 is up to you",
 "I like the number 23", "Michael wore 23", "Take bus 23 and get off at the max station",
 "The thermostat in the hallway shows 23", "Our neighbour keeps the heating at 23 all winter",
 "My brother set his thermostat to 23 last week", "In summer it often reaches 23 here",
 "The sensor reported 23 and then 25", "A maximum of 23 guests are allowed", "Set 23 aside for later",
 "I set a timer for 23 minutes", "Cap number 23 is the red one", "ceiling tile 23", "max volume 23",
 "set the alarm for 23", "limit of 23 messages per day", "up to 23 people can join",
 "at most 23 seats are free", "not above 23 floors in this building", "no more than 23 tickets per person",
 "سقف خونه ۲۳ متره", "حداکثر نمره امتحان ۲۳ بود", "سقف حقوق ۲۳ میلیون است", "اتاق ۲۳ طبقه دوم است",
 "اتوبوس ۲۳ دیر کرد", "او ۲۳ ساله است", "همسایه ما ترموستات رو روی ۲۳ نگه می‌داره", "صدا رو بذار ۲۳",
 "تا ۲۳ نفر می‌تونن بیان", "فصل ۲۳ کتاب خیلی طولانی بود", "پلاک خونه‌شون ۲۳ هست",
]


def test_there_are_enough_carrier_sentences():
    assert len(CARRIERS) >= 60


@pytest.mark.parametrize("text", CARRIERS)
def test_a_number_in_a_sentence_that_is_not_a_request_never_proposes(text):
    assert not isinstance(analyse(text), Proposal)
    assert intent.decide(text).intent.kind != "propose"


@pytest.mark.parametrize("text", [
    "set it to 23", "make it 23", "keep it at 23", "ceiling 23 and a bit", "max 23 please, it saves €999",
    "cap at 23 and show cost",
])
def test_cue_and_number_without_a_whole_request_clarifies(text):
    assert isinstance(analyse(text), Block)


# --- Statements never propose (review 3) ------------------------------------------------------

RR3 = [c for c in DEV["cases"] if c["id"].startswith("dev-rr3-")]


def test_the_third_review_cases_are_in_the_development_set():
    assert sum(c["category"] == "review_regression" for c in RR3) >= 40
    assert sum(c["category"] == "review_positive" for c in RR3) >= 20


@pytest.mark.parametrize("case", RR3, ids=lambda c: c["id"])
def test_third_review_cases_have_their_labels(case):
    turn = case["turns"][0]
    assert analyse(turn["user"]) == _result(turn["expected"])
    assert (intent.decide(turn["user"]).intent.kind == "propose") == (turn["expected"]["kind"] == "propose")


def test_every_new_request_variant_proposes():
    positives = [c["turns"][0] for c in RR3 if c["category"] == "review_positive"]
    assert all(analyse(t["user"]) == _result(t["expected"]) for t in positives)


_SUBJECTS = ["we", "you", "they", "he", "she", "i", "it"]
_PHRASES = [
    "set the cap at {v} °C", "set the maximum to {v} °C", "capped the indoor temperature at {v} °C",
    "put the ceiling at {v} °C", "cap the house at {v} °C", "had set the limit to {v} °C",
    "are setting the maximum to {v} °C", "will set the cap at {v} °C", "have capped it at {v} °C",
]


def _declaratives():
    out = []
    for i, subject in enumerate(_SUBJECTS):
        for j, phrase in enumerate(_PHRASES):
            out.append(f"{subject.capitalize()} {phrase.format(v=22 + (i + j) % 20 / 10)}.")
    out += [f"She said the cap is {v} °C." for v in ("23", "22.5")]
    out += [f"I set the cap at {v} yesterday." for v in ("23", "22.4")]
    return out


def test_declarative_sentences_never_propose():
    sentences = _declaratives()
    assert len(sentences) >= 50
    for text in sentences:
        assert not isinstance(analyse(text), Proposal), text
        assert intent.decide(text).intent.kind != "propose", text


@pytest.mark.parametrize("text", [
    "Set it to 23", "We should cap it at 23", "ما سقف را ۲۳ گذاشتیم", "سقف ۲۳ بود",
])
def test_subject_and_tense_words_are_not_dropped(text):
    assert not isinstance(analyse(text), Proposal)


# --- Declarations never propose; explicit requests still do -----------------------------------

DEV_G = [c for c in DEV["cases"] if c["id"].startswith("dev-g-")]
DECLARATIVES = [c["turns"][0]["user"] for c in DEV_G if c["turns"][0]["expected"]["kind"] == "clarify"]


def test_the_failing_statement_and_its_variants_are_in_dev():
    assert "22.6 °C is the maximum indoor temperature." in DECLARATIVES
    assert len(DECLARATIVES) >= 30
    assert any("حداکثر دمای داخل ۲۲٫۶ درجه است" == t for t in DECLARATIVES)
    assert any("سقف ۲۳ درجه‌ست" == t for t in DECLARATIVES)
    assert any("۲۳ درجه حداکثره" == t for t in DECLARATIVES)


@pytest.mark.parametrize("case", DEV_G, ids=lambda c: c["id"])
def test_declarative_and_request_dev_cases_have_their_labels(case):
    turn = case["turns"][0]
    assert analyse(turn["user"]) == _result(turn["expected"])


@pytest.mark.parametrize("text", DECLARATIVES)
def test_a_declaration_is_never_proposed_by_either_entry_point(text):
    assert analyse(text) == clarify("question_with_value")
    decided = intent.decide(text).intent
    assert decided.kind == "clarify" and decided.reason == "question_with_value"


@pytest.mark.parametrize("template", [
    "{n} is the max", "{n} is the maximum", "{n} is the limit", "{n} is the ceiling",
    "the max is {n}", "The maximum is {n} degrees", "maximum indoor temperature is {n}",
    "{n} °C is the maximum indoor temperature.",
])
@pytest.mark.parametrize("n", ["21.5", "22", "22.6", "23.4", "24"])
def test_declaration_templates_never_propose_for_any_value(template, n):
    assert not isinstance(analyse(template.format(n=n)), Proposal)


@pytest.mark.parametrize("text", [
    "Kindly set the entire-day ceiling to 22.7 °C.", "Please use 22.3 °C as the maximum indoor temperature.",
    "Please enforce an indoor ceiling of 22.9 °C all day.",
    "لطفاً سقف دمای خانه را روی ۲۲٫۵ درجه قرار بده.", "خواهش می‌کنم سقف دمای خانه را روی ۲۲٫۵ درجه قرار بده.",
    "دمای داخل در تمام طول روز حداکثر ۲۱٫۸ درجه باشه، لطفاً.",
    "حداکثر دمای داخل خانه را برای تمام روز ۲۲٫۶ درجه تعیین کنید.",
    "22,5 is the most I'd want", "23 is the most I want", "23 is the most I need",
])
def test_the_added_request_patterns_propose(text):
    assert isinstance(analyse(text), Proposal)
    assert isinstance(intent.decide(text).intent, intent.ProposeCeiling)


@pytest.mark.parametrize("text", [
    "I need to use 23 as the maximum", "We use 23 as the maximum", "She enforced a ceiling of 23",
    "Kindly note the entire-day ceiling is 23", "Please say whether 23 is the maximum",
    "enforce 23 tonight", "use 23 as the max if it is cold", "ceiling of 23 is enforced",
])
def test_the_added_patterns_do_not_widen_the_gate(text):
    assert not isinstance(analyse(text), Proposal)
