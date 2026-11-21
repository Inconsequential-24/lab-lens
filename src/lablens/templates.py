"""urgent_template and template_fallback (PLAN.md section 4). Deterministic, no LLM.

Hindi wording is model-written demo text and needs review by a fluent Hindi reader.
"""
from __future__ import annotations

from lablens import reference
from lablens.flag_engine import CRITICAL_OVERRIDE_WARNING
from lablens.glossary import glossary_lookup
from lablens.schemas import (Citation, Explanation, Flag, FlaggedTest, Recommendation,
                             Severity, Statement)

LANGS = ("en", "hi")
LOW_CONFIDENCE = 0.7  # PLAN.md gives no number; below this a critical value adds "confirm"
DISCLAIMER = {
    "en": "This explains your report. It is not medical advice or a diagnosis.",
    "hi": "यह आपकी रिपोर्ट को समझाता है। यह चिकित्सा सलाह या निदान नहीं है।",
}
_RANK = {Severity.CRITICAL: 0, Severity.MARKED: 1, Severity.MILD: 2}


def _fmt(x: float) -> str:
    return f"{x:g}"


def _unit(t: FlaggedTest) -> str:
    u = (t.unit_raw or t.unit or "").strip()
    return f" {u}" if u else ""


def display_name(t: FlaggedTest, lang: str) -> str:
    en = (reference.load_tests().get(t.test_id or "") or {}).get("name") or t.raw_name
    if lang == "en":
        return en
    hi = (glossary_lookup([t.test_id]).get(t.test_id) or {}).get("name_hi")
    return f"{hi} ({en})" if hi else en


def critical_tests(tests: list[FlaggedTest]) -> list[FlaggedTest]:
    seen, out = set(), []
    for t in tests:
        if t.is_critical and t.test_id not in seen:
            seen.add(t.test_id)
            out.append(t)
    return out


def urgent_template(lang: str, tests: list[FlaggedTest],
                    low_confidence: float = LOW_CONFIDENCE) -> str | None:
    """Fixed urgent text naming each critical test and value; None when nothing is critical."""
    crit = critical_tests(tests)
    if not crit:
        return None
    vals = ", ".join(f"{display_name(t, lang)} {t.value.raw}{_unit(t)}" for t in crit)
    confirm = any(t.confidence < low_confidence for t in crit)
    if lang == "en":
        text = (f"URGENT: Your report shows a result that needs prompt medical attention: {vals}. "
                "Please contact a doctor or the lab now. Do not wait for a routine appointment.")
        return text + (" Please confirm this value with the lab." if confirm else "")
    text = (f"तुरंत ध्यान दें: आपकी रिपोर्ट में ऐसा परिणाम है जिस पर तुरंत डॉक्टर से बात करनी "
            f"चाहिए: {vals}। कृपया अभी डॉक्टर या लैब से संपर्क करें। रूटीन अपॉइंटमेंट का इंतज़ार न करें।")
    return text + (" कृपया इस मान की लैब से पुष्टि करें।" if confirm else "")


def _value_sentence(t: FlaggedTest, lang: str) -> str:
    name, val, u = display_name(t, lang), t.value.raw, _unit(t)
    lo, hi = t.ref.low, t.ref.high
    printed = t.ref.source == "report"
    if CRITICAL_OVERRIDE_WARNING in t.warnings:  # the printed range does not support the flag
        if lang == "en":
            word = "low" if t.flag is Flag.LOW else "high"
            return (f"Your {name} is {val}{u}. This is very {word}: it is past the safety limit "
                    f"we use for urgent results, whatever range your report prints.")
        word = "कम" if t.flag is Flag.LOW else "अधिक"
        return (f"आपका {name} {val}{u} है। यह बहुत {word} है: यह उस सुरक्षा सीमा से आगे है "
                f"जिसे हम तुरंत ध्यान देने वाले परिणामों के लिए उपयोग करते हैं।")
    if lang == "en":
        where = "printed on your report" if printed else "from our standard table (not printed on your report)"
        if lo is not None and hi is not None:
            rng = f"the range of {_fmt(lo)} to {_fmt(hi)}{u} {where}"
        elif lo is not None:
            rng = f"the lower limit of {_fmt(lo)}{u} {where}"
        else:
            rng = f"the upper limit of {_fmt(hi)}{u} {where}"
        word = "below" if t.flag is Flag.LOW else "above"
        return f"Your {name} is {val}{u}, {word} {rng}."
    where = "आपकी रिपोर्ट पर छपी" if printed else "हमारी मानक तालिका की (रिपोर्ट पर नहीं छपी)"
    if lo is not None and hi is not None:
        rng = f"{where} सीमा {_fmt(lo)} से {_fmt(hi)}{u}"
    elif lo is not None:
        rng = f"{where} न्यूनतम सीमा {_fmt(lo)}{u}"
    else:
        rng = f"{where} अधिकतम सीमा {_fmt(hi)}{u}"
    word = "कम" if t.flag is Flag.LOW else "अधिक"
    return f"आपका {name} {val}{u} है, जो {rng} से {word} है।"


_VERIFY = {"en": "Please verify your {n} result with the lab; we could not compare it with a range.",
           "hi": "कृपया अपने {n} परिणाम की लैब से पुष्टि करें; हम इसे किसी सीमा से नहीं मिला पाए।"}
