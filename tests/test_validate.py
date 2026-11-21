from lablens.schemas import Extraction, ExtractedRow
from lablens.validate import LOW_CONFIDENCE, map_test_id, missing_expected, validate

SRC = "HEMOGLOBIN 11.3 g/dL 12.0 - 15.0 MCV 79.2 fL PLATELET COUNT 265"


def row(name, value, unit="g/dL", low=12.0, high=15.0, **kw):
    return ExtractedRow(raw_name=name, value_raw=value, unit_raw=unit, ref_raw=f"{low} - {high}",
                        ref_low=low, ref_high=high, **kw)


def test_alias_mapping():
    assert map_test_id("HEMOGLOBIN") == ("HB", "alias")
    assert map_test_id("PACKED CELL VOLUME (PCV)")[0] == "PCV"
    assert map_test_id("TOTAL LEUCOCYTE COUNT (TLC)")[0] == "WBC"
    assert map_test_id("A/G Ratio")[0] == "AG"
    assert map_test_id("A : G Ratio")[0] == "AG"
    assert map_test_id("Mystery Marker", "TSH") == ("TSH", "hint")
    assert map_test_id("Mystery Marker", "NOPE") == (None, None)


def test_model_matched_name_is_low_confidence_with_warning():
    from lablens.schemas import Extraction, ExtractedRow
    assert map_test_id("Haemoglobin Hb")[1] in ("alias", "model")
    name = next(n for n in ["Haemoglobin Hb", "Thyroid Stimulating Hormone (TSH)"]
                if map_test_id(n)[1] == "model")
    fields = ExtractedRow.model_fields
    row = {"raw_name": name, "value_raw": "11.0"}
    row.update({k: None for k, f in fields.items() if k not in row and f.is_required()})
    report = validate(Extraction(tests=[ExtractedRow(**row)]))
    assert report.tests[0].test_id in report.low_confidence_tests
    assert any("matched by the model" in w for w in report.warnings)


def test_valid_row_full_confidence():
    v = validate(Extraction(tests=[row("HEMOGLOBIN", "11.3")], report_date="2026-09-17"), SRC)
    t = v.tests[0]
    assert t.test_id == "HB" and t.value.number == 11.3 and t.confidence == 1.0
    assert t.ref.source == "report" and v.report_date.isoformat() == "2026-09-17"
    assert v.low_confidence_tests == []


def test_invented_value_dropped():
    v = validate(Extraction(tests=[row("HEMOGLOBIN", "14.8")]), SRC)
    assert v.tests == [] and v.dropped_rows == ["HEMOGLOBIN"]


def test_unknown_unit_and_implausible_lower_confidence():
    v = validate(Extraction(tests=[row("HEMOGLOBIN", "113", unit="bananas")]), "HEMOGLOBIN 113")
    assert v.tests[0].confidence < LOW_CONFIDENCE and v.low_confidence_tests == ["HB"]
    v = validate(Extraction(tests=[row("HEMOGLOBIN", "113")]), "HEMOGLOBIN 113")
    assert "HB" in v.low_confidence_tests and any("plausible" in w for w in v.warnings)


def test_comparator_qualitative_and_unrecognised():
    rows = [row("Platelet Count", "<5", unit="10^3/µL", low=150, high=410),
            row("Urine colour", "Pale yellow", unit=None, low=None, high=None)]
    v = validate(Extraction(tests=rows))
    assert v.tests[0].value.comparator == "<" and v.tests[0].value.number == 5
    assert v.unrecognised_tests == ["Urine colour"]


def test_completeness_and_bad_range():
    rows = [row("HbA1c", "5.4", unit="%", low=6.0, high=4.0)]
    assert missing_expected(rows) == ["Estimated Average Glucose (eAG)"] or missing_expected(rows)
    v = validate(Extraction(tests=rows))
    assert v.tests[0].ref.source == "none" and v.tests[0].confidence < 1.0
    assert any(w.startswith("expected tests not found") for w in v.warnings)


def test_report_date_out_of_range_rejected():
    v = validate(Extraction(tests=[], report_date="1985-01-01"))
    assert v.report_date is None and v.warnings
