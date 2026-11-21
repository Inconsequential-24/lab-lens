"""Demo list: the 15 synthetic source reports only (never eval cases or the held-out critical-value set). Built solely from data/reports/source/."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
SOURCE_DIR = ROOT / "data" / "reports" / "source"
CASE_SPECS = ROOT / "data" / "case_specs.yaml"
GROUND_TRUTH = ROOT / "data" / "ground_truth"
DEMO_ID = re.compile(r"^D\d{2}$")
CATEGORY = {"R1_critical": "critical", "R6_normal": "normal", "R5_verify": "held"}


def category(rule: str) -> str:
    return CATEGORY.get(rule, "abnormal")


@lru_cache(maxsize=1)
def demo_reports() -> tuple[dict, ...]:
    cases = yaml.safe_load(CASE_SPECS.read_text(encoding="utf-8"))["cases"]
    out = []
    for c in cases:
        if c.get("split") != "source" or not DEMO_ID.match(str(c.get("id", ""))):
            continue
        cid = c["id"]
        if not (SOURCE_DIR / f"{cid}.pdf").is_file():
            continue
        gt_path = GROUND_TRUTH / f"{cid}.json"
        tests = json.loads(gt_path.read_text(encoding="utf-8")).get("tests", []) if gt_path.is_file() else []
        out.append({"id": cid, "title": c["title"], "panel": (c.get("panels") or [None])[0],
                    "category": category(c["expect"]["rule"]), "test_count": len(tests),
                    "pdf_url": f"/v1/demo/reports/{cid}.pdf"})
    return tuple(out)


def demo_pdf(report_id: str) -> Path | None:
    """Resolve only ids listed in demo_reports(); anything else is None."""
    if not DEMO_ID.match(report_id) or report_id not in {d["id"] for d in demo_reports()}:
        return None
    p = (SOURCE_DIR / f"{report_id}.pdf").resolve()
    return p if p.parent == SOURCE_DIR.resolve() and p.is_file() else None
