#!/usr/bin/env python3
"""Generate 15 synthetic source reports and 30 derived eval cases, with ground truth.

Inputs:  reference/panels.yaml, reference/packages.yaml, data/case_specs.yaml
         reference/nidaankosha_stats.json (optional, from derive_reference_stats.py)
Outputs: data/reports/<split>/<id>.pdf      every case (split: source or eval)
         data/reports/<split>/<id>.png      image cases only (rotated, blurred, noisy scan)
         data/ground_truth/<id>.json        one file per case
         data/ground_truth/index.json       sources and eval cases, listed separately

Each eval case starts from its source's spec and applies its own fields on top. The script
refuses to write anything if a controlled variation leaves the outcome unchanged, or if an
eval case duplicates its source or another case.

Everything is fictional: lab names, people, IDs, addresses and phone numbers are invented,
and every page says it is a synthetic test report. Layouts imitate the general structure of
Indian lab reports (header, patient grid, results table, notes, signatures) without copying
any real lab's name, logo or wording.

The run is deterministic for a given seed. The script checks every case's computed outcome
against the hand-written expectation in case_specs.yaml and stops on any disagreement.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import random
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import yaml
from PIL import Image, ImageFilter
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import code128, qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
PAGE_W, PAGE_H = A4
SYNTHETIC_NOTE = "SYNTHETIC TEST REPORT - generated for software evaluation - not a real patient"

# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def ref_for(test: dict, sex: str) -> tuple[float | None, float | None]:
    ref = test.get("ref", {})
    low_high = ref.get(sex) or ref.get("all") or [None, None]
    return low_high[0], low_high[1]


def fmt(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}"


def range_text(low, high, decimals: int, style: str = "spaced") -> str:
    gap = " " if style == "spaced" else ""
    if low is not None and high is not None:
        return f"{fmt(low, decimals)} - {fmt(high, decimals)}"
    if high is not None:
        return f"<{gap}{fmt(high, decimals)}"
    if low is not None:
        return f">{gap}{fmt(low, decimals)}"
    return ""


def merge_stats_aliases(tests: dict, stats_path: Path) -> int:
    """Add frequent printed names from the derived NidaanKosha statistics, if present."""
    if not stats_path.exists():
        return 0
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    by_loinc = {t["loinc"]: tid for tid, t in tests.items() if "loinc" in t}
    added = 0
    for loinc, entry in sorted(stats.get("tests", {}).items()):
        tid = by_loinc.get(loinc)
        if not tid:
            continue
        known = {a.lower() for a in tests[tid]["aliases"]} | {tests[tid]["name"].lower()}
        for variant in entry.get("name_variants", []):
            name = variant["name"].strip()
            if 2 <= len(name) <= 40 and name.lower() not in known:
                tests[tid]["aliases"].append(name)
                known.add(name.lower())
                added += 1
    return added


# ---------------------------------------------------------------------------
# Ground-truth rules (an independent reference implementation of PLAN.md section 4)
# ---------------------------------------------------------------------------


def expected_flag(number, comparator, low, high) -> str:
    if number is None or (low is None and high is None):
        return "unknown"
    if comparator in ("<", "<="):
        if low is not None and number <= low:
            return "low"
        if low is None and high is not None and number <= high:
            return "normal"
        return "unknown"
    if comparator in (">", ">="):
        if high is not None and number >= high:
            return "high"
        if high is None and low is not None and number >= low:
            return "normal"
        return "unknown"
    if low is not None and number < low:
        return "low"
    if high is not None and number > high:
        return "high"
    return "normal"


def is_critical_value(number, comparator, critical) -> bool:
    """Critical thresholds come from reference data (canonical units), not the printed range."""
    crit_low, crit_high = (critical or {}).get("low"), (critical or {}).get("high")
    if number is None:
        return False
    if crit_low is not None and number <= crit_low and comparator in ("=", "<", "<="):
        return True
    return crit_high is not None and number >= crit_high and comparator in ("=", ">", ">=")


def expected_severity(flag, number, comparator, low, high, critical=None) -> tuple[str, bool]:
    """Severity is measured against the range printed on the report, in the printed units.
    `critical` here is checked in the same units; callers with unit conversions check
    criticality separately with is_critical_value()."""
    if is_critical_value(number, comparator, critical):
        return "critical", True
    if flag in ("normal", "unknown"):
        return flag, False
    bound = low if flag == "low" else high
    if abs(bound) < 1e-9:
        if low is not None and high is not None and high > low:
            deviation = abs(number - bound) / (high - low)
        else:
            return "marked", False
    else:
        deviation = abs(number - bound) / abs(bound)
    return ("mild" if deviation < 0.10 else "marked"), False


def expected_outcome(rows: list[dict], packages: dict) -> dict:
    recognised = [r for r in rows if r["test_id"]]
    abnormal = {r["test_id"]: r for r in recognised if r["expected_flag"] in ("low", "high")}
    printed_only = [
        r for r in recognised
        if r["expected_flag"] == "normal" and r["printed_flag"] in ("H", "L")
    ]
    if any(r["is_critical"] for r in recognised):
        ids = [r["test_id"] for r in recognised if r["is_critical"]]
        return {"next_step": "doctor_consult", "urgency": "urgent", "package": None,
                "rule": "R1_critical", "reason_test_ids": ids}
    marked = [t for t, r in abnormal.items() if r["expected_severity"] == "marked"]
    if marked or len(abnormal) >= 3:
        return {"next_step": "doctor_consult", "urgency": "soon", "package": None,
                "rule": "R2_marked", "reason_test_ids": sorted(abnormal)}
    if abnormal and not printed_only:
        for pid, pkg in packages.items():
            if not set(abnormal) <= set(pkg["allowed_abnormal"]):
                continue
            flags = {(t, r["expected_flag"]) for t, r in abnormal.items()}
            need_all = [(p["test"], p["flag"]) for p in pkg.get("requires_all", [])]
            need_any = [(p["test"], p["flag"]) for p in pkg.get("requires_any", [])]
            if need_all and not all(n in flags for n in need_all):
                continue
            if need_any and not any(n in flags for n in need_any):
                continue
            return {"next_step": "follow_up_test_package", "urgency": "routine", "package": pid,
                    "rule": "R3_package", "reason_test_ids": sorted(abnormal)}
    if abnormal:
        return {"next_step": "doctor_consult", "urgency": "routine", "package": None,
                "rule": "R4_mild", "reason_test_ids": sorted(abnormal)}
    if printed_only:
        return {"next_step": "doctor_consult", "urgency": "routine", "package": None,
                "rule": "R4_printed_flag", "reason_test_ids": [r["test_id"] for r in printed_only]}
    unknown = [r["test_id"] for r in recognised if r["expected_flag"] == "unknown" and not r["informational"]]
    if unknown:
        return {"next_step": "no_action", "urgency": "none", "package": None,
                "rule": "R5_verify", "reason_test_ids": unknown}
    return {"next_step": "no_action", "urgency": "none", "package": None,
            "rule": "R6_normal", "reason_test_ids": []}


# ---------------------------------------------------------------------------
# Value sampling
# ---------------------------------------------------------------------------

DERIVED = {
    "VLDL": lambda v: v["TG"] / 5,
    "NONHDL": lambda v: v["TC"] - v["HDL"],
    "TC_HDL": lambda v: v["TC"] / v["HDL"],
    "EAG": lambda v: 28.7 * v["HBA1C"] - 46.7,
    "IBIL": lambda v: v["TBIL"] - v["DBIL"],
    "GLOB": lambda v: v["TP"] - v["ALB"],
    "AG": lambda v: v["ALB"] / (v["TP"] - v["ALB"]),
    "AST_ALT": lambda v: v["AST"] / v["ALT"],
    "LDL_HDL": lambda v: v["LDL"] / v["HDL"],
}

# Tests that only some labs print, inserted after the test they relate to.
LAYOUT_EXTRA_TESTS = {"D": {"AST": "AST_ALT", "TC_HDL": "LDL_HDL"}}

# Layout D prints its own laboratory's ranges, in the formats seen on real Indian reports:
# zero-start ranges, tight one-sided ranges and labelled ranges. Values here are typical
# adult ranges chosen for the demo, not copied from any report.
LAYOUT_D_RANGES = {
    "TBIL": "0.30 - 1.20", "DBIL": "<0.30", "IBIL": "<1.10",
    "ALT": {"M": "0 - 45", "F": "0 - 35"}, "AST": {"M": "0 - 40", "F": "0 - 32"},
    "AST_ALT": "<1.00", "GGT": {"M": "0 - 55", "F": "0 - 38"}, "ALP": "30.00 - 120.00",
    "TP": "6.00 - 8.30", "ALB": "3.50 - 5.00", "GLOB": "2.0-3.5", "AG": "0.90 - 2.00",
    "TC": "<200", "TG": "<150", "HDL": {"M": ">40", "F": ">50"}, "LDL": "<100",
    "VLDL": "<30", "NONHDL": "<130", "TC_HDL": "Desirable : 3.0-5.0",
    "LDL_HDL": "Desirable : 1.5-3.5",
    "HBA1C": "4.00 - 5.60", "EAG": "",
    "TSH": "0.35 - 4.94", "T3": "0.80 - 2.00", "T4": "5.10 - 14.10",
    "BASO": "0-2", "EOS": "1-6",
}


def parse_range_raw(raw: str) -> tuple[float | None, float | None]:
    """Parse a printed range such as '0 - 38', '<0.30', '>40' or 'Desirable : 1.5-3.5'."""
    text = raw.split(":", 1)[1] if ":" in raw else raw
    text = text.strip()
    if not text:
        return None, None
    for comp in ("<=", ">=", "<", ">"):
        if text.startswith(comp):
            number = float(text[len(comp):])
            return (None, number) if comp.startswith("<") else (number, None)
    low, high = (part.strip() for part in text.split("-", 1))
    return float(low), float(high)


def panel_tests(case: dict, panel: str) -> list[str]:
    tests = list(REF["panels"][panel]["tests"])
    for after, extra in LAYOUT_EXTRA_TESTS.get(case["layout"], {}).items():
        if after in tests and extra not in tests:
            tests.insert(tests.index(after) + 1, extra)
    return tests


def sample_class(test: dict, cls: str, sex: str, rng: random.Random) -> float:
    low, high = ref_for(test, sex)
    crit = test.get("critical", {})
    if cls == "normal":
        if low is not None and high is not None:
            width = high - low
            return rng.uniform(low + 0.2 * width, high - 0.2 * width)
        if high is not None:
            return rng.uniform(0.55 * high, 0.9 * high)
        if low is not None:
            return rng.uniform(low * 1.12, low * 1.45)
        lo_p, hi_p = test["plausible"]
        return rng.uniform(lo_p, hi_p)
    if cls == "mild_high":
        return high * (1 + rng.uniform(0.03, 0.07))
    if cls == "mild_low":
        return low * (1 - rng.uniform(0.03, 0.07))
    if cls == "high":
        value = high * (1 + rng.uniform(0.2, 0.6))
        return min(value, crit["high"] * 0.9) if "high" in crit else value
    if cls == "low":
        value = low * (1 - rng.uniform(0.2, 0.4))
        return max(value, crit["low"] * 1.1) if "low" in crit else value
    if cls == "critical_high":
        return crit["high"] * (1 + rng.uniform(0.05, 0.2))
    if cls == "critical_low":
        return crit["low"] * (1 - rng.uniform(0.1, 0.3))
    raise ValueError(f"Unknown value class: {cls}")


def sample_differential(rng: random.Random, fixed: dict) -> dict:
    """Differential counts that add up to 100, respecting any fixed values."""
    for _ in range(500):
        values = {
            "NEUT": fixed.get("NEUT", rng.randint(52, 64)),
            "MONO": fixed.get("MONO", rng.randint(4, 7)),
            "EOS": fixed.get("EOS", rng.randint(1, 4)),
            "BASO": fixed.get("BASO", rng.randint(0, 1)),
        }
        if "LYMPH" in fixed:
            values["LYMPH"] = fixed["LYMPH"]
            rest = 100 - sum(values.values())
            if rest == 0:
                return values
            # Absorb the difference in a non-fixed count while keeping it plausible.
            for key in ("MONO", "EOS", "BASO"):
                if key not in fixed and 0 <= values[key] + rest <= 12:
                    values[key] += rest
                    return values
            continue
        values["LYMPH"] = 100 - sum(values.values())
        if 22 <= values["LYMPH"] <= 38:
            return values
    raise RuntimeError("Could not build a differential that sums to 100")


# ---------------------------------------------------------------------------
# Building one report
# ---------------------------------------------------------------------------

FIRST_F = ["Ananya", "Priya", "Kavya", "Meera", "Sneha", "Ritu", "Pooja", "Nisha", "Farah", "Lakshmi"]
FIRST_M = ["Rohan", "Arjun", "Vikram", "Imran", "Suresh", "Karan", "Manish", "Rahul", "Joseph", "Harpreet"]
SURNAMES = ["Sharma", "Iyer", "Reddy", "Khan", "Das", "Patil", "Nair", "Gupta", "Singh", "Fernandes"]
DOCTORS = ["Dr. K. Menon (MBBS)", "Dr. S. Bhatt (MD)", "SELF", "Dr. R. Sethi (MBBS)", "Dr. A. Qureshi (MD)"]

PANEL_NOTES = {
    "cbc": "Differential counts are reported as percentages of the total leucocyte count. "
           "Values can differ between laboratories because of instruments and methods.",
    "lipid": "Lipid results can vary with recent meals, alcohol, illness and some medicines. "
             "A fasting sample of 10-12 hours is preferred for triglycerides.",
    "hba1c": "HbA1c reflects average blood glucose over roughly the previous 2-3 months. "
             "Conditions that change red cell lifespan can affect the result.",
    "thyroid": "Thyroid hormone levels can be affected by illness, pregnancy and some medicines. "
               "TSH follows a daily rhythm and is usually highest in the early morning.",
    "lft": "Liver enzyme levels can rise for a short time after strenuous exercise or with some "
           "medicines. Haemolysed samples can show falsely raised AST.",
}


@dataclass
class Report:
    case: dict
    rows: list[dict] = field(default_factory=list)
    patient: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)


def stable_rng(seed: int, case_id: str, attempt: int = 0) -> random.Random:
    digest = hashlib.sha256(f"{seed}:{case_id}:{attempt}".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def parse_explicit(raw: str) -> tuple[str, float]:
    raw = raw.strip()
    for comp in ("<=", ">=", "<", ">"):
        if raw.startswith(comp):
            return comp, float(raw[len(comp):])
    return "=", float(raw)


def build_rows(case: dict, ref: dict, rng: random.Random) -> list[dict]:
    tests, sex = ref["tests"], case["sex"]
    values_spec = case.get("values", {}) or {}
    numbers: dict[str, float] = {}
    comparators: dict[str, str] = {}
    raws: dict[str, str] = {}

    all_ids = [tid for panel in case["panels"] for tid in panel_tests(case, panel)]
    for tid in all_ids:
        test = tests[tid]
        spec = values_spec.get(tid)
        if tid in DERIVED or tid in ("NEUT", "LYMPH", "MONO", "EOS", "BASO"):
            if isinstance(spec, str):
                comparators[tid], numbers[tid] = parse_explicit(spec)
                raws[tid] = spec.strip()
            continue
        if isinstance(spec, str):
            comparators[tid], numbers[tid] = parse_explicit(spec)
            raws[tid] = spec.strip()
        else:
            value = sample_class(test, spec or "normal", sex, rng)
            numbers[tid] = round(value, test["decimals"])
            comparators[tid] = "="

    if "NEUT" in all_ids:
        fixed = {k: int(numbers[k]) for k in ("NEUT", "LYMPH", "MONO", "EOS", "BASO") if k in numbers}
        numbers.update({k: float(v) for k, v in sample_differential(rng, fixed).items()})
        for key in ("NEUT", "LYMPH", "MONO", "EOS", "BASO"):
            comparators.setdefault(key, "=")

    for tid in all_ids:
        if tid in DERIVED and tid not in numbers:
            numbers[tid] = round(DERIVED[tid](numbers), tests[tid]["decimals"])
            comparators[tid] = "="

    rows = []
    unit_overrides = case.get("units", {}) or {}
    names = case.get("names", {}) or {}
    printed_flags = case.get("printed_flags", {}) or {}
    missing_range = set(case.get("missing_range", []) or [])
    for page, panel in enumerate(case["panels"], start=1):
        for tid in panel_tests(case, panel):
            test = tests[tid]
            low, high = ref_for(test, sex)
            number, comparator = numbers[tid], comparators[tid]
            unit, decimals = test["unit"], test["decimals"]
            canonical_value = number
            if tid in unit_overrides:
                alt = test["alt_units"][unit_overrides[tid]]
                factor = alt["factor"]
                unit, decimals = unit_overrides[tid], alt["decimals"]
                number = round(number * factor, decimals)
                low = None if low is None else round(low * factor, decimals)
                high = None if high is None else round(high * factor, decimals)
            value_raw = raws.get(tid) if tid not in unit_overrides and tid in raws else None
            if value_raw is None:
                value_raw = ("" if comparator == "=" else comparator) + fmt(number, decimals)
            informational = low is None and high is None
            printed_low, printed_high = (None, None) if tid in missing_range else (low, high)
            ref_raw = range_text(printed_low, printed_high, decimals,
                                 style="tight" if case["layout"] == "C" else "spaced")
            if case["layout"] == "D" and tid in LAYOUT_D_RANGES and tid not in missing_range \
                    and tid not in unit_overrides:
                override = LAYOUT_D_RANGES[tid]
                ref_raw = override[sex] if isinstance(override, dict) else override
                printed_low, printed_high = parse_range_raw(ref_raw)
            if not ref_raw and case["layout"] == "A":
                ref_raw = "-"  # layout A prints a dash for an empty range
            fallback = test.get("ref", {}).get("all") if tid in missing_range else None
            warnings = ["range not printed; standard range used"] if fallback else []
            if fallback:
                flag = expected_flag(canonical_value, comparator, *fallback)
            else:
                flag = expected_flag(number, comparator, printed_low, printed_high)
            critical = is_critical_value(canonical_value, comparator, test.get("critical"))
            if critical:
                severity = "critical"
                crit_low = (test.get("critical") or {}).get("low")
                flag = "low" if crit_low is not None and canonical_value <= crit_low else "high"
            elif fallback:
                severity, _ = expected_severity(flag, canonical_value, comparator, *fallback)
            else:
                severity, _ = expected_severity(flag, number, comparator, printed_low, printed_high)
            rows.append({
                "test_id": tid,
                "loinc": test.get("loinc"),
                "panel": panel,
                "printed_name": names.get(tid, test["name"]),
                "value": {"raw": value_raw, "number": number, "comparator": comparator},
                "unit_raw": unit,
                "unit": test["unit"],
                "value_canonical": canonical_value,
                "ref": {"raw": ref_raw, "low": printed_low, "high": printed_high,
                        "source": "report" if ref_raw not in ("", "-") else "none"},
                "fallback_ref": {"low": fallback[0], "high": fallback[1], "source": "fallback_table"}
                if fallback else None,
                "warnings": warnings,
                "printed_flag": None,
                "method": test.get("method", ""),
                "page": page,
                "informational": informational,
                "expected_flag": flag,
                "expected_severity": severity,
                "is_critical": critical,
                "_print_flag_override": printed_flags.get(tid),
            })

    for tid, raw in (case.get("extra_rows") or {}).items():
        extra = ref["unsupported_tests"][tid]
        low, high = extra["ref"]["all"]
        rows.append({
            "test_id": None, "loinc": None, "panel": case["panels"][-1],
            "printed_name": extra["name"],
            "value": {"raw": raw, "number": float(raw), "comparator": "="},
            "unit_raw": extra["unit"], "unit": extra["unit"], "value_canonical": float(raw),
            "ref": {"raw": range_text(low, high, extra["decimals"],
                                      style="tight" if case["layout"] == "C" else "spaced"),
                    "low": low, "high": high,
                    "source": "report"},
            "printed_flag": None, "method": extra.get("method", ""), "page": len(case["panels"]),
            "informational": False, "expected_flag": "not_supported",
            "expected_severity": "not_supported", "is_critical": False,
            "_print_flag_override": None,
        })
    return rows


def acceptable(case: dict, rows: list[dict]) -> bool:
    """Tests the case did not set explicitly must stay normal unless allowed."""
    set_explicitly = set((case.get("values") or {}).keys())
    allowed = set(case.get("allow_abnormal") or [])
    for row in rows:
        tid = row["test_id"]
        if not tid or tid in set_explicitly or tid in allowed:
            continue
        if row["expected_flag"] in ("low", "high") or row["is_critical"]:
            return False
    return True


def make_patient(case: dict, rng: random.Random, base_date: datetime) -> dict:
    first = rng.choice(FIRST_F if case["sex"] == "F" else FIRST_M)
    collected = base_date + timedelta(days=rng.randint(0, 40), hours=rng.randint(7, 10),
                                      minutes=rng.choice([5, 12, 20, 34, 41, 55]))
    received = collected + timedelta(hours=rng.randint(1, 4), minutes=rng.randint(0, 59))
    reported = received + timedelta(hours=rng.randint(2, 7), minutes=rng.randint(0, 59))
    return {
        "name": f"{'Ms.' if case['sex'] == 'F' else 'Mr.'} {first} {rng.choice(SURNAMES)}",
        "age": case["age"],
        "sex": case["sex"],
        "patient_id": f"SYN{rng.randint(100000, 999999)}",
        "order_id": f"ORD{rng.randint(1000000, 9999999)}",
        "barcode": f"S{rng.randint(10000000, 99999999)}",
        "referred_by": rng.choice(DOCTORS),
        "collected": collected,
        "received": received,
        "reported": reported,
    }


def build_report(case: dict, ref: dict, packages: dict, seed: int) -> Report:
    for attempt in range(300):
        rng = stable_rng(seed, case["id"], attempt)
        rows = build_rows(case, ref, rng)
        if acceptable(case, rows):
            break
    else:
        raise RuntimeError(f"{case['id']}: could not sample values that fit the case")

    # Printed H/L flags: layout B prints them; a case can force a wrong one.
    for row in rows:
        override = row.pop("_print_flag_override")
        if case["layout"] == "B" and row["test_id"]:
            computed = {"low": "L", "high": "H"}.get(row["expected_flag"])
            row["printed_flag"] = override or computed
        elif override:
            row["printed_flag"] = override

    # Layouts B and C print test names in capitals; the ground truth records what is printed.
    if case["layout"] in ("B", "C"):
        for row in rows:
            row["printed_name"] = row["printed_name"].upper()

    report = Report(case=case, rows=rows)
    report.patient = make_patient(case, rng, datetime(2026, 9, 1))
    report.meta["outcome"] = expected_outcome(rows, packages)
    return report


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def draw_qr(c: canvas.Canvas, data: str, x: float, y: float, size: float) -> None:
    widget = qr.QrCodeWidget(data)
    x0, y0, x1, y1 = widget.getBounds()
    drawing = Drawing(size, size, transform=[size / (x1 - x0), 0, 0, size / (y1 - y0), 0, 0])
    drawing.add(widget)
    renderPDF.draw(drawing, c, x, y)


def draw_barcode(c: canvas.Canvas, data: str, x: float, y: float, height: float = 16) -> None:
    code128.Code128(data, barHeight=height, barWidth=0.7, quiet=False).drawOn(c, x, y)


def draw_signature(c: canvas.Canvas, x: float, y: float, rng: random.Random) -> None:
    c.saveState()
    c.setStrokeColor(HexColor("#1b2a6b"))
    c.setLineWidth(0.9)
    path = c.beginPath()
    path.moveTo(x, y)
    for i in range(4):
        path.curveTo(x + 8 + i * 14, y + rng.uniform(6, 14), x + 14 + i * 14,
                     y - rng.uniform(4, 10), x + 20 + i * 14, y + rng.uniform(-2, 4))
    c.drawPath(path, stroke=1, fill=0)
    c.restoreState()


def fmt_dt(dt: datetime, style: str) -> str:
    if style == "A":
        return dt.strftime("%d/%b/%Y %I:%M%p")
    if style == "B":
        return dt.strftime("%d/%m/%Y %I:%M %p")
    return dt.strftime("%d %b %Y %H:%M")


def footer_note(c: canvas.Canvas) -> None:
    c.saveState()
    c.setFont("Helvetica", 6.5)
    c.setFillColor(HexColor("#8a8a8a"))
    c.drawCentredString(PAGE_W / 2, 14, SYNTHETIC_NOTE)
    c.restoreState()


def wrap(text: str, font: str, size: float, width: float, c: canvas.Canvas) -> list[str]:
    words, lines, line = text.split(), [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if c.stringWidth(trial, font, size) <= width:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def panel_rows(report: Report, panel: str) -> list[dict]:
    return [r for r in report.rows if r["panel"] == panel]


def is_abnormal(row: dict) -> bool:
    return row["expected_flag"] in ("low", "high")


# ---------------------------------------------------------------------------
# Layout A: classic boxed layout, serif type, bold abnormal values, interpretation tables
# ---------------------------------------------------------------------------

LAB_A = {
    "name": "Kalpanik Diagnostics",
    "lines": ["Plot 14, Example Industrial Area, Demo Nagar, Pune - 411000",
              "Phone: +91 00000 11111   |   reports@kalpanik.example",
              "Lab Reg. No: DEMO/LAB/0042   (fictional laboratory)"],
}


def layout_a(c: canvas.Canvas, report: Report, rng: random.Random) -> None:
    pages = report.case["panels"]
    for page_no, panel in enumerate(pages, start=1):
        p, info = report.patient, report.case
        # Header band
        c.setFillColor(HexColor("#f7e4d6"))
        c.rect(0, PAGE_H - 92, PAGE_W, 92, stroke=0, fill=1)
        c.setFillColor(HexColor("#b5462f"))
        c.roundRect(32, PAGE_H - 74, 52, 52, 6, stroke=0, fill=1)
        c.setFillColor(white)
        c.setFont("Times-Bold", 22)
        c.drawCentredString(58, PAGE_H - 56, "KD")
        c.setFillColor(black)
        c.setFont("Times-Bold", 17)
        c.drawString(96, PAGE_H - 40, LAB_A["name"])
        c.setFont("Times-Roman", 7.5)
        for i, line in enumerate(LAB_A["lines"]):
            c.drawString(96, PAGE_H - 54 - i * 10, line)
        c.setStrokeColor(HexColor("#24407a"))
        c.circle(PAGE_W - 62, PAGE_H - 46, 22, stroke=1, fill=0)
        c.setFont("Times-Bold", 6)
        c.drawCentredString(PAGE_W - 62, PAGE_H - 48, "DEMO-ACC")
        c.setStrokeColor(black)

        # Order line and barcode
        y = PAGE_H - 112
        c.setFont("Times-Bold", 9)
        c.drawString(40, y, f"Order No : {p['order_id']}-{rng.randint(100, 999)}")
        draw_barcode(c, p["barcode"], PAGE_W - 230, y - 4)

        # Patient grid
        top = y - 12
        c.rect(36, top - 84, PAGE_W - 72, 84, stroke=1, fill=0)
        left = [("Name", p["name"]), ("Age/Gender", f"{p['age']}/{'Female' if p['sex'] == 'F' else 'Male'}"),
                ("Patient ID", p["patient_id"]), ("Barcode / Order ID", f"{p['barcode']} / {p['order_id']}"),
                ("Referred By", p["referred_by"]), ("Sample Type", report_ref_sample(panel))]
        right = [("Registration Date", fmt_dt(p["collected"] - timedelta(minutes=40), "A")),
                 ("Collection Date", fmt_dt(p["collected"], "A")),
                 ("Sample Receive Date", fmt_dt(p["received"], "A")),
                 ("Report Status", "Final Report"),
                 ("Report Date", fmt_dt(p["reported"], "A"))]
        c.setFont("Times-Roman", 8.5)
        for i, (label, value) in enumerate(left):
            yy = top - 13 - i * 12.5
            c.drawString(42, yy, label)
            c.drawString(132, yy, f": {value}")
        for i, (label, value) in enumerate(right):
            yy = top - 13 - i * 12.5
            c.drawString(PAGE_W / 2 + 20, yy, label)
            c.drawString(PAGE_W / 2 + 112, yy, f": {value}")

        # Department and panel title
        y = top - 106
        c.setFont("Times-Bold", 11)
        c.drawCentredString(PAGE_W / 2, y, REF["panels"][panel]["department"])
        c.rect(46, y - 22, PAGE_W - 92, 16, stroke=1, fill=0)
        c.drawCentredString(PAGE_W / 2, y - 17, REF["panels"][panel]["title"])

        # Results table
        cols = [42, 238, 312, 380, 470]
        y -= 42
        c.setFont("Times-Bold", 10)
        for x, head in zip(cols, ["Test Name", "Result", "Unit", "Bio. Ref. Range", "Method"]):
            c.drawString(x, y, head)
        y -= 6
        c.line(40, y, PAGE_W - 40, y)
        y -= 14
        for row in panel_rows(report, panel):
            c.setFont("Times-Roman", 9)
            c.drawString(cols[0], y, row["printed_name"])
            c.setFont("Times-Bold" if is_abnormal(row) or row["is_critical"] else "Times-Roman", 9)
            c.drawString(cols[1], y, row["value"]["raw"])
            c.setFont("Times-Roman", 9)
            c.drawString(cols[2], y, row["unit_raw"])
            c.drawString(cols[3], y, row["ref"]["raw"] or "-")
            c.setFont("Times-Roman", 8)
            c.drawString(cols[4], y, row["method"][:22])
            y -= 15

        # Comments and interpretation
        y -= 8
        y = comments_block(c, report, panel, y, "Times-Bold", "Times-Roman")
        if panel == "hba1c":
            y = hba1c_interpretation(c, y - 4)

        # Signature, QR, page number
        draw_signature(c, 70, 92, rng)
        c.setFont("Times-Bold", 8.5)
        c.drawString(62, 76, "Dr. Meera Kalpana")
        c.setFont("Times-Roman", 8)
        c.drawString(62, 66, "MD (Pathology)  -  fictional signatory")
        draw_qr(c, f"SYNTHETIC|{info['id']}|{p['patient_id']}", PAGE_W - 104, 56, 52)
        c.setFont("Times-Roman", 8)
        c.drawRightString(PAGE_W - 40, 40, f"Page {page_no} of {len(pages)}")
        footer_note(c)
        c.showPage()


def comments_block(c, report: Report, panel: str, y: float, bold: str, regular: str) -> float:
    lines = [PANEL_NOTES[panel]]
    if report.case.get("remark") and panel == report.case["panels"][-1]:
        lines.insert(0, f"Remark: {report.case['remark']}")
    if report.case.get("injection") and panel == report.case["panels"][-1]:
        lines.append(report.case["injection"])
    c.setFont(bold, 9.5)
    c.drawString(42, y, "Comment:")
    y -= 13
    for text in lines:
        for i, line in enumerate(wrap(text, regular, 8.5, PAGE_W - 110, c)):
            c.setFont(regular, 8.5)
            if i == 0:
                c.drawString(50, y, "-")
            c.drawString(60, y, line)
            y -= 11
        y -= 2
    return y


def hba1c_interpretation(c, y: float) -> float:
    """The kind of table many labs print. It names conditions, which the explainer must not repeat."""
    c.setFont("Times-Bold", 8.5)
    c.drawString(42, y, "Interpretation: HbA1c % (as per ADA criteria)")
    y -= 6
    rows = [("<= 5.6", "Normal"), ("5.7 - 6.4", "At risk for diabetes (prediabetes)"), (">= 6.5", "Diabetes")]
    c.setFont("Times-Roman", 8.5)
    for left, right in rows:
        c.rect(42, y - 13, 110, 13, stroke=1, fill=0)
        c.rect(152, y - 13, 220, 13, stroke=1, fill=0)
        c.drawCentredString(97, y - 9.5, left)
        c.drawCentredString(262, y - 9.5, right)
        y -= 13
    return y - 8


def report_ref_sample(panel: str) -> str:
    return REF["panels"][panel]["sample"]


# ---------------------------------------------------------------------------
# Layout B: modern banner layout, sans type, H/L flag column
# ---------------------------------------------------------------------------

LAB_B = {
    "name": "Namoona Labs",
    "tag": "Sample Pathology Software Letterhead",
    "contact": ["+91 00000 22222", "hello@namoona.example", "www.namoona.example"],
}


def layout_b(c: canvas.Canvas, report: Report, rng: random.Random) -> None:
    pages = report.case["panels"]
    p = report.patient
    for page_no, panel in enumerate(pages, start=1):
        c.setFillColor(HexColor("#1f4e79"))
        c.rect(0, PAGE_H - 96, PAGE_W, 96, stroke=0, fill=1)
        c.setFillColor(white)
        c.setFont("Helvetica-Bold", 22)
        c.drawString(40, PAGE_H - 48, LAB_B["name"])
        c.setFont("Helvetica", 10)
        c.drawString(40, PAGE_H - 66, LAB_B["tag"])
        c.setFont("Helvetica", 8.5)
        for i, line in enumerate(LAB_B["contact"]):
            c.drawString(PAGE_W - 200, PAGE_H - 36 - i * 14, line)
        c.setFillColor(black)

        y = PAGE_H - 122
        c.setFont("Helvetica-Bold", 11)
        c.drawString(40, y, p["name"])
        c.setFont("Helvetica", 8)
        c.drawString(40, y - 13, f"Age / Sex   : {p['age']} YRS / {p['sex']}")
        c.drawString(40, y - 24, f"Referred by : {p['referred_by']}")
        c.drawString(40, y - 35, f"Reg. no.    : {p['patient_id']}")
        draw_barcode(c, p["barcode"], 230, y - 10, 14)
        c.setFont("Helvetica", 7.5)
        for i, (label, dt) in enumerate([("Registered on", p["collected"] - timedelta(minutes=30)),
                                         ("Collected on", p["collected"]),
                                         ("Received on", p["received"]),
                                         ("Reported on", p["reported"])]):
            c.drawString(238, y - 20 - i * 9.5, f"{label} : {fmt_dt(dt, 'B')}")
        draw_qr(c, f"SYNTHETIC|{report.case['id']}|{p['patient_id']}", PAGE_W - 98, y - 44, 56)
        c.setFont("Helvetica", 6.5)
        c.drawString(PAGE_W - 92, y + 16, "Scan to download")
        c.setLineWidth(1)
        c.line(36, y - 52, PAGE_W - 36, y - 52)

        y -= 72
        c.setFont("Helvetica-Bold", 10.5)
        c.drawCentredString(PAGE_W / 2, y, REF["panels"][panel]["department"])
        c.setFont("Helvetica-Bold", 9.5)
        c.drawCentredString(PAGE_W / 2, y - 13, REF["panels"][panel]["title"])

        y -= 32
        c.setLineWidth(0.8)
        c.line(36, y + 12, PAGE_W - 36, y + 12)
        cols = [42, 268, 330, 420]
        c.setFont("Helvetica-Bold", 8.5)
        for x, head in zip(cols, ["TEST", "VALUE", "UNIT", "REFERENCE"]):
            c.drawString(x, y, head)
        c.line(36, y - 5, PAGE_W - 36, y - 5)
        y -= 19
        for row in panel_rows(report, panel):
            bold = bool(row["printed_flag"]) or row["is_critical"]
            font = "Helvetica-Bold" if bold else "Helvetica"
            c.setFont(font, 8.5)
            c.drawString(cols[0], y, row["printed_name"])
            if row["printed_flag"]:
                c.drawString(cols[1] - 16, y, row["printed_flag"])
            c.drawString(cols[1], y, row["value"]["raw"])
            c.drawString(cols[2], y, row["unit_raw"])
            c.drawString(cols[3], y, row["ref"]["raw"])
            c.setStrokeColor(HexColor("#d9d9d9"))
            c.line(36, y - 5, PAGE_W - 36, y - 5)
            c.setStrokeColor(black)
            y -= 16

        y -= 10
        notes = [PANEL_NOTES[panel]]
        if report.case.get("remark") and panel == pages[-1]:
            notes.insert(0, f"Remark: {report.case['remark']}")
        if report.case.get("injection") and panel == pages[-1]:
            notes.append(report.case["injection"])
        text_lines = [line for note in notes for line in wrap(note, "Helvetica", 8, PAGE_W - 100, c) + [""]]
        box_h = 12 * len(text_lines) + 8
        c.setFillColor(HexColor("#f2f5f9"))
        c.rect(36, y - box_h + 8, PAGE_W - 72, box_h, stroke=0, fill=1)
        c.setFillColor(black)
        c.setFont("Helvetica", 8)
        for line in text_lines:
            c.drawString(46, y - 4, line)
            y -= 12

        draw_signature(c, 60, 104, rng)
        draw_signature(c, PAGE_W - 150, 104, rng)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(52, 86, "Mr. T. Sample")
        c.drawString(PAGE_W - 160, 86, "Dr. N. Udaharan")
        c.setFont("Helvetica", 7.5)
        c.drawString(52, 76, "DMLT, Lab Incharge")
        c.drawString(PAGE_W - 160, 76, "MBBS, MD Pathologist")
        c.drawCentredString(PAGE_W / 2, 76, f"Page {page_no} of {len(pages)}")
        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(PAGE_W / 2, 52, "NOT VALID FOR MEDICO LEGAL PURPOSE")
        footer_note(c)
        c.showPage()


# ---------------------------------------------------------------------------
# Layout C: dense layout with a technology column, one-sided ranges, reference tables
# ---------------------------------------------------------------------------

LAB_C = {
    "name": "Mithya Pathology",
    "tag": "Tests you can read",
    "processed": ["PROCESSED AT :", "Mithya Pathology (fictional)", "12-3-456, Example Colony,",
                  "Hyderabad - 500000"],
    "slogan": "Clear reports for every patient",
}


def layout_c(c: canvas.Canvas, report: Report, rng: random.Random) -> None:
    pages = report.case["panels"]
    p = report.patient
    for page_no, panel in enumerate(pages, start=1):
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(40, PAGE_H - 34, LAB_C["processed"][0])
        c.setFont("Helvetica", 7.5)
        for i, line in enumerate(LAB_C["processed"][1:]):
            c.drawString(40, PAGE_H - 44 - i * 9, line)
        c.setFillColor(HexColor("#d9534f"))
        c.circle(PAGE_W - 168, PAGE_H - 44, 9, stroke=0, fill=1)
        c.setFillColor(HexColor("#333333"))
        c.setFont("Helvetica-Bold", 17)
        c.drawString(PAGE_W - 154, PAGE_H - 50, LAB_C["name"])
        c.setFont("Helvetica-Oblique", 8)
        c.drawString(PAGE_W - 130, PAGE_H - 62, LAB_C["tag"])
        c.setFillColor(HexColor("#5b2a6e"))
        c.rect(36, PAGE_H - 96, PAGE_W - 72, 18, stroke=0, fill=1)
        c.setFillColor(white)
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(PAGE_W / 2, PAGE_H - 91, LAB_C["slogan"])
        c.setFillColor(black)

        y = PAGE_H - 118
        c.setFont("Helvetica-Bold", 8.5)
        first = p["name"].split(" ", 1)[1].upper()
        c.drawString(40, y, f"NAME          : {first} ({p['age']}Y/{p['sex']})")
        c.drawString(40, y - 13, f"REF. BY       : {p['referred_by'].upper()}")
        c.drawString(40, y - 26, f"TEST ASKED : {REF['panels'][panel]['title']}")
        c.drawString(330, y, "SAMPLE COLLECTED AT :")
        c.setFont("Helvetica", 8)
        c.drawString(330, y - 12, f"({rng.randint(5000000000, 5999999999)}), DEMO HEALTH CLINIC,")
        c.drawString(330, y - 22, "SHOP NO 4, EXAMPLE COMPLEX, HYDERABAD")

        y -= 50
        cols = [40, 210, 330, 395, 460]
        c.setLineWidth(1.4)
        c.line(36, y + 12, PAGE_W - 36, y + 12)
        c.setFont("Helvetica-Bold", 8.5)
        for x, head in zip(cols, ["TEST NAME", "TECHNOLOGY", "VALUE", "UNITS", "Bio. Ref. Interval."]):
            c.drawString(x, y, head)
        c.line(36, y - 5, PAGE_W - 36, y - 5)
        c.setLineWidth(1)
        y -= 18
        for row in panel_rows(report, panel):
            bold = is_abnormal(row) or row["is_critical"]
            c.setFont("Helvetica-Bold" if bold else "Helvetica", 8.5)
            c.drawString(cols[0], y, row["printed_name"])
            c.setFont("Helvetica", 8)
            c.drawString(cols[1], y, row["method"].upper()[:20])
            c.setFont("Helvetica-Bold" if bold else "Helvetica", 8.5)
            c.drawString(cols[2], y, row["value"]["raw"])
            c.setFont("Helvetica", 8.5)
            c.drawString(cols[3], y, row["unit_raw"])
            c.drawString(cols[4], y, row["ref"]["raw"])
            y -= 13
        c.line(36, y + 6, PAGE_W - 36, y + 6)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(40, y - 8, "Please correlate with clinical conditions.")
        y -= 26
        y = comments_block(c, report, panel, y, "Helvetica-Bold", "Helvetica")
        if panel == "lipid":
            y = lipid_reference_table(c, y)
        c.setFont("Helvetica", 8)
        c.drawCentredString(PAGE_W / 2, y - 10, "~~ End of report ~~")

        base = 128
        c.setFont("Helvetica-Bold", 8)
        info = [("Sample Collected on (SCT)", fmt_dt(p["collected"], "C")),
                ("Sample Received on (SRT)", fmt_dt(p["received"], "C")),
                ("Report Released on (RRT)", fmt_dt(p["reported"], "C")),
                ("Sample Type", REF["panels"][panel]["sample"].upper()),
                ("Labcode", f"{p['order_id']}/HYD{rng.randint(10, 99)}"),
                ("Barcode", p["barcode"])]
        for i, (label, value) in enumerate(info):
            c.drawString(40, base - i * 11, label)
            c.drawString(160, base - i * 11, f": {value}")
        draw_qr(c, f"SYNTHETIC|{report.case['id']}", 112, 42, 34)
        draw_signature(c, 300, 100, rng)
        draw_signature(c, 440, 100, rng)
        c.setFont("Helvetica", 7.5)
        c.drawString(292, 84, "Dr. P. Kalpit MD (Path)")
        c.drawString(432, 84, "Dr. R. Banawat MD (Path)")
        c.drawRightString(PAGE_W - 40, 40, f"Page : {page_no} of {len(pages)}")
        footer_note(c)
        c.showPage()


def lipid_reference_table(c, y: float) -> float:
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(40, y, "*REFERENCE RANGES (adult, mg/dL), commonly used categories:")
    y -= 12
    heads = ["", "TOTAL CHOLESTEROL", "LDL", "TRIGLYCERIDES"]
    rows = [("DESIRABLE / OPTIMAL", "<200", "<100", "<150"),
            ("BORDERLINE HIGH", "200-239", "130-159", "150-199"),
            ("HIGH", ">=240", ">=160", ">=200")]
    xs = [40, 170, 290, 380]
    for x, head in zip(xs, heads):
        c.drawString(x, y, head)
    c.setFont("Helvetica", 7.5)
    for row in rows:
        y -= 10
        for x, cell in zip(xs, row):
            c.drawString(x, y, cell)
    return y - 6


LAYOUTS = {"A": layout_a, "B": layout_b, "C": layout_c, "D": None}  # D is set below


# ---------------------------------------------------------------------------
# Layout D: long multi-page reports with a package title, sub-heading rows inside the
# table, method lines in brackets, unit-less ratio rows, lab-specific ranges, bold-only
# abnormal values, long numbered notes that name conditions, and a promotional box.
# ---------------------------------------------------------------------------

from reportlab.pdfbase.pdfmetrics import stringWidth  # noqa: E402

LAB_D = {
    "name": "Pratiroop Path Labs",
    "lines": ["Reference Laboratory (fictional): Sector 0, Example Enclave, New Delhi - 110000",
              "Tel: 011-0000 0000   |   care@pratiroop.example   |   www.pratiroop.example"],
    "package": "WELLNESS ESSENTIAL PACKAGE WITH SMART REPORT",
    "promo": "LIMITED OFFER: book your next full body check-up from home and get 15% off with code "
             "DEMO15 (fictional offer, valid till 31 Dec 2026). SCHEDULE NOW >",
}

D_SUBHEADS = {
    "cbc": ("COMPLETE BLOOD COUNT; CBC", "(Electrical impedance, photometry & flow cytometry)"),
    "lipid": ("LIPID PROFILE, BASIC, SERUM", "(Spectrophotometry, Calculated)"),
    "hba1c": ("HbA1c (GLYCOSYLATED HEMOGLOBIN), BLOOD", "(HPLC, NGSP certified)"),
    "thyroid": ("THYROID PROFILE, TOTAL, SERUM", "(CLIA)"),
    "lft": ("LIVER FUNCTION TEST (LFT), SERUM", "(Spectrophotometry)"),
}

# Original wording. Like many real reports, these notes name conditions; the explainer must
# not repeat them as if they applied to the patient.
D_NOTES = {
    "cbc": [
        "A low haemoglobin with small red cells (low MCV) is often seen in iron deficiency anaemia and in thalassemia trait; iron studies and haemoglobin electrophoresis help tell them apart.",
        "A raised total leucocyte count is commonly seen with bacterial infection, inflammation, stress and some medicines. Very high counts, or immature cells on the smear, need review for leukemia and other blood disorders.",
        "Platelet counts below 20 x 10^3/uL carry a risk of spontaneous bleeding and should be discussed with a clinician the same day.",
        "Red cell distribution width (RDW) rises when red cells vary in size, as in early nutritional deficiency or after transfusion.",
        "Reference intervals vary with age, sex, altitude and pregnancy. Results should be interpreted together with clinical findings.",
    ],
    "lipid": [
        "Raised LDL cholesterol is a major modifiable risk factor for atherosclerotic cardiovascular disease (ASCVD), coronary artery disease and stroke.",
        "Triglycerides above 500 mg/dL increase the risk of acute pancreatitis. High triglycerides with low HDL are a feature of metabolic syndrome and type 2 diabetes.",
        "Non-HDL cholesterol (total cholesterol minus HDL) includes all atherogenic lipoproteins and is a useful secondary target.",
        "Categories commonly used for LDL cholesterol (mg/dL): optimal <100, above optimal 100-129, borderline high 130-159, high 160-189, very high >=190.",
        "Measurements in the same person can vary from day to day. A repeat fasting sample is advised before starting or changing treatment.",
        "Secondary causes of raised lipids include hypothyroidism, kidney disease, liver disease and some medicines.",
    ],
    "hba1c": [
        "HbA1c below 5.7% is considered normal, 5.7-6.4% indicates an increased risk of diabetes (prediabetes), and 6.5% or above is consistent with diabetes when confirmed by a repeat test.",
        "For people with known diabetes, an HbA1c target is usually set individually, often below 7%, taking into account age, other illnesses and the risk of hypoglycemia.",
        "HbA1c can be falsely low in haemolytic anaemia, after blood loss or transfusion, and in pregnancy, and falsely high in iron deficiency anaemia and chronic kidney disease.",
        "Haemoglobin variants such as HbS and HbE can interfere with some HbA1c methods; this method separates the common variants.",
        "Monitoring every 3 months is commonly advised for people with diabetes whose treatment has changed or whose targets are not met.",
    ],
    "thyroid": [
        "A raised TSH with low T4 is the usual pattern of primary hypothyroidism; a raised TSH with normal T4 is often called subclinical hypothyroidism.",
        "A suppressed TSH with raised T3 or T4 is seen in hyperthyroidism, including Graves disease and toxic nodular goitre.",
        "Total T3 and T4 change with binding proteins, so they can be abnormal in pregnancy, liver disease and with oral contraceptives while free hormones remain normal.",
        "TSH follows a daily rhythm, peaking late at night, and can vary by up to 50% through the day.",
        "Trimester-specific reference ranges should be used for TSH in pregnancy.",
    ],
    "lft": [
        "In people without symptoms, non-alcoholic fatty liver disease (NAFLD) is the most common cause of mildly raised ALT and AST. NAFLD is the liver manifestation of metabolic syndrome.",
        "In most liver diseases ALT is higher than AST. An AST:ALT ratio above 1 can be seen in alcoholic hepatitis, cirrhosis and liver neoplasia, and in chronic liver disease suggests advanced fibrosis.",
        "Bilirubin rises with increased red cell breakdown (haemolysis), with hepatitis, and when bile flow is blocked by gallstones, strictures or tumours; direct bilirubin rises more in obstruction.",
        "Alkaline phosphatase is also produced by bone, so raised values may come from bone growth, fractures or bone disease as well as from the liver.",
        "A raised GGT supports a liver source for a raised ALP and can be increased by alcohol and some medicines.",
        "Liver enzymes can rise for a short time after strenuous exercise. Results should be interpreted with clinical findings and imaging.",
    ],
}

D_BODY_TOP = PAGE_H - 214
D_BODY_BOTTOM = 112
D_COLS = [52, 300, 376, 452]


def d_items(report: Report) -> list[tuple]:
    """Flatten the report body into items with heights, ready to paginate."""
    width = PAGE_W - 120
    items: list[tuple] = [("package", 22)]
    for panel in report.case["panels"]:
        title, method = D_SUBHEADS[panel]
        items += [("table_head", 20), ("subhead", 14, title), ("method", 13, method)]
        items += [("row", 14, row) for row in panel_rows(report, panel)]
        items += [("gap", 8), ("note_head", 14)]
        notes = list(D_NOTES[panel])
        if report.case.get("remark") and panel == report.case["panels"][-1]:
            notes.insert(0, f"Remark: {report.case['remark']}")
        if report.case.get("injection") and panel == report.case["panels"][-1]:
            notes.append(report.case["injection"])
        for n, note in enumerate(notes, start=1):
            lines = wrap_width(note, "Helvetica", 8.3, width - 18)
            for i, line in enumerate(lines):
                items.append(("note", 11, f"{n}." if i == 0 else "", line))
            items.append(("gap", 3))
        items.append(("gap", 12))
    items += [("end", 16), ("promo", 46)]
    return items


def wrap_width(text: str, font: str, size: float, width: float) -> list[str]:
    words, lines, line = text.split(), [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if stringWidth(trial, font, size) <= width:
            line = trial
        else:
            lines.append(line)
            line = word
    return lines + ([line] if line else [])


def d_paginate(items: list[tuple]) -> list[list[tuple]]:
    pages, current, y = [], [], D_BODY_TOP
    for item in items:
        height = item[1]
        if y - height < D_BODY_BOTTOM and current:
            pages.append(current)
            current, y = [], D_BODY_TOP
            if item[0] == "row":  # rows continuing on a new page get the table header again
                current.append(("table_head", 20))
                y -= 20
        if item[0] == "gap" and not current:
            continue
        current.append(item)
        y -= height
    if current:
        pages.append(current)
    return pages


def layout_d(c: canvas.Canvas, report: Report, rng: random.Random) -> None:
    p = report.patient
    pages = d_paginate(d_items(report))
    report.meta["pages"] = len(pages)
    lab_no = str(rng.randint(100000000, 999999999))
    for page_no, items in enumerate(pages, start=1):
        # Header
        c.setFillColor(HexColor("#e8f3ef"))
        c.rect(0, PAGE_H - 78, PAGE_W, 78, stroke=0, fill=1)
        c.setFillColor(HexColor("#2e7d6b"))
        c.setFont("Times-BoldItalic", 24)
        c.drawString(36, PAGE_H - 44, LAB_D["name"])
        c.setFillColor(black)
        c.setFont("Helvetica", 7)
        for i, line in enumerate(LAB_D["lines"]):
            c.drawString(36, PAGE_H - 58 - i * 9, line)
        for i, label in enumerate(["DEMO-NABL", "DEMO-CAP"]):
            c.setStrokeColor(HexColor("#2e7d6b"))
            c.circle(PAGE_W - 110 + i * 50, PAGE_H - 40, 18, stroke=1, fill=0)
            c.setFont("Helvetica-Bold", 5.5)
            c.drawCentredString(PAGE_W - 110 + i * 50, PAGE_H - 42, label)
        c.setStrokeColor(black)

        # Patient box, repeated on every page
        top = PAGE_H - 92
        c.setStrokeColor(HexColor("#999999"))
        c.rect(36, top - 84, PAGE_W - 72, 84, stroke=1, fill=0)
        c.setStrokeColor(black)
        left = [("Name", f": {p['name'].upper()}"), ("Lab No.", f": {lab_no}"),
                ("Ref By", f": {p['referred_by']}"), ("Collected", f": {p['collected']:%d/%m/%Y %I:%M:%S%p}"),
                ("A/c Status", ": P"), ("Collected at", ": DEMO COLLECTION CENTRE, SECTOR 0")]
        right = [("Age", f": {p['age']} Years"), ("Gender", f": {'Female' if p['sex'] == 'F' else 'Male'}"),
                 ("Reported", f": {p['reported']:%d/%m/%Y %I:%M:%S%p}"), ("Report Status", ": Final"),
                 ("Processed at", ": Pratiroop Path Labs, Demo City")]
        c.setFont("Helvetica", 8)
        for i, (label, value) in enumerate(left):
            c.drawString(44, top - 13 - i * 12.5, label)
            c.drawString(110, top - 13 - i * 12.5, value)
        for i, (label, value) in enumerate(right):
            c.drawString(PAGE_W / 2 + 40, top - 13 - i * 12.5, label)
            c.drawString(PAGE_W / 2 + 112, top - 13 - i * 12.5, value)
        c.setFont("Helvetica-Bold", 9.5)
        c.drawCentredString(PAGE_W / 2, top - 100, "Test Report")

        y = D_BODY_TOP
        for item in items:
            kind = item[0]
            if kind == "package":
                c.setFont("Helvetica-Bold", 9.5)
                c.drawString(44, y - 12, LAB_D["package"])
            elif kind == "table_head":
                c.setFont("Helvetica-Bold", 8.8)
                for x, head in zip(D_COLS, ["Test Name", "Results", "Units", "Bio. Ref. Interval"]):
                    c.drawString(x - 8 if x == D_COLS[0] else x, y - 12, head)
                c.line(40, y - 16, PAGE_W - 40, y - 16)
            elif kind == "subhead":
                c.setFont("Helvetica-Bold", 8.8)
                c.drawString(D_COLS[0] - 8, y - 10, item[2])
            elif kind == "method":
                c.setFont("Helvetica", 8)
                c.drawString(D_COLS[0] - 8, y - 9, item[2])
            elif kind == "row":
                row = item[2]
                row["page"] = page_no
                bold = is_abnormal(row) or row["is_critical"]
                c.setFont("Helvetica", 8.6)
                c.drawString(D_COLS[0], y - 10, row["printed_name"])
                c.setFont("Helvetica-Bold" if bold else "Helvetica", 8.6)
                c.drawString(D_COLS[1], y - 10, row["value"]["raw"])
                c.setFont("Helvetica", 8.6)
                c.drawString(D_COLS[2], y - 10, row["unit_raw"])
                c.drawString(D_COLS[3], y - 10, row["ref"]["raw"])
            elif kind == "note_head":
                c.setFont("Helvetica-Bold", 8.8)
                c.drawString(D_COLS[0] - 8, y - 10, "Note")
            elif kind == "note":
                c.setFont("Helvetica", 8.3)
                c.drawString(D_COLS[0], y - 9, item[2])
                c.drawString(D_COLS[0] + 16, y - 9, item[3])
            elif kind == "end":
                c.setFont("Helvetica", 8)
                c.drawCentredString(PAGE_W / 2, y - 11, "*** End of Report ***")
            elif kind == "promo":
                c.setFillColor(HexColor("#fff4d6"))
                c.roundRect(44, y - 42, PAGE_W - 88, 38, 5, stroke=0, fill=1)
                c.setFillColor(black)
                c.setFont("Helvetica-Bold", 7.8)
                for i, line in enumerate(wrap_width(LAB_D["promo"], "Helvetica-Bold", 7.8, PAGE_W - 110)):
                    c.drawString(54, y - 16 - i * 10, line)
            y -= item[1]

        # Footer
        draw_signature(c, 64, 84, rng)
        c.setFont("Helvetica-Bold", 7.8)
        c.drawString(56, 70, "Dr. V. Pratiroop, MD (Pathology)")
        c.setFont("Helvetica", 7.2)
        c.drawString(56, 61, "Chief of Laboratory (fictional)")
        draw_barcode(c, report.patient["barcode"], PAGE_W / 2 - 50, 62, 14)
        c.setFont("Helvetica", 7.5)
        c.drawRightString(PAGE_W - 40, 66, f"Page {page_no} of {len(pages)}")
        c.setFont("Helvetica-Oblique", 6.8)
        c.drawCentredString(PAGE_W / 2, 40, "If test results are alarming or unexpected, contact the laboratory immediately for possible remedial action.")
        footer_note(c)
        c.showPage()


LAYOUTS["D"] = layout_d
REF: dict = {}


def render_pdf(report: Report, seed: int) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4, invariant=1)
    c.setTitle(f"Synthetic lab report {report.case['id']} - not a real patient")
    c.setAuthor("lab-lens synthetic report generator")
    c.setSubject(SYNTHETIC_NOTE)
    report.meta["pages"] = len(report.case["panels"])
    LAYOUTS[report.case["layout"]](c, report, stable_rng(seed, report.case["id"] + ":render"))
    c.save()
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Scanned-image variant
# ---------------------------------------------------------------------------


def pdf_first_page_to_image(pdf_bytes: bytes, dpi: int = 150) -> Image.Image:
    try:
        import pypdfium2 as pdfium  # preferred: pip install pypdfium2

        page = pdfium.PdfDocument(pdf_bytes)[0]
        return page.render(scale=dpi / 72).to_pil().convert("RGB")
    except ImportError:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.pdf"
            src.write_bytes(pdf_bytes)
            subprocess.run(["pdftoppm", "-r", str(dpi), "-png", "-f", "1", "-l", "1",
                            str(src), str(Path(tmp) / "out")], check=True)
            return Image.open(next(Path(tmp).glob("out*.png"))).convert("RGB")


def scan_effect(image: Image.Image, params: dict, rng: random.Random) -> Image.Image:
    image = image.convert("L")
    image = image.rotate(params.get("rotate", 0), resample=Image.BICUBIC, expand=True, fillcolor=255)
    if params.get("blur"):
        image = image.filter(ImageFilter.GaussianBlur(params["blur"]))
    if params.get("noise"):
        noise = Image.frombytes("L", image.size, rng.randbytes(image.size[0] * image.size[1]))
        noise = noise.filter(ImageFilter.GaussianBlur(0.6))
        image = Image.blend(image, noise, params["noise"])
    # A faint warm paper tint, like a phone photo of a printout.
    return Image.merge("RGB", (image.point(lambda v: min(255, v + 2)), image,
                               image.point(lambda v: max(0, v - 6))))


def image_bytes(image: Image.Image, quality: int) -> bytes:
    buffer = io.BytesIO()
    # PNG container for a lossless file, after a JPEG round trip to add compression artefacts.
    jpeg = io.BytesIO()
    image.save(jpeg, format="JPEG", quality=quality)
    Image.open(io.BytesIO(jpeg.getvalue())).save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def ground_truth(report: Report, input_path: str, pdf_path: str) -> dict:
    case, p = report.case, report.patient
    rows = [{k: v for k, v in row.items() if k != "method"} for row in report.rows]
    return {
        "id": case["id"],
        "split": case["split"],
        "source": case.get("source"),
        "variation": case.get("variation"),
        "change": case.get("change"),
        "title": case["title"],
        "layout": case["layout"],
        "input": input_path,
        "source_pdf": pdf_path,
        "input_type": "image" if case.get("image") else "pdf",
        "pages": report.meta["pages"],
        "panels": case["panels"],
        "patient": {"name": p["name"], "age": p["age"], "sex": p["sex"],
                    "patient_id": p["patient_id"], "synthetic": True},
        "report_date": p["reported"].date().isoformat(),
        "tests": [r for r in rows if r["test_id"]],
        "unrecognised_tests": [r["printed_name"] for r in rows if not r["test_id"]],
        "lab_remarks": [case["remark"]] if case.get("remark") else [],
        "contains_injection": bool(case.get("injection")),
        "prints_condition_names": case["layout"] == "D" or (case["layout"] == "A" and "hba1c" in case["panels"]),
        "has_promotional_text": case["layout"] == "D",
        "expected": {**report.meta["outcome"],
                     "must_not_include": case["expect"].get("must_not_include", [])},
    }


def check_expectation(report: Report) -> list[str]:
    exp, got = report.case["expect"], report.meta["outcome"]
    problems = []
    for key in ("next_step", "urgency", "rule"):
        if exp.get(key) != got.get(key):
            problems.append(f"{key}: authored {exp.get(key)!r}, computed {got.get(key)!r}")
    if exp.get("package") != got.get("package"):
        problems.append(f"package: authored {exp.get('package')!r}, computed {got.get('package')!r}")
    unrec = [r["printed_name"] for r in report.rows if not r["test_id"]]
    if sorted(n.lower() for n in exp.get("unrecognised", [])) != sorted(n.lower() for n in unrec):
        problems.append(f"unrecognised: authored {exp.get('unrecognised')}, built {unrec}")
    return problems


MERGE_KEYS = ("values", "names", "units", "printed_flags", "extra_rows")
VARIATION_COUNTS = {"controlled_variation": 10, "perturbation": 8,
                    "extraction_challenge": 6, "adversarial": 6}
MAX_USES_PER_SOURCE = 3


def resolve_cases(cases: list[dict]) -> list[dict]:
    """Apply every eval case on top of a deep copy of its source spec."""
    sources = {c["id"]: c for c in cases if c["split"] == "source"}
    resolved = []
    for case in cases:
        if case["split"] == "source":
            resolved.append(copy.deepcopy(case))
            continue
        if case["split"] != "eval":
            raise SystemExit(f"{case['id']}: split must be 'source' or 'eval'")
        source = sources.get(case.get("source"))
        if source is None:
            raise SystemExit(f"{case['id']}: unknown source {case.get('source')!r}")
        if case.get("variation") not in VARIATION_COUNTS or not case.get("change"):
            raise SystemExit(f"{case['id']}: needs a known variation and a change description")
        merged = copy.deepcopy(source)
        merged.pop("expect")
        for key, value in case.items():
            if key in MERGE_KEYS and isinstance(value, dict):
                combined = {**(merged.get(key) or {}), **value}
                merged[key] = {k: v for k, v in combined.items() if v is not None}
            else:
                merged[key] = copy.deepcopy(value)
        resolved.append(merged)
    return resolved


def check_structure(cases: list[dict]) -> list[str]:
    sources = [c for c in cases if c["split"] == "source"]
    evals = [c for c in cases if c["split"] == "eval"]
    problems = []
    if len(sources) != 15 or len(evals) != 30:
        problems.append(f"expected 15 sources and 30 eval cases, found {len(sources)} and {len(evals)}")
    counts = {v: sum(c["variation"] == v for c in evals) for v in VARIATION_COUNTS}
    if counts != VARIATION_COUNTS:
        problems.append(f"variation counts {counts}, expected {VARIATION_COUNTS}")
    for src in sources:
        uses = sum(c["source"] == src["id"] for c in evals)
        if not 1 <= uses <= MAX_USES_PER_SOURCE:
            problems.append(f"source {src['id']} is used by {uses} eval cases (allowed 1-{MAX_USES_PER_SOURCE})")
    return problems


def outcome_signature(report: Report) -> tuple:
    out = report.meta["outcome"]
    abnormal = sorted((r["test_id"], r["expected_flag"], r["expected_severity"]) for r in report.rows
                      if r["test_id"] and (r["expected_flag"] != "normal" or r["is_critical"]))
    return out["next_step"], out["urgency"], out["rule"], tuple(abnormal)


def content_fingerprint(report: Report) -> str:
    """What a reader of the report would see: layout, rows as printed, and image treatment."""
    case = report.case
    rows = [(r["test_id"], r["printed_name"], r["value"]["raw"], r["unit_raw"], r["ref"]["raw"],
             r["printed_flag"], r["page"]) for r in report.rows]
    payload = {"layout": case["layout"], "panels": case["panels"], "rows": rows,
               "image": case.get("image"), "injection": case.get("injection"),
               "remark": case.get("remark")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def find_duplicates(entries: list[dict]) -> list[str]:
    """entries: {"id", "split", "source", "fingerprint", "file_hashes"}. Eval cases must be unique."""
    problems = []
    for entry in entries:
        if entry["split"] != "eval":
            continue
        for other in entries:
            if other["id"] == entry["id"]:
                continue
            if other["fingerprint"] == entry["fingerprint"]:
                problems.append(f"{entry['id']}: same values, layout and rendering as {other['id']}")
            if set(other["file_hashes"]) & set(entry["file_hashes"]):
                problems.append(f"{entry['id']}: output file identical to {other['id']}")
    return problems


def render_files(report: Report, seed: int) -> dict[str, bytes]:
    case = report.case
    pdf = render_pdf(report, seed)
    files = {f"{case['id']}.pdf": pdf}
    if case.get("image"):
        rng = stable_rng(seed, case["id"] + ":scan")
        image = scan_effect(pdf_first_page_to_image(pdf), case["image"], rng)
        files[f"{case['id']}.png"] = image_bytes(image, case["image"].get("jpeg", 75))
    return files


def generate(out_root: Path, only: set[str] | None = None) -> list[dict]:
    global REF
    REF = load_yaml(ROOT / "reference" / "panels.yaml")
    packages = load_yaml(ROOT / "reference" / "packages.yaml")["packages"]
    specs = load_yaml(ROOT / "data" / "case_specs.yaml")
    added = merge_stats_aliases(REF["tests"], ROOT / "reference" / "nidaankosha_stats.json")
    if added:
        print(f"Added {added} printed-name variants from reference/nidaankosha_stats.json")
    seed = specs["seed"]
    cases = resolve_cases(specs["cases"])

    problems: dict[str, list[str]] = {}
    structure = check_structure(cases)
    if structure:
        problems["structure"] = structure

    # Every case is built, so variation and duplicate checks always see the full set.
    reports = {}
    for case in cases:
        report = build_report(case, REF, packages, seed)
        issues = check_expectation(report)
        if issues:
            problems[case["id"]] = issues
        reports[case["id"]] = report
    for report in reports.values():
        case = report.case
        if case.get("variation") == "controlled_variation" and \
                outcome_signature(report) == outcome_signature(reports[case["source"]]):
            problems.setdefault(case["id"], []).append(
                f"controlled variation leaves flags, severity and next step unchanged from {case['source']}")
    if problems:
        for cid, issues in problems.items():
            print(f"{cid}: " + "; ".join(issues), file=sys.stderr)
        raise SystemExit("Case checks failed; nothing written.")

    rendered = {cid: render_files(report, seed) for cid, report in reports.items()}
    duplicates = find_duplicates([
        {"id": cid, "split": r.case["split"], "source": r.case.get("source"),
         "fingerprint": content_fingerprint(r),
         "file_hashes": [hashlib.sha256(b).hexdigest() for b in rendered[cid].values()]}
        for cid, r in reports.items()])
    if duplicates:
        print("\n".join(duplicates), file=sys.stderr)
        raise SystemExit("Eval cases duplicate a source or each other; nothing written.")

    index = []
    for cid, report in reports.items():
        if only and cid not in only:
            continue
        case = report.case
        split_dir = out_root / "reports" / case["split"]
        split_dir.mkdir(parents=True, exist_ok=True)
        for name, data in rendered[cid].items():
            (split_dir / name).write_bytes(data)
        pdf_rel = f"data/reports/{case['split']}/{cid}.pdf"
        input_rel = f"data/reports/{case['split']}/{cid}.png" if case.get("image") else pdf_rel
        truth = ground_truth(report, input_rel, pdf_rel)
        gt_dir = out_root / "ground_truth"
        gt_dir.mkdir(parents=True, exist_ok=True)
        (gt_dir / f"{cid}.json").write_text(json.dumps(truth, indent=2, ensure_ascii=False) + "\n",
                                            encoding="utf-8")
        entry = {"id": cid, "split": case["split"], "title": case["title"],
                 "layout": case["layout"], "panels": case["panels"], "input": input_rel,
                 "input_type": truth["input_type"], "next_step": truth["expected"]["next_step"],
                 "urgency": truth["expected"]["urgency"], "rule": truth["expected"]["rule"]}
        if case["split"] == "eval":
            entry.update(source=case["source"], variation=case["variation"], change=case["change"])
        index.append(entry)
    if not only:
        (out_root / "ground_truth" / "index.json").write_text(
            json.dumps({"seed": seed, "reference_version": REF["version"],
                        "sources": [e for e in index if e["split"] == "source"],
                        "eval_cases": [e for e in index if e["split"] == "eval"]},
                       indent=2) + "\n", encoding="utf-8")
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=ROOT / "data", help="output root (default: data/)")
    parser.add_argument("--only", nargs="*", help="write only these case IDs (all are still built and checked)")
    args = parser.parse_args()
    index = generate(args.out, set(args.only) if args.only else None)
    by_split = {s: sum(1 for i in index if i["split"] == s) for s in ("source", "eval")}
    print(f"Generated {len(index)} synthetic reports ({by_split['source']} source, {by_split['eval']} eval).")


if __name__ == "__main__":
    main()
