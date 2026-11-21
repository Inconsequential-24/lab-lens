import pytest

from lablens.decision import route_next_step
from lablens.flag_engine import flag_tests
from lablens.safety import safety_check
from lablens.schemas import Citation, Statement
from lablens.templates import template_fallback
from tests.test_templates import make


def base(critical=False):
    hb = make("HB", "6.5", 6.5, 12.0, 15.0) if critical else make("HB", "10.2", 10.2, 12.0, 15.0)
    tests = flag_tests([hb, make("MCV", "85", 85, 80, 100, "fL")])
    rec = route_next_step(tests)
    return template_fallback(tests, rec), tests, rec


def set_text(exps, lang, idx, text, cites=None):
    ex = next(e for e in exps if e.language == lang)
    st = ex.statements[idx]
    ex.statements[idx] = Statement.model_construct(claim_id=st.claim_id, text=text,
                                                   cites=st.cites if cites is None else cites)


def codes(fails):
    return {(f.code, f.level, f.language) for f in fails}


def test_clean_fallback_passes():
    exps, tests, rec = base()
    assert safety_check(exps, tests, rec) == []


@pytest.mark.parametrize("lang,text,code", [
    ("en", "Your Hemoglobin is 10.2 g/dL. You have anemia.", "banned_phrase"),
    ("en", "This means you need iron tablets, 1 tablet daily.", "banned_phrase"),
    ("en", "Your Hemoglobin is 10.2 g/dL, which may explain why you feel tired.", "banned_phrase"),
    ("hi", "आपका Hemoglobin 10.2 g/dL है। आपको एनीमिया है।", "banned_phrase"),
    ("hi", "आपका Hemoglobin 10.2 g/dL है, आयरन की दवा लें।", "banned_phrase"),
    ("en", "Your Hemoglobin is 10.2 g/dL, above the range of 12 to 15 g/dL.", "wrong_direction"),
    ("hi", "आपका Hemoglobin 10.2 g/dL है, जो सीमा 12 से 15 g/dL से अधिक है।", "wrong_direction"),
    ("en", "Your Hemoglobin is 10.2 g/dL, which is within the normal range.", "reassurance_against_flag"),
    ("en", "Your Hemoglobin is 9.2 g/dL, below the range of 12 to 15 g/dL.", "ungrounded_number"),
    ("en", "Your Hemoglobin is 10.2, below the range of 12 to 15.", "missing_unit"),
    ("hi", "आपका Hemoglobin 10.2 है, जो सीमा 12 से 15 से कम है।", "missing_unit"),
])
def test_adversarial_statement_rejected_as_render(lang, text, code):
    exps, tests, rec = base()
    set_text(exps, lang, 0, text)
    fails = safety_check(exps, tests, rec)
    assert (code, "render", lang) in codes(fails), fails


def test_same_error_in_both_languages_is_plan_level():
    exps, tests, rec = base()
    set_text(exps, "en", 0, "Your Hemoglobin is 10.2 g/dL, above the range of 12 to 15 g/dL.")
    set_text(exps, "hi", 0, "आपका Hemoglobin 10.2 g/dL है, जो सीमा 12 से 15 g/dL से अधिक है।")
    assert {f.level for f in safety_check(exps, tests, rec)} == {"plan"}


def test_missing_citation_is_plan_level():
    exps, tests, rec = base()
    set_text(exps, "en", 0, exps[0].statements[0].text, cites=[])
    assert ("missing_citation", "plan", "en") in codes(safety_check(exps, tests, rec))


def test_unknown_citation_is_plan_level():
    exps, tests, rec = base()
    set_text(exps, "en", 0, exps[0].statements[0].text, cites=[Citation(kind="test", id="TSH")])
    assert ("unknown_citation", "plan", "en") in codes(safety_check(exps, tests, rec))


def test_glossary_citation_direction_checked():
    exps, tests, rec = base()
    set_text(exps, "en", 1, "A higher value can be affected by many things.")
    assert ("wrong_direction", "render", "en") in codes(safety_check(exps, tests, rec))


def test_en_hi_mismatch_rejected():
    exps, tests, rec = base()
    exps[1].statements.pop(1)
    assert ("claim_set_mismatch", "render", "hi") in codes(safety_check(exps, tests, rec))
    exps, tests, rec = base()
    set_text(exps, "hi", 1, exps[1].statements[1].text, cites=[Citation(kind="glossary", id="HB.measures")])
    assert ("citation_mismatch", "render", "hi") in codes(safety_check(exps, tests, rec))


def test_missing_language_rejected():
    exps, tests, rec = base()
    assert ("missing_language", "plan", "hi") in codes(safety_check(exps[:1], tests, rec))


def test_critical_passes_and_missing_urgent_banner_rejected():
    exps, tests, rec = base(critical=True)
    assert safety_check(exps, tests, rec) == []
    exps[1].urgent_message = None
    assert ("missing_urgent_template", "plan", "hi") in codes(safety_check(exps, tests, rec))
    exps, tests, rec = base(critical=True)
    exps[0].urgent_message = "Please see a doctor."
    assert ("missing_urgent_template", "plan", "en") in codes(safety_check(exps, tests, rec))


