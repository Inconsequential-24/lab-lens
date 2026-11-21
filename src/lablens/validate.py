"""validate: schema, alias mapping, unit, plausibility, completeness, confidence (PLAN.md 4, 11)."""
from __future__ import annotations

import re
from datetime import date, datetime
from functools import lru_cache

from lablens import reference
from lablens.flag_engine import to_canonical
from lablens.schemas import (Extraction, ExtractedRow, ExtractedTest, Panel, RefRange,
                             ValidatedReport, Value)

LOW_CONFIDENCE = 0.7
PENALTY = {"unit": 0.35, "implausible": 0.5, "hint_only": 0.2, "bad_range": 0.2,
           "unparsed_number": 0.3}
_NUM = re.compile(r"^\s*(<=|>=|<|>)?\s*(-?\d+(?:\.\d+)?)\s*$")


def norm_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower().replace("µ", "u").replace("μ", "u")).strip()


def _variants(name: str) -> set[str]:
    """Full name, name without parentheses, and the parenthetical alone."""
    out = {norm_name(name), norm_name(re.sub(r"\(.*?\)", " ", name))}
    out.update(norm_name(p) for p in re.findall(r"\((.*?)\)", name))
    return {v for v in out if v}


@lru_cache(maxsize=1)
def names_by_test() -> dict[str, frozenset[str]]:
    out = {}
    for tid, t in reference.load_tests().items():
        names = set()
        for a in [t["name"], *(t.get("aliases") or [])]:
            names |= _variants(str(a))
        names.add(norm_name(tid))
        out[tid] = frozenset(names)
    return out


@lru_cache(maxsize=1)
def _alias_index() -> dict[str, str | None]:
    idx: dict[str, str | None] = {}
    for tid, names in names_by_test().items():
        for n in names:
            idx[n] = tid if idx.get(n, tid) == tid else None  # None = ambiguous alias
    return idx


@lru_cache(maxsize=1)
def panel_of() -> dict[str, Panel]:
    return {tid: Panel(p) for p, spec in reference.load_yaml("panels.yaml")["panels"].items()
            for tid in spec["tests"]}


def map_test_id(raw_name: str, hint: str | None = None) -> tuple[str | None, str | None]:
    """(test_id, source): "alias" is trusted; "model" (ML matcher) and "hint" (LLM) must be verified."""
    idx = _alias_index()
    full = norm_name(raw_name)
    if idx.get(full):
        return idx[full], "alias"
    for v in sorted(_variants(raw_name), key=len, reverse=True):
        if idx.get(v):
            return idx[v], "alias"
    from lablens.ml.normalize_names import normalize_name_with_source
    tid, source = normalize_name_with_source(raw_name)
    if tid:
        return tid, source if source == "model" else "alias"
    if hint and hint.upper() in reference.load_tests():
        return hint.upper(), "hint"
    return None, None


def _value(row: ExtractedRow) -> tuple[Value, bool]:
    raw = row.value_raw.strip()
    m = _NUM.match(raw.replace(",", ""))
    if m:
        return Value(raw=raw, number=float(m.group(2)), comparator=m.group(1) or "="), True
    if row.value_number is not None:  # LLM gave a number we cannot see in raw
        return Value(raw=raw, number=row.value_number, comparator=row.comparator), False
    return Value(raw=raw, number=None, comparator="="), True


def _grounded(raw: str, source: str) -> bool:
    squash = lambda s: re.sub(r"\s+", "", s)
    return squash(raw) in squash(source)


def parse_report_date(raw: str | None) -> date | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d-%b-%Y"):
        try:
            d = datetime.strptime(raw.strip()[:11].strip(), fmt).date()
        except ValueError:
            continue
        return d if date(1990, 1, 1) <= d <= date.today() else None
    return None


