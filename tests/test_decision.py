from lablens.decision import route_next_step
from lablens.flag_engine import flag_test
from tests.test_flag_engine import make


def route(*rows):
    return route_next_step([flag_test(r) for r in rows])


def test_r1_critical_wins_even_with_low_confidence():
    r = route(make("HB", "6.0", 6.0, 12.0, 15.0), make("TSH", "9", 9.0, 0.27, 4.2))
    assert (r.rule_id, r.next_step, r.urgency, r.reason_test_ids) == (
        "R1_critical", "doctor_consult", "urgent", ["HB"])


def test_r2_marked():
    r = route(make("TSH", "9", 9.0, 0.27, 4.2))
    assert (r.rule_id, r.urgency) == ("R2_marked", "soon")


def test_r2_three_mild_abnormal():
    r = route(make("ALP", "125", 125, 30, 120), make("TP", "8.5", 8.5, 6.4, 8.3),
              make("ALB", "5.3", 5.3, 3.5, 5.2))
    assert r.rule_id == "R2_marked" and len(r.reason_test_ids) == 3


def test_r3_iron_package():
    r = route(make("HB", "11.5", 11.5, 12.0, 15.0), make("MCV", "80", 80.0, 83.0, 101.0))
    assert (r.rule_id, r.next_step, r.package_id, r.urgency) == (
        "R3_package", "follow_up_test_package", "iron_studies_package", "routine")


def test_r3_blocked_by_disallowed_abnormal_falls_to_r4():
    r = route(make("TSH", "4.5", 4.5, 0.27, 4.2), make("ALP", "125", 125, 30, 120))
    assert (r.rule_id, r.next_step, r.package_id) == ("R4_mild", "doctor_consult", None)


def test_r4_printed_flag_in_range():
    r = route(make("MCV", "90", 90.0, 83.0, 101.0, printed="H"))
    assert (r.rule_id, r.urgency) == ("R4_printed_flag", "routine")
    assert "confirm" in r.note


def test_r5_missing_range_needs_verify():
    r = route(make("HB", "13", 13.0, None, None), make("MCV", "90", 90.0, 83.0, 101.0))
    assert (r.rule_id, r.next_step, r.reason_test_ids) == ("R5_verify", "no_action", ["HB"])


def test_informational_eag_and_unrecognised_do_not_trigger_verify():
    r = route(make("EAG", "117", 117.0, None, None), make(None, "300", 300.0, 211, 911),
              make("HBA1C", "5.0", 5.0, 4.0, 5.6))
    assert r.rule_id == "R6_normal" and r.next_step == "no_action"


def test_duplicate_rows_use_more_severe():
    r = route(make("TSH", "4.3", 4.3, 0.27, 4.2), make("TSH", "9", 9.0, 0.27, 4.2))
    assert r.rule_id == "R2_marked"


def test_all_normal():
    r = route(make("HB", "13.5", 13.5, 12.0, 15.0))
    assert (r.rule_id, r.next_step, r.urgency, r.reason_test_ids) == (
        "R6_normal", "no_action", "none", [])