def test_banned_phrase_in_summary_rejected():
    exps, tests, rec = base()
    exps[0].summary = "You are healthy, nothing to worry about."
    assert ("banned_phrase", "render", "en") in codes(safety_check(exps, tests, rec))


def high_base():
    tests = flag_tests([make("HB", "17.0", 17.0, 12.0, 15.0), make("MCV", "70", 70, 80, 100, "fL")])
    rec = route_next_step(tests)
    return template_fallback(tests, rec), tests, rec


def test_glossary_low_cite_cannot_override_high_test():
    exps, tests, rec = high_base()
    set_text(exps, "en", 0, "Your haemoglobin is low.",
             cites=[Citation(kind="test", id="HB"), Citation(kind="glossary", id="HB.low")])
    c = codes(safety_check(exps, tests, rec))
    assert ("glossary_flag_mismatch", "plan", "en") in c
    assert ("wrong_direction", "render", "en") in c


def test_direction_words_with_mixed_low_high_cites_rejected():
    exps, tests, rec = high_base()  # HB high, MCV low
    set_text(exps, "en", 0, "Your Hemoglobin is low and your MCV is high.",
             cites=[Citation(kind="test", id="HB"), Citation(kind="test", id="MCV")])
    assert ("mixed_direction", "plan", "en") in codes(safety_check(exps, tests, rec))


@pytest.mark.parametrize("lang,summary,code", [
    ("en", "Your Hemoglobin is high.", "wrong_direction"),
    ("en", "Your report looks normal and fine.", "reassurance_against_flag"),
    ("en", "All results are high.", "wrong_direction"),
    ("hi", "आपका HB अधिक है।", "wrong_direction"),
    ("hi", "आपके सभी परिणाम सामान्य हैं।", "reassurance_against_flag"),
])
def test_summary_direction_and_reassurance_checked(lang, summary, code):
    exps, tests, rec = base()  # HB low
    next(e for e in exps if e.language == lang).summary = summary
    assert (code, "render", lang) in codes(safety_check(exps, tests, rec))


@pytest.mark.parametrize("lang,text,code", [
    ("en", "Your Hemoglobin is 10.2 g/dL; you may have low iron.", "banned_phrase"),
    ("en", "Your Hemoglobin is 10.2 g/dL, which points to blood loss.", "banned_phrase"),
    ("en", "Your Hemoglobin is 10.2 g/dL, likely from diet.", "banned_phrase"),
    ("en", "Your Hemoglobin is 10.2 g/dL, which could be from diet.", "banned_phrase"),
    ("en", "Your Hemoglobin of 10.2 g/dL suggests a problem.", "banned_phrase"),
    ("en", "Your Hemoglobin is 10.2 g/dL because of diet.", "banned_phrase"),
    ("en", "Your Hemoglobin is 10.2 g/dL due to diet.", "banned_phrase"),
    ("hi", "आपका Hemoglobin 10.2 g/dL है, आपको आयरन की समस्या हो सकती है।", "banned_phrase"),
    ("hi", "आपका Hemoglobin 10.2 g/dL है, यह आहार के कारण है।", "banned_phrase"),
    ("en", "Your Hemoglobin is 10.2 g/dL, raised above the range.", "wrong_direction"),
    ("en", "Your Hemoglobin is 10.2 g/dL and has increased.", "wrong_direction"),
    ("hi", "आपका Hemoglobin 10.2 g/dL है, जो बढ़कर आया है।", "wrong_direction"),
    ("en", "Your Hemoglobin is 10.2 g/dL, which is not low.", "negated_direction"),
    ("hi", "आपका Hemoglobin 10.2 g/dL है, जो कम नहीं है।", "negated_direction"),
])
def test_new_banned_and_direction_words(lang, text, code):
    exps, tests, rec = base()
    set_text(exps, lang, 0, text)
    assert (code, "render", lang) in codes(safety_check(exps, tests, rec))


def test_hindi_direction_word_boundary():
    exps, tests, rec = high_base()  # HB high: "कमरे" must not count as "कम"
    set_text(exps, "hi", 0, "आपका Hemoglobin 17.0 g/dL है, जो कमरे में जाँचा गया, सीमा 12 से 15 g/dL से अधिक है।")
    assert not any(f.code == "wrong_direction" for f in safety_check(exps, tests, rec))


def test_thousands_separators_grounded():
    tests = flag_tests([make("PLT", "1,20,000", 120000, 150000, 410000, "/cumm"),
                        make("SG", "1,020", 1020, 1005, 1030, "ratio")])
    rec = route_next_step(tests)
    exps = template_fallback(tests, rec)
    set_text(exps, "en", 0, "Your PLT is 1,20,000 /cumm, below the range of 150000 to 410000 /cumm.")
    assert not any(f.code == "ungrounded_number" and f.language == "en"
                   for f in safety_check(exps, tests, rec))