def missing_expected(rows: list[ExtractedRow]) -> list[str]:
    """Expected tests of every detected panel that no row maps to (completeness check)."""
    ids = {map_test_id(r.raw_name, r.test_id_hint)[0] for r in rows}
    panels = {panel_of()[t] for t in ids if t in panel_of()}
    spec = reference.load_yaml("panels.yaml")["panels"]
    tests = reference.load_tests()
    return [tests[t]["name"] for p in sorted(panels, key=lambda p: p.value)
            for t in spec[p.value]["tests"] if t not in ids]


def resolve_names(extraction: Extraction) -> dict[str, tuple[str | None, str | None]]:
    """normalize_names node logic: raw name -> (test_id, source) for every extracted row."""
    return {r.raw_name: map_test_id(r.raw_name, r.test_id_hint) for r in extraction.tests}


def validate(extraction: Extraction, source_text: str = "",
             names: dict[str, tuple[str | None, str | None]] | None = None) -> ValidatedReport:
    """source_text: redacted text layer; when present, values not found in it are dropped.
    names: output of resolve_names (the normalize_names node); computed here when absent."""
    names = names if names is not None else resolve_names(extraction)
    tests, unrecognised, dropped, low_conf, warnings = [], [], [], [], []
    plaus = {tid: t.get("plausible") for tid, t in reference.load_tests().items()}
    for row in extraction.tests:
        if not row.raw_name.strip() or not row.value_raw.strip():
            dropped.append(row.raw_name or "<blank>")
            continue
        if source_text and not _grounded(row.value_raw, source_text):
            dropped.append(row.raw_name)  # possibly invented: value not in the document
            continue
        tid, name_source = names.get(row.raw_name) or map_test_id(row.raw_name, row.test_id_hint)
        if tid is None:
            unrecognised.append(row.raw_name)
            continue
        conf = 1.0
        value, parsed_ok = _value(row)
        if not parsed_ok:
            conf -= PENALTY["unparsed_number"]
        if name_source == "hint":
            conf -= PENALTY["hint_only"]
        if name_source == "model":
            low_conf.append(tid)
            warnings.append(f"{row.raw_name}: test name matched by the model, please verify")
        low, high = row.ref_low, row.ref_high
        if low is not None and high is not None and low > high:
            low = high = None
            conf -= PENALTY["bad_range"]
        canon, unit_ok = to_canonical(value.number, tid, row.unit_raw)
        if not unit_ok:
            conf -= PENALTY["unit"]
        lim = plaus.get(tid)
        if canon is not None and lim and not lim[0] <= canon <= lim[1]:
            conf -= PENALTY["implausible"]
            warnings.append(f"{row.raw_name}: value outside plausible limits, please verify")
        conf = max(0.0, round(conf, 2))
        if conf < LOW_CONFIDENCE:
            low_conf.append(tid)
        tests.append(ExtractedTest(
            raw_name=row.raw_name, test_id=tid, panel=panel_of().get(tid), value=value,
            unit_raw=row.unit_raw or None, unit=reference.load_tests()[tid].get("unit") if unit_ok else None,
            ref=RefRange(raw=row.ref_raw, low=low, high=high,
                         source="report" if (low is not None or high is not None) else "none"),
            printed_flag=row.printed_flag or None, remark=row.remark or None, page=row.page,
            source_span=row.source_span, confidence=conf))
    missing = missing_expected(extraction.tests)
    if missing:
        warnings.append("expected tests not found: " + ", ".join(missing))
    if dropped:
        warnings.append(f"{len(dropped)} row(s) dropped: value not found in the document")
    rd = parse_report_date(extraction.report_date)
    if extraction.report_date and rd is None:
        warnings.append("report date unreadable or out of range")
    panels = sorted({t.panel for t in tests if t.panel}, key=lambda p: p.value)
    return ValidatedReport(tests=tests, report_date=rd, panels=panels,
                           unrecognised_tests=unrecognised, lab_remarks=extraction.lab_remarks,
                           low_confidence_tests=sorted(set(low_conf)), dropped_rows=dropped,
                           warnings=warnings)
