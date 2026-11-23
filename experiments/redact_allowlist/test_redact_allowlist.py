"""Unit tests for the allow-list redactor. Run: python -m pytest experiments/redact_allowlist -q"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import redact_allowlist as A  # noqa: E402

CELLS = """[page 1]
Patient Name : Ms. Kavita Menon
Age / Sex : 34 YRS / F
Mobile : +91 98765 43210
Reported on : 25/10/2026 01:52 PM
HAEMATOLOGY
TEST
VALUE
UNIT
REFERENCE
HEMOGLOBIN
L
13.1
g/dL
12.0 - 15.0
PATIENT CONTACT DETAILS
Name : Kavita Menon
Flat 402, Shanti Residency
Pune, Maharashtra 411038
PLATELET COUNT
251
10^3/µL
150 - 410"""


def test_pii_anywhere_is_dropped_and_rows_kept():
    out = A.redact_text(CELLS).text
    for s in ("Kavita", "Menon", "98765", "Shanti", "411038", "PATIENT"):
        assert s not in out
    assert "HEMOGLOBIN L 13.1 g/dL 12.0 - 15.0" in out
    assert "PLATELET COUNT 251 10^3/µL 150 - 410" in out


def test_fields_are_rebuilt():
    out = A.redact_text(CELLS).text.split("\n")
    assert out[:3] == ["Age: 34 YRS", "Sex: F", "Report date: 25/10/2026"]


def test_dob_is_never_the_report_date():
    f = A.extract_fields(["Age / DOB : 26 Y / 03-04-1992", "Sex : F", "Reported on : 21/12/2026"])
    assert f == {"age": "26", "sex": "F", "report_date": "21/12/2026"}


def test_name_and_age_on_one_line_keeps_only_age_sex():
    out = A.redact_text("Imran Sheikh  38 Y  M\nTEST\nHEMOGLOBIN\n13.1\ng/dL\n12.0 - 15.0").text
    assert "Imran" not in out and "Age: 38 YRS" in out and "Sex: M" in out


def test_pii_tail_inside_a_row_is_cut():
    assert A.clean_name("HEMOGLOBIN (patient Imran Sheikh)", "lenient") == "HEMOGLOBIN"
    assert A.clean_name("PLATELET COUNT 98339 93319", "lenient") == "PLATELET COUNT"
    assert A.clean_name("SERUM CREATININE c/o Dr. A. Khanna", "lenient") == "SERUM CREATININE"


def test_longer_test_name_is_not_truncated_to_a_different_test():
    # "MEAN CORPUSCULAR HEMOGLOBIN" is MCH; cutting MCHC to it would mislabel the result
    name = "MEAN CORPUSCULAR HEMOGLOBIN CONCENTRATION"
    assert A.clean_name(name, "lenient") == name
    assert A.clean_name(name, "strict") is None


def test_column_header_is_not_glued_to_the_next_row():
    out = A.redact_text("TEST\nVALUE\nUNIT\nREFERENCE\nHEMOGLOBIN\n13.1\ng/dL\n12.0 - 15.0").text
    assert "REFERENCE HEMOGLOBIN" not in out and "HEMOGLOBIN 13.1 g/dL 12.0 - 15.0" in out


def test_test_named_like_its_panel_is_a_row():
    out = A.redact_text("GLYCOSYLATED HAEMOGLOBIN (HbA1c)\nTEST\nGLYCOSYLATED HEMOGLOBIN (HbA1c)\n5.4\n%\n4.0 - 5.6").text
    assert "GLYCOSYLATED HEMOGLOBIN (HbA1c) 5.4 % 4.0 - 5.6" in out


def test_strict_mode_drops_unknown_tests_lenient_keeps_them():
    t = "TEST\nSERUM CREATININE\n0.8\nmg/dL\n0.6 - 1.1"
    assert "SERUM CREATININE" in A.redact_text(t, "lenient").text
    assert "SERUM CREATININE" not in A.redact_text(t, "strict").text


def test_devanagari_and_ids_never_pass():
    t = "नाम: कविता मेनन\nAadhaar: 4821 7733 0915\nwww.lab.example/r/AB12\nTEST\nMCV\n92.4\nfL\n83.0 - 101.0"
    out = A.redact_text(t).text
    assert out.strip().endswith("MCV 92.4 fL 83.0 - 101.0") and "4821" not in out and "www" not in out
    assert not A.PII_PATTERNS["non_latin"].search(out)


def test_validator_blocks_a_row_name_with_pii():
    assert A.validate(A.Line("row", "X 1 g/dL", "Ms. Someone")) != []
    assert A.validate(A.Line("row", "PLATELET COUNT 251 10^3/µL 150 - 410", "PLATELET COUNT")) == []
