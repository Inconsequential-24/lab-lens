"""safety_check node (PLAN.md section 4). Rules in reference/safety_rules.yaml.

Each failure is tagged "plan" (wrong claim, missing/unknown citation, missing urgent text:
retry plan_statements) or "render" (one language dropped a unit or used a banned phrase:
retry only that render). A render failure seen in every language for the same claim is
promoted to plan-level, because the claim itself is wrong.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from lablens import reference
from lablens.glossary import glossary_ids
from lablens.schemas import Explanation, Flag, FlaggedTest, Recommendation
from lablens.templates import DISCLAIMER, LANGS, display_name, urgent_template

_NUM = re.compile(r"(?<![\w^.\u0900-\u097F])\d+(?:\.\d+)?(?![\w^\u0900-\u097F])")
_GROUPED = re.compile(r"(?<![\d.,])\d{1,3}(?:,\d{2})*,\d{3}(?![\d,])")  # 1,020 / 1,20,000
_W = r"[\w\u0900-\u097F]"  # Python \w misses Devanagari vowel signs
_ABN = {Flag.LOW, Flag.HIGH}


@dataclass(frozen=True)
class SafetyFailure:
    level: str          # "plan" | "render"
    language: str       # "en" | "hi" | "*"
    claim_id: str | None
    code: str
    detail: str


def _rules() -> dict:
    return reference.load_yaml("safety_rules.yaml")


def _pat(phrase: str, lang: str, word: bool) -> str:
    if lang == "en":
        return r"(?<!\w)" + re.escape(phrase.lower())
    if not word:
        return re.escape(phrase)
    if phrase.endswith("*"):
        return f"(?<!{_W})" + re.escape(phrase[:-1])
    return f"(?<!{_W})" + re.escape(phrase) + f"(?!{_W})"


def _has(text: str, phrase: str, lang: str, word: bool = False) -> bool:
    """word=True: Hindi entries match whole words (or word-start with a trailing "*")."""
    t = text.lower() if lang == "en" else text
    return re.search(_pat(phrase, lang, word), t) is not None


def _nums(text: str) -> set[float]:
    text = _GROUPED.sub(lambda m: m.group(0).replace(",", ""), text)
    return {round(float(x), 6) for x in _NUM.findall(text)}


def _test_nums(t: FlaggedTest) -> set[float]:
    out = _nums(t.value.raw) | _nums(t.ref.raw or "")
    out |= {round(x, 6) for x in (t.value.number, t.ref.low, t.ref.high) if x is not None}
    return out


def _banned(text: str, lang: str) -> list[str]:
    rules = _rules()
    hits = [p for group in rules["banned"].values() for p in group.get(lang, [])
            if _has(text, p, lang)]
    return hits + [p for p in rules.get("banned_patterns", {}).get(lang, [])
                   if re.search(p, text, re.IGNORECASE)]


def _negated(text: str, w: str, lang: str) -> bool:
    negs = _rules()["direction"]["negation"][lang]
    t = text.lower() if lang == "en" else text
    neg = "(?:" + "|".join(re.escape(n) for n in sorted(negs, key=len, reverse=True)) + ")"
    word = _pat(w, lang, True)
    if lang == "en":
        pre = rf"(?:(?<!\w){neg}(?!\w)|\w+n't)\W+(?:\w+\W+){{0,2}}"
        return re.search(pre + word, t) is not None
    after = word + rf"\S*(?:\s+\S+){{0,2}}\s+{neg}(?!{_W})"
    before = rf"(?<!{_W})नहीं\s+(?:\S+\s+){{0,2}}" + word
    return re.search(after, t) is not None or re.search(before, t) is not None


def _direction_fails(text: str, lang: str, flags: set[Flag], scope_abn: bool) -> list[tuple]:
    """(level, code, detail) for direction/reassurance misuse. flags: tests the words refer
    to; scope_abn: whether any low/high test is in scope for generic/reassurance words."""
    words = _rules()["direction"]
    for ig in words.get("ignore", {}).get(lang, []):
        text = re.sub(_pat(ig, lang, True), " ", text, flags=re.IGNORECASE)
    hits = {k: [w for w in words[k][lang] if _has(text, w, lang, True)]
            for k in ("low", "high", "abnormal", "normal")}
    out, abn = [], flags & _ABN
    if (hits["low"] or hits["high"]) and len(abn) > 1:
        out.append(("plan", "mixed_direction", "direction words with low and high tests cited"))
    for d, flag in (("low", Flag.LOW), ("high", Flag.HIGH)):
        if hits[d] and flag not in flags:
            out.append(("render", "wrong_direction",
                        f"{hits[d][0]!r} but flags {sorted(f.value for f in flags)}"))
    if hits["abnormal"] and not scope_abn:
        out.append(("render", "wrong_direction", f"{hits['abnormal'][0]!r} but nothing flagged"))
    if hits["normal"] and scope_abn:
        out.append(("render", "reassurance_against_flag", repr(hits["normal"][0])))
    if scope_abn:
        neg = [w for k in hits for w in hits[k] if _negated(text, w, lang)]
        if neg:
            out.append(("render", "negated_direction", repr(neg[0])))
    return out


def _check_language(ex: Explanation, by_id: dict[str, list[FlaggedTest]],
                    gl_ids: set[str], remark_ids: set[str]) -> list[SafetyFailure]:
    lang, out = ex.language, []

    def fail(level, cid, code, detail):
        out.append(SafetyFailure(level, lang, cid, code, detail))

    for field, text in (("summary", ex.summary), ("urgent_message", ex.urgent_message or "")):
        for p in _banned(text, lang):
            fail("render", None, "banned_phrase", f"{field}: {p!r}")
    all_nums = set().union(*(_test_nums(t) for ts in by_id.values() for t in ts)) if by_id else set()
    if extra := _nums(ex.summary) - all_nums - {float(len(by_id))}:
        fail("render", None, "ungrounded_number", f"summary: {sorted(extra)}")
    any_abn = any(t.flag in _ABN for ts in by_id.values() for t in ts)
    for sent in re.split(r"[.!?\u0964]", ex.summary):
        named = {t.flag for ts in by_id.values() for t in ts
                 if any(n and _has(sent, n, lang, True) for n in {t.test_id, display_name(t, lang)})}
        for level, code, detail in _direction_fails(sent, lang, named, any_abn):
            fail(level, None, code, f"summary: {detail}")
    for st in ex.statements:
        cid, text = st.claim_id, st.text
        if not st.cites:
            fail("plan", cid, "missing_citation", "statement has no citations")
        flags: set[Flag] = set()
        tests: list[FlaggedTest] = []
        for c in st.cites:
            if c.kind == "test" and c.id in by_id:
                tests += by_id[c.id]
                flags |= {t.flag for t in by_id[c.id]}
            elif c.kind == "glossary" and c.id in gl_ids:
                # A glossary citation never supplies a flag: it refers to the test's real flag.
                tid, suffix = c.id.rsplit(".", 1)
                real = {t.flag for t in by_id.get(tid, [])}
                flags |= real
                if suffix in ("low", "high") and Flag(suffix) not in real:
                    fail("plan", cid, "glossary_flag_mismatch",
                         f"{c.id} but {tid} flags {sorted(f.value for f in real)}")
            elif c.kind == "remark" and c.id in remark_ids:
                pass
            else:
                fail("plan", cid, "unknown_citation", f"{c.kind}:{c.id}")
        for p in _banned(text, lang):
            fail("render", cid, "banned_phrase", repr(p))
        for level, code, detail in _direction_fails(text, lang, flags, bool(flags & _ABN)):
            fail(level, cid, code, detail)
        allowed = set().union(*(_test_nums(t) for t in tests)) if tests else set()
        if extra := _nums(text) - allowed:
            fail("render", cid, "ungrounded_number", str(sorted(extra)))
        for t in tests:
            unit = (t.unit_raw or "").strip()
            if (t.value.number is not None and round(t.value.number, 6) in _nums(text)
                    and unit and unit.lower() != "ratio" and unit not in text):
                fail("render", cid, "missing_unit", f"{t.test_id}: {unit}")
    if ex.disclaimer != DISCLAIMER[lang]:
        fail("render", None, "disclaimer_changed", "disclaimer must be the fixed text")
    return out


def safety_check(explanations: list[Explanation], flagged_tests: list[FlaggedTest],
                 recommendation: Recommendation) -> list[SafetyFailure]:
    """Return all failures; an empty list means the explanations may be shown."""
    by_id: dict[str, list[FlaggedTest]] = {}
    for t in flagged_tests:
        if t.test_id:
            by_id.setdefault(t.test_id, []).append(t)
    remark_ids = {t.test_id for t in flagged_tests if t.test_id and t.remark}
    gl_ids = glossary_ids()
    out: list[SafetyFailure] = []
    by_lang = {e.language: e for e in explanations}
    for lang in LANGS:
        if lang not in by_lang:
            out.append(SafetyFailure("plan", lang, None, "missing_language", lang))
    critical = any(t.is_critical for t in flagged_tests) or recommendation.urgency == "urgent"
    for lang, ex in by_lang.items():
        out += _check_language(ex, by_id, gl_ids, remark_ids)
        expected = urgent_template(lang, flagged_tests)
        if critical and (not ex.urgent_message or ex.urgent_message != expected):
            out.append(SafetyFailure("plan", lang, None, "missing_urgent_template",
                                     "critical value needs the fixed urgent text first"))
        elif not critical and ex.urgent_message:
            out.append(SafetyFailure("plan", lang, None, "unexpected_urgent", "no critical value"))
    # EN and HI must render the same claim set with the same citations and numbers.
    if "en" in by_lang:
        ref = {s.claim_id: s for s in by_lang["en"].statements}
        for lang, ex in by_lang.items():
            if lang == "en":
                continue
            other = {s.claim_id: s for s in ex.statements}
            for cid in ref.keys() ^ other.keys():
                out.append(SafetyFailure("render", lang, cid, "claim_set_mismatch",
                                         "claim present in only one language"))
            for cid in ref.keys() & other.keys():
                a, b = ref[cid], other[cid]
                if sorted((c.kind, c.id) for c in a.cites) != sorted((c.kind, c.id) for c in b.cites):
                    out.append(SafetyFailure("render", lang, cid, "citation_mismatch", "EN/HI cites differ"))
                if _nums(a.text) != _nums(b.text):
                    out.append(SafetyFailure("render", lang, cid, "number_mismatch", "EN/HI numbers differ"))
    return _promote(out, set(by_lang))


def _promote(fails: list[SafetyFailure], langs: set[str]) -> list[SafetyFailure]:
    seen: dict[tuple, set[str]] = {}
    for f in fails:
        if f.level == "render" and f.claim_id:
            seen.setdefault((f.claim_id, f.code), set()).add(f.language)
    both = {k for k, v in seen.items() if len(langs) > 1 and v >= langs}
    return [SafetyFailure("plan", f.language, f.claim_id, f.code, f.detail)
            if f.level == "render" and (f.claim_id, f.code) in both else f for f in fails]
