import pytest

from lablens.flag_engine import compute_flag, compute_severity, flag_test, is_critical
from lablens.schemas import ExtractedTest, Flag, RefRange, Severity, Value


def make(test_id, raw, number, low, high, comparator="=", printed=None, ref_raw="x"):
    src = "none" if low is None and high is None else "report"
    return ExtractedTest(raw_name=test_id or "Mystery", test_id=test_id, panel=None,
                         value=Value(raw=raw, number=number, comparator=comparator),
                         unit_raw=None, unit=None,
                         ref=RefRange(raw=ref_raw, low=low, high=high, source=src),
                         printed_flag=printed, remark=None, page=1, source_span=raw,
                         confidence=0.95)


@pytest.mark.parametrize("num,comp,low,high,expected", [
    (13.5, "=", 13.0, 17.0, Flag.NORMAL),
    (13.0, "=", 13.0, 17.0, Flag.NORMAL),  # bounds inclusive
    (12.9, "=", 13.0, 17.0, Flag.LOW),
    (250, "=", None, 200, Flag.HIGH),      # one-sided "< 200"
    (35, "=", 40, None, Flag.LOW),         # one-sided "> 40"
    (0.010, "<", 0.27, 4.2, Flag.LOW),     # "<0.010" decidable
    (0.5, "<", None, 200, Flag.NORMAL),
    (0.5, "<", 0.3, 1.2, Flag.UNKNOWN),    # "<0.5" straddles low bound
    (1000, ">", 30, 120, Flag.HIGH),
    (1000, ">", None, 200, Flag.HIGH),
    (30, ">", 40, None, Flag.UNKNOWN),
    (None, "=", 1, 2, Flag.UNKNOWN),       # qualitative "Nil"
    (5.0, "=", None, None, Flag.UNKNOWN),
    (0, "=", 0, 40, Flag.NORMAL),          # zero-start range
])
def test_compute_flag(num, comp, low, high, expected):
    assert compute_flag(num, comp, low, high) is expected


def test_severity_mild_marked_threshold():
    assert compute_severity(Flag.LOW, 12.0, 13.0, 17.0) is Severity.MILD  # 7.7%
    assert compute_severity(Flag.LOW, 11.7, 13.0, 17.0) is Severity.MARKED  # 10%
    assert compute_severity(Flag.HIGH, 219, None, 200) is Severity.MILD


def test_severity_zero_bound_uses_width_or_marked():
    assert compute_severity(Flag.LOW, -1, 0, 40) is Severity.MILD  # 1/40
    assert compute_severity(Flag.LOW, -1, 0, None) is Severity.MARKED


def test_critical_independent_of_printed_range():
    # Printed range is absurdly wide, but Hb 6.5 is still critical.
    # The flag follows the breached safety limit, never "normal" next to an urgent banner.
    t = flag_test(make("HB", "6.5", 6.5, 5.0, 17.0))
    assert t.flag is Flag.LOW and t.is_critical and t.severity is Severity.CRITICAL
    assert any("past the safety limit" in w for w in t.warnings)
    assert is_critical(5.0, "<", {"low": 7.0})
    assert not is_critical(25.0, "<", {"high": 20.0})


def test_critical_without_printed_range_shows_direction_not_unknown():
    t = flag_test(make("HB", "6.0", 6.0, None, None))
    assert t.flag is Flag.LOW and t.is_critical
    assert any("past the safety limit" in w for w in t.warnings)


def test_critical_already_low_gets_no_override_note():
    t = flag_test(make("HB", "6.0", 6.0, 12.0, 15.5))
    assert t.flag is Flag.LOW and t.is_critical
    assert not any("past the safety limit" in w for w in t.warnings)


def test_labelled_range_parsed_bounds_flag():
    t = flag_test(make("TC_HDL", "5.4", 5.4, 3.0, 5.0, ref_raw="Desirable : 3.0-5.0"))
    assert t.flag is Flag.HIGH and t.severity is Severity.MILD


def test_missing_range_fallback_for_sex_independent_test():
    t = flag_test(make("MCV", "70", 70.0, None, None))
    assert t.ref.source == "fallback_table" and t.flag is Flag.LOW


def test_missing_range_no_fallback_for_sex_dependent_test():
    t = flag_test(make("HB", "11.0", 11.0, None, None))
    assert t.ref.source == "none" and t.flag is Flag.UNKNOWN and t.severity is Severity.UNKNOWN


def test_printed_flag_disagreement_recorded_but_computed_shown():
    t = flag_test(make("MCV", "90", 90.0, 83.0, 101.0, printed="H"))
    assert t.flag is Flag.NORMAL and t.flag_disagrees_with_printed
    assert not flag_test(make("MCV", "70", 70.0, 83.0, 101.0, printed="L")).flag_disagrees_with_printed


def test_unknown_test_does_not_crash():
    t = flag_test(make(None, "5", 5.0, None, None))
    assert t.flag is Flag.UNKNOWN


def _plt(raw, number, unit_raw, low, high, ref_raw):
    t = make("PLT", raw, number, low, high, ref_raw=ref_raw)
    return t.model_copy(update={"unit_raw": unit_raw, "unit": "10^3/µL"})


def test_plt_lakhs_per_cumm_critical_not_missed():
    ft = flag_test(_plt("12", 12, "lakhs/cumm", 1.5, 4.1, "1.5 - 4.1"))
    assert ft.is_critical and ft.flag is Flag.HIGH and ft.severity is Severity.CRITICAL


def test_plt_per_cumm_normal_not_critical():
    ft = flag_test(_plt("250000", 250000, "/cumm", 150000, 410000, "150000 - 410000"))
    assert not ft.is_critical and ft.flag is Flag.NORMAL and ft.warnings == []


def test_unknown_unit_is_unknown_with_warning_and_routes_to_verify():
    from lablens.decision import route_next_step as decide
    ft = flag_test(_plt("250", 250, "furlongs", 150, 410, "150 - 410"))
    assert ft.flag is Flag.UNKNOWN and not ft.is_critical
    assert ft.warnings == ["unit not recognised: please verify"]
    assert decide([ft]).rule_id == "R5_verify"


def test_canonical_unit_spelling_still_critical():
    ft = flag_test(_plt("1200", 1200, "10^3/µL", 150, 410, "150 - 410"))
    assert ft.is_critical


def test_fallback_range_flags_with_warning():
    ft = flag_test(make("ALB", "4.30", 4.30, None, None, ref_raw="-"))
    assert ft.ref.source == "fallback_table" and ft.flag is Flag.NORMAL
    assert ft.warnings == ["range not printed; standard range used"]


def test_no_fallback_stays_unknown_without_fallback_warning():
    ft = flag_test(make("HB", "14.6", 14.6, None, None, ref_raw="-"))
    assert ft.flag is Flag.UNKNOWN and ft.warnings == []
