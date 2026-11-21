"""Deterministic flag, severity and critical checks (PLAN.md section 4)."""
from __future__ import annotations

from lablens import reference
from lablens.schemas import ExtractedTest, Flag, FlaggedTest, RefRange, Severity

_PRINTED = {"h": Flag.HIGH, "high": Flag.HIGH, "hh": Flag.HIGH, "*h": Flag.HIGH,
            "l": Flag.LOW, "low": Flag.LOW, "ll": Flag.LOW, "*l": Flag.LOW,
            "n": Flag.NORMAL, "normal": Flag.NORMAL}


def compute_flag(number: float | None, comparator: str, low: float | None,
                 high: float | None) -> Flag:
    if number is None or (low is None and high is None):
        return Flag.UNKNOWN
    if comparator in ("<", "<="):  # true value is at or below `number`
        if low is not None and number <= low:
            return Flag.LOW
        if low is None and number <= high:
            return Flag.NORMAL
        return Flag.UNKNOWN
    if comparator in (">", ">="):
        if high is not None and number >= high:
            return Flag.HIGH
        if high is None and number >= low:
            return Flag.NORMAL
        return Flag.UNKNOWN
    if low is not None and number < low:
        return Flag.LOW
    if high is not None and number > high:
        return Flag.HIGH
    return Flag.NORMAL


def is_critical(number: float | None, comparator: str, critical: dict | None) -> bool:
    """Checked against critical thresholds only, never the printed range."""
    if number is None or not critical:
        return False
    lo, hi = critical.get("low"), critical.get("high")
    if lo is not None and number <= lo and comparator in ("=", "<", "<="):
        return True
    return hi is not None and number >= hi and comparator in ("=", ">", ">=")


UNIT_WARNING = "unit not recognised: please verify"
FALLBACK_WARNING = "range not printed; standard range used"


def _norm_unit(u: str | None) -> str:
    return "".join((u or "").split()).lower().replace("µ", "u").replace("μ", "u")


def to_canonical(number: float | None, test_id: str | None, unit_raw: str | None,
                 conversions: dict[str, dict] | None = None) -> tuple[float | None, bool]:
    """Return (value in canonical unit, unit_recognised). Missing unit is assumed canonical."""
    if conversions is None:
        conversions = reference.load_unit_conversions()
    conv = conversions.get(test_id or "")
    if conv is None or not unit_raw or not unit_raw.strip():
        return number, True
    u = _norm_unit(unit_raw)
    if u == _norm_unit(conv["unit"]) or u in {_norm_unit(e) for e in conv["equivalent"]}:
        return number, True
    for alt, spec in conv["alt_units"].items():
        if u == _norm_unit(alt):
            return (None if number is None else number / spec["factor"]), True
    return None, False


def compute_severity(flag: Flag, number: float | None, low: float | None,
                     high: float | None, critical: bool = False) -> Severity:
    if critical:
        return Severity.CRITICAL
    if flag in (Flag.NORMAL, Flag.UNKNOWN):
        return Severity(flag.value)
    bound = low if flag is Flag.LOW else high
    if abs(bound) < 1e-9:
        if low is None or high is None or high <= low:
            return Severity.MARKED
        dev = abs(number - bound) / (high - low)
    else:
        dev = abs(number - bound) / abs(bound)
    return Severity.MILD if dev < 0.10 else Severity.MARKED


def normalize_printed_flag(printed: str | None) -> Flag | None:
    return _PRINTED.get(printed.strip().lower()) if printed and printed.strip() else None


def resolve_range(test: ExtractedTest) -> RefRange:
    """Printed range if usable, else the age/sex-independent fallback, else source 'none'."""
    ref = test.ref
    if ref.low is not None or ref.high is not None:
        return ref
    fb = reference.fallback_range(test.test_id)
    if fb is None:
        return RefRange(raw=ref.raw, low=None, high=None, source="none")
    return RefRange(raw=ref.raw, low=fb[0], high=fb[1], source="fallback_table")


def flag_test(test: ExtractedTest, criticals: dict[str, dict] | None = None) -> FlaggedTest:
    if criticals is None:
        criticals = reference.load_critical_values()
    ref = resolve_range(test)
    num, comp = test.value.number, test.value.comparator
    canon, unit_ok = to_canonical(num, test.test_id, test.unit_raw)
    warnings: list[str] = []
    if unit_ok:
        # printed range is in printed units; fallback range and criticals are canonical
        if ref.source == "fallback_table":
            num = canon
            warnings.append(FALLBACK_WARNING)
        flag = compute_flag(num, comp, ref.low, ref.high)
        crit = is_critical(canon, comp, criticals.get(test.test_id or ""))
    else:  # never silently normal: UNKNOWN routes to R5_verify
        flag, crit = Flag.UNKNOWN, False
        warnings.append(UNIT_WARNING)
    severity = compute_severity(flag, num, ref.low, ref.high, crit)
    printed = normalize_printed_flag(test.printed_flag)
    disagrees = printed is not None and flag is not Flag.UNKNOWN and printed is not flag
    return FlaggedTest(**test.model_dump(exclude={"ref"}), ref=ref, flag=flag,
                       severity=severity, is_critical=crit,
                       flag_disagrees_with_printed=disagrees, warnings=warnings)


def flag_tests(tests: list[ExtractedTest]) -> list[FlaggedTest]:
    criticals = reference.load_critical_values()
    return [flag_test(t, criticals) for t in tests]
