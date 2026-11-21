#!/usr/bin/env python3
"""Generate the held-out critical-value verification set (PLAN.md sections 4 and 7).

Outputs (default data/critical_set/):
  rows.json                  single-test rows with expected flag / is_critical / rule
  reports/Cxx.pdf            10 synthetic report PDFs, each with at least one critical value
  ground_truth/Cxx.json      ground truth for each PDF (same format as data/ground_truth)

HELD OUT: this set is for verification only. It must never be used to tune thresholds,
prompts or models. Everything is synthetic; every PDF carries the synthetic-report line.

Expected labels are computed here with exact decimal arithmetic from reference/panels.yaml
critical limits (canonical units) and the unit factors, independently of src/lablens.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_reports as gr  # noqa: E402  (read-only reuse of layouts and rendering)

SEED = 20261121
SEX = "M"
# Alternate printed units with the decimals a lab would print them in (factor: printed = canonical * factor).
PDF_ALT_DECIMALS = {"lakhs/cumm": 2, "lakh/cumm": 2, "/cumm": 0, "cells/cumm": 0, "/ul": 0}
NO_CRITICAL_EXTREMES = [("TSH", "95.000"), ("LDL", "350.0"), ("HBA1C", "14.0"), ("TG", "900.0"),
                        ("ALP", "1200"), ("GGT", "1100"), ("T4", "0.60"), ("RDW", "28.0"),
                        ("MCV", "55.0"), ("HDL", "12.0")]


def load_ref() -> tuple[dict, dict]:
    panels = gr.load_yaml(ROOT / "reference" / "panels.yaml")
    conv = gr.load_yaml(ROOT / "reference" / "unit_conversions.yaml")["tests"]
    return panels, conv


def panel_of(panels: dict, tid: str) -> str:
    return next(p for p, spec in panels["panels"].items() if tid in spec["tests"])


def dfmt(x: D, decimals: int) -> str:
    return f"{x:.{decimals}f}" if decimals > 0 else f"{x.quantize(D(1)):f}"


def expected_critical(canon: D, comp: str, crit: dict) -> tuple[bool, str | None]:
    lo, hi = crit.get("low"), crit.get("high")
    if lo is not None and canon <= D(str(lo)) and comp in ("=", "<", "<="):
        return True, "low"
    if hi is not None and canon >= D(str(hi)) and comp in ("=", ">", ">="):
        return True, "high"
    return False, None


def expected_range_flag(num: D, comp: str, low: D | None, high: D | None) -> str:
    if low is None and high is None:
        return "unknown"
    if comp in ("<", "<="):
        if low is not None and num <= low:
            return "low"
        return "normal" if low is None and num <= high else "unknown"
    if comp in (">", ">="):
        if high is not None and num >= high:
            return "high"
        return "normal" if high is None and num >= low else "unknown"
    if low is not None and num < low:
        return "low"
    if high is not None and num > high:
        return "high"
    return "normal"


class Builder:
    def __init__(self, panels: dict, conv: dict):
        self.tests, self.panels, self.conv, self.rows = panels["tests"], panels, conv, []

    def units(self, tid: str) -> list[tuple[str, D]]:
        """(printed unit, factor) for the canonical unit and each alternate unit."""
        t = self.tests[tid]
        alts = {**(t.get("alt_units") or {}), **((self.conv.get(tid) or {}).get("alt_units") or {})}
        return [(t["unit"], D(1))] + [(u, D(str(s["factor"]))) for u, s in alts.items()]

    def add(self, category: str, tid: str, printed: D, *, unit: str | None = None, factor: D = D(1),
            decimals: int | None = None, comp: str = "=", ref: tuple | None | str = "default",
            printed_flag: str | None = None, note: str = "") -> None:
        t = self.tests[tid]
        unit = unit or t["unit"]
        decimals = t["decimals"] if decimals is None else decimals
        if ref == "default":
            lo, hi = gr.ref_for(t, SEX)
            ref = (None if lo is None else D(str(lo)) * factor, None if hi is None else D(str(hi)) * factor)
        if ref is None:  # range not printed: engine uses the canonical fallback table, if any
            fb = (t.get("ref") or {}).get("all")
            rlo, rhi, rraw, src = None, None, "", "none"
            flag_lo = None if not fb or fb[0] is None else D(str(fb[0]))
            flag_hi = None if not fb or fb[1] is None else D(str(fb[1]))
            flag_num = printed / factor
        else:
            rlo, rhi = ref
            rraw = gr.range_text(None if rlo is None else float(rlo), None if rhi is None else float(rhi),
                                 decimals)
            src, flag_lo, flag_hi, flag_num = "report", rlo, rhi, printed
        canon = printed / factor
        crit, direction = expected_critical(canon, comp, t.get("critical") or {})
        flag = direction if crit else expected_range_flag(flag_num, comp, flag_lo, flag_hi)
        raw = ("" if comp == "=" else comp) + dfmt(printed, decimals)
        self.rows.append({
            "id": f"CR{len(self.rows) + 1:03d}", "category": category, "note": note,
            "test": {
                "raw_name": t["name"], "test_id": tid, "panel": panel_of(self.panels, tid),
                "value": {"raw": raw, "number": float(D(raw.lstrip("<>="))), "comparator": comp},
                "unit_raw": unit, "unit": t["unit"],
                "ref": {"raw": rraw, "low": None if rlo is None else float(rlo),
                        "high": None if rhi is None else float(rhi), "source": src},
                "printed_flag": printed_flag, "remark": None, "page": 1,
                "source_span": f"{t['name']} {raw} {unit} {rraw}".strip(), "confidence": 1.0},
            "value_canonical": float(canon),
            "expected_flag": flag, "expected_is_critical": crit,
            "expected_rule": "R1_critical" if crit else "not_R1",
        })

    def build(self) -> list[dict]:
        crit_tests = {tid: t for tid, t in self.tests.items() if t.get("critical")}
        for tid, t in crit_tests.items():
            dec = t["decimals"]
            step = D(1).scaleb(-dec)
            for side in ("low", "high"):
                lim = t["critical"].get(side)
                if lim is None:
                    continue
                lim = D(str(lim))
                out = -1 if side == "low" else 1  # direction "past" the limit
                # 1. boundaries in every unit: past/at/inside by one printed step and a finer step
                for unit, f in self.units(tid):
                    udec = dec if f == 1 else PDF_ALT_DECIMALS.get(unit, dec)
                    ustep = D(1).scaleb(-udec)
                    fine = ustep / 10
                    positions = [("past", ustep), ("past_fine", fine), ("at", D(0)),
                                 ("inside_fine", -fine), ("inside", -ustep)]
                    for name, delta in positions:
                        v = lim * f + out * delta
                        d = udec + (1 if "fine" in name else 0)
                        self.add("boundary_canonical" if f == 1 else "boundary_alt_unit", tid, v,
                                 unit=unit, factor=f, decimals=d, note=f"{side} {name}")
                # 2. canonical-unit spellings (PLT)
                for spelling in (self.conv.get(tid) or {}).get("equivalent") or []:
                    for name, delta in (("past", step), ("at", D(0)), ("inside", -step)):
                        self.add("unit_equivalent_spelling", tid, lim + out * delta, unit=spelling,
                                 note=f"{side} {name}")
                # 3. printed range wide enough that the critical value looks normal
                for k, mult in (("at", 0), ("past", 1), ("far_past", 5)):
                    v = lim + out * mult * step
                    wide = (min(v, lim) - 10 * step if side == "low" else D(0),
                            max(v, lim) * 2 + step)
                    self.add("misleading_printed_range", tid, v, ref=wide, note=f"{side} {k}")
                for unit, f in self.units(tid)[1:3]:
                    udec = PDF_ALT_DECIMALS.get(unit, dec)
                    for k, mult in (("at", 0), ("past", 1)):
                        v = (lim + out * mult * step) * f
                        wide = (D(0), max(v, lim * f) * 2)
                        self.add("misleading_printed_range", tid, v, unit=unit, factor=f,
                                 decimals=udec, ref=wide, note=f"{side} {k} {unit}")
                # 4. no printed flag, or a printed "N" flag, on a critical value
                for pf in (None, "N"):
                    for k, mult in (("at", 0), ("past", 3)):
                        self.add("no_or_normal_printed_flag", tid, lim + out * mult * step,
                                 printed_flag=pf, note=f"{side} {k} flag={pf}")
                # 5. range not printed at all
                for k, mult in (("at", 0), ("past", 3)):
                    self.add("no_printed_range", tid, lim + out * mult * step, ref=None,
                             note=f"{side} {k}")
                # 6. comparator values
                c = "<" if side == "low" else ">"
                for k, mult in (("at", 0), ("beyond", 5)):
                    self.add("comparator_critical", tid, lim + out * mult * step, comp=c,
                             note=f"{c} {side} {k}")
                self.add("comparator_control", tid, lim - out * 5 * step, comp=c,
                         note=f"{c} on the safe side of the {side} limit")
                opp = ">" if c == "<" else "<"
                self.add("comparator_control", tid, lim + out * 5 * step, comp=opp,
                         note=f"{opp} past the {side} limit, true value unbounded toward safety")
                if tid == "PLT":
                    for unit, f in self.units(tid)[1:3]:
                        udec = PDF_ALT_DECIMALS.get(unit, dec)
                        self.add("comparator_critical", tid, (lim + out * 2 * step) * f, unit=unit,
                                 factor=f, decimals=udec, comp=c, note=f"{c} {side} {unit}")
                # 7. non-critical abnormal controls on the same side
                for frac in (D("0.5"), D("0.9")):
                    lo, hi = gr.ref_for(t, SEX)
                    edge = D(str(lo if side == "low" else hi))
                    v = (edge + (lim - edge) * frac).quantize(step)
                    if v == lim:
                        v -= out * step
                    self.add("control_abnormal_noncritical", tid, v, note=f"{side} {frac} of way")
            # 8. normal controls
            lo, hi = gr.ref_for(t, SEX)
            lo = D(str(lo)) if lo is not None else D(str(hi)) / 4
            hi = D(str(hi))
            for frac in (D("0.2"), D("0.5"), D("0.8")):
                self.add("control_normal", tid, (lo + (hi - lo) * frac).quantize(step))
        # 9. extreme values on tests that have no critical limit
        for tid, raw in NO_CRITICAL_EXTREMES:
            self.add("control_no_critical_limit", tid, D(raw),
                     decimals=len(raw.split(".")[1]) if "." in raw else 0)
        return self.rows


# ---------------------------------------------------------------------------
# PDFs
# ---------------------------------------------------------------------------

DERIVED_ALLOW = ["IBIL", "DBIL", "AST_ALT", "GLOB", "AG", "NEUT", "LYMPH", "MONO", "EOS", "BASO",
                 "PCV", "MCH", "MCHC", "RBC"]
URGENT = {"next_step": "doctor_consult", "urgency": "urgent", "rule": "R1_critical"}
PDF_CASES = [
    {"id": "C01", "title": "CBC, critically low haemoglobin", "layout": "A", "sex": "F", "age": 41,
     "panels": ["cbc"], "values": {"HB": "6.4"}},
    {"id": "C02", "title": "CBC, critically low platelets printed in lakhs/cumm", "layout": "B",
     "sex": "M", "age": 36, "panels": ["cbc"], "values": {"PLT": "15"}, "units": {"PLT": "lakhs/cumm"}},
    {"id": "C03", "title": "CBC, critically high leucocytes", "layout": "C", "sex": "M", "age": 62,
     "panels": ["cbc"], "values": {"WBC": "32.50"}},
    {"id": "C04", "title": "LFT, critically high bilirubin", "layout": "D", "sex": "F", "age": 55,
     "panels": ["lft"], "values": {"TBIL": "16.20", "DBIL": "9.10"}},
    {"id": "C05", "title": "LFT, ALT reported as >1200 and AST 1100", "layout": "A", "sex": "M",
     "age": 47, "panels": ["lft"], "values": {"ALT": ">1200", "AST": "1100"}},
    {"id": "C06", "title": "CBC, low platelets printed in /cumm, no flag column", "layout": "C",
     "sex": "F", "age": 29, "panels": ["cbc"], "values": {"PLT": "12"}, "units": {"PLT": "/cumm"}},
    {"id": "C07", "title": "CBC, critically low platelets with range not printed", "layout": "A",
     "sex": "M", "age": 70, "panels": ["cbc"], "values": {"PLT": "8"}, "missing_range": ["PLT"]},
    {"id": "C08", "title": "CBC, critically high platelets", "layout": "D", "sex": "F", "age": 33,
     "panels": ["cbc"], "values": {"PLT": "1100"}},
    {"id": "C09", "title": "CBC + LFT, low WBC and bilirubin exactly at the limit", "layout": "B",
     "sex": "M", "age": 58, "panels": ["cbc", "lft"], "values": {"WBC": "1.80", "TBIL": "15.00", "DBIL": "8.00"}},
    {"id": "C10", "title": "LFT, AST exactly at the critical limit", "layout": "C", "sex": "F",
     "age": 44, "panels": ["lft"], "values": {"AST": "1000"}},
]


def pdf_ref(panels: dict, conv: dict) -> dict:
    ref = copy.deepcopy(panels)
    for tid, spec in conv.items():  # alternate units the PDF layouts may print, with decimals
        alts = ref["tests"][tid].setdefault("alt_units", {})
        for unit, s in (spec.get("alt_units") or {}).items():
            alts.setdefault(unit, {"factor": s["factor"], "decimals": PDF_ALT_DECIMALS.get(unit, 2)})
    return ref


def build_pdfs(out: Path, panels: dict, conv: dict) -> list[dict]:
    ref = pdf_ref(panels, conv)
    packages = gr.load_yaml(ROOT / "reference" / "packages.yaml")["packages"]
    gr.REF = ref  # panel_tests() reads the module-level reference
    (out / "reports").mkdir(parents=True, exist_ok=True)
    (out / "ground_truth").mkdir(parents=True, exist_ok=True)
    index = []
    for spec in PDF_CASES:
        case = {"split": "critical_set", "allow_abnormal": DERIVED_ALLOW, "expect": dict(URGENT), **spec}
        report = gr.build_report(case, ref, packages, SEED)
        problems = gr.check_expectation(report)
        crit = [r["test_id"] for r in report.rows if r["is_critical"]]
        if problems or not crit:
            raise SystemExit(f"{case['id']}: {problems or 'no critical value'}; nothing written")
        pdf = gr.render_pdf(report, SEED)
        rel = f"data/critical_set/reports/{case['id']}.pdf"
        (out / "reports" / f"{case['id']}.pdf").write_bytes(pdf)
        truth = gr.ground_truth(report, rel, rel)
        truth["held_out"] = True
        (out / "ground_truth" / f"{case['id']}.json").write_text(
            json.dumps(truth, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        index.append({"id": case["id"], "layout": case["layout"], "title": case["title"],
                      "critical_tests": crit,
                      "units": {r["test_id"]: r["unit_raw"] for r in report.rows if r["is_critical"]}})
    return index


def generate(out: Path, pdfs: bool = True) -> dict:
    # Rows are fully enumerated (no randomness); PDFs use the generator's seeded RNG.
    panels, conv = load_ref()
    rows = Builder(panels, conv).build()
    counts = Counter(r["category"] for r in rows)
    summary = {"seed": SEED, "reference_version": panels["version"], "held_out": True,
               "synthetic": True, "n_rows": len(rows),
               "n_critical": sum(r["expected_is_critical"] for r in rows),
               "counts_by_category": dict(sorted(counts.items())),
               "critical_by_category": dict(sorted(Counter(
                   r["category"] for r in rows if r["expected_is_critical"]).items()))}
    out.mkdir(parents=True, exist_ok=True)
    pdf_index = build_pdfs(out, panels, conv) if pdfs else []
    payload = {**summary, "pdfs": pdf_index, "rows": rows}
    (out / "rows.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                                   encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "critical_set")
    args = ap.parse_args()
    s = generate(args.out)
    print(f"{s['n_rows']} rows ({s['n_critical']} critical): {s['counts_by_category']}")


if __name__ == "__main__":
    main()
