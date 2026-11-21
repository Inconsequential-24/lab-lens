import re

from lablens import reference
from lablens.glossary import glossary_ids, glossary_lookup, load_glossary


def test_every_panel_test_has_en_hi_entries():
    gl = load_glossary()
    assert reference.load_yaml("glossary.yaml")["version"]
    for tid in reference.load_tests():
        e = gl[tid]
        assert e["name_hi"]
        for k in ("measures", "low", "high"):
            assert e[k]["en"].strip() and e[k]["hi"].strip()


def test_lookup_skips_unknown_and_none():
    out = glossary_lookup(["HB", None, "NOPE", "TSH"])
    assert list(out) == ["HB", "TSH"]
    assert "HB.low" in glossary_ids() and "TSH.high" in glossary_ids()


def test_glossary_text_has_no_banned_phrases():
    from lablens.safety import _banned
    for tid, e in load_glossary().items():
        for k in ("measures", "low", "high"):
            for lang in ("en", "hi"):
                assert _banned(e[k][lang], lang) == [], (tid, k, lang)


def test_glossary_direction_words_match_key():
    gl = load_glossary()["HB"]
    assert re.search(r"\blower\b", gl["low"]["en"]) and "कम" in gl["low"]["hi"]
    assert re.search(r"\bhigher\b", gl["high"]["en"]) and "अधिक" in gl["high"]["hi"]