_OTHERS = {"en": "Your other results are within the ranges printed on your report.",
           "hi": "आपके बाकी परिणाम आपकी रिपोर्ट पर छपी सीमाओं के भीतर हैं।"}
_NEXT = {
    "urgent": {"en": "Please contact a doctor or the lab now about these results.",
               "hi": "कृपया इन परिणामों के बारे में अभी डॉक्टर या लैब से संपर्क करें।"},
    "soon": {"en": "It is worth discussing these results with a doctor soon.",
             "hi": "इन परिणामों के बारे में जल्द ही डॉक्टर से बात करना अच्छा रहेगा।"},
    "routine": {"en": "You may want to discuss these results with a doctor at a routine visit.",
                "hi": "आप अगली नियमित मुलाकात में इन परिणामों के बारे में डॉक्टर से बात कर सकते हैं।"},
    "package": {"en": "A follow-up test package may help: {p}.",
                "hi": "एक फ़ॉलो-अप जाँच पैकेज मददगार हो सकता है: {p}।"},
}
_SUMMARY = {
    "urgent": {"en": "I went through your report. One or more results need urgent attention.",
               "hi": "मैंने आपकी रिपोर्ट देखी। एक या अधिक परिणामों पर तुरंत ध्यान देना ज़रूरी है।"},
    "some": {"en": "I went through your report. Some results are outside the ranges printed on it.",
             "hi": "मैंने आपकी रिपोर्ट देखी। कुछ परिणाम रिपोर्ट पर छपी सीमाओं से बाहर हैं।"},
    "none": {"en": "I went through your report. All results are within the ranges printed on your report.",
             "hi": "मैंने आपकी रिपोर्ट देखी। सभी परिणाम आपकी रिपोर्ट पर छपी सीमाओं के भीतर हैं।"},
}


def _claims(tests: list[FlaggedTest], rec: Recommendation, gl: dict) -> list[tuple[str, dict, list[Citation]]]:
    """Language-neutral plan: (claim_id, {lang: text}, cites)."""
    recognised = [t for t in tests if t.test_id]
    abnormal: dict[str, FlaggedTest] = {}
    for t in recognised:
        if t.flag in (Flag.LOW, Flag.HIGH):
            cur = abnormal.get(t.test_id)
            if cur is None or _RANK.get(t.severity, 3) < _RANK.get(cur.severity, 3):
                abnormal[t.test_id] = t
    ordered = sorted(abnormal.values(), key=lambda t: _RANK.get(t.severity, 3))
    out, n = [], 0
    for t in ordered:
        n += 1
        out.append((f"c{n}", {l: _value_sentence(t, l) for l in LANGS},
                    [Citation(kind="test", id=t.test_id)]))
        e = gl.get(t.test_id)
        if e:
            n += 1
            d = t.flag.value
            out.append((f"c{n}", {l: f"{e['measures'][l]} {e[d][l]}" for l in LANGS},
                        [Citation(kind="glossary", id=f"{t.test_id}.measures"),
                         Citation(kind="glossary", id=f"{t.test_id}.{d}")]))
    for t in recognised:
        if t.flag is Flag.UNKNOWN and not reference.is_informational(t.test_id) \
                and t.test_id not in abnormal:
            n += 1
            out.append((f"c{n}", {l: _VERIFY[l].format(n=display_name(t, l)) for l in LANGS},
                        [Citation(kind="test", id=t.test_id)]))
    normal = sorted({t.test_id for t in recognised if t.flag is Flag.NORMAL} - set(abnormal))
    if normal and abnormal:
        n += 1
        out.append((f"c{n}", dict(_OTHERS), [Citation(kind="test", id=i) for i in normal]))
    if rec.next_step != "no_action" and rec.reason_test_ids:
        if rec.next_step == "follow_up_test_package":
            label = reference.load_packages()[rec.package_id]["label"]
            text = {l: _NEXT["package"][l].format(p=label) for l in LANGS}
        else:
            text = dict(_NEXT.get(rec.urgency, _NEXT["routine"]))
        n += 1
        out.append((f"c{n}", text, [Citation(kind="test", id=i) for i in rec.reason_test_ids]))
    if not out and normal:  # all normal: one bounded statement
        out.append(("c1", {l: _SUMMARY["none"][l] for l in LANGS},
                    [Citation(kind="test", id=i) for i in normal]))
    return out


def template_fallback(tests: list[FlaggedTest], rec: Recommendation) -> list[Explanation]:
    """Full EN + HI explanations from deterministic outputs and the glossary."""
    gl = glossary_lookup([t.test_id for t in tests])
    claims = _claims(tests, rec, gl)
    has_abnormal = any(t.test_id and t.flag in (Flag.LOW, Flag.HIGH) for t in tests)
    kind = "urgent" if critical_tests(tests) else ("some" if has_abnormal else "none")
    return [Explanation(language=l, source="template_fallback",
                        urgent_message=urgent_template(l, tests),
                        summary=_SUMMARY[kind][l],
                        statements=[Statement(claim_id=c, text=txt[l], cites=cites)
                                    for c, txt, cites in claims],
                        disclaimer=DISCLAIMER[l]) for l in LANGS]
