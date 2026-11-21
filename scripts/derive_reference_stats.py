#!/usr/bin/env python3
"""Derive aggregate statistics from the NidaanKosha dataset for the report generator.

NidaanKosha (ekacare/NidaanKosha-100k-V1.0, CC-BY-SA-4.0) holds about 6.8 million test
readings extracted from 100,000 real, de-identified Indian lab reports. Because it comes from
real patients, this project never copies its rows into reports. This script keeps only
aggregates for the tests the generator uses:

  - how test names are printed (variants seen at least --min-count times)
  - which units appear
  - how reference ranges are written
  - value percentiles (p1, p5, p25, p50, p75, p95, p99)

Output: reference/nidaankosha_stats.json, which generate_reports.py reads if it exists to
add realistic name variants. The file is a derivative of a CC-BY-SA-4.0 dataset, so it carries
the attribution below and is shared under the same licence.

Run it on your own machine (it downloads about 176 MB):

    pip install "huggingface_hub>=0.24" pandas pyarrow pyyaml
    python scripts/derive_reference_stats.py

Untested against the live dataset: column names follow the dataset card (test_name,
display_ranges, value, unit, loinc). If they differ, the script stops and prints the columns.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = "ekacare/NidaanKosha-100k-V1.0"
NEEDED = ["test_name", "display_ranges", "value", "unit", "loinc"]
NUMBER = re.compile(r"[-+]?\d*\.?\d+")


def load_frame():
    import pandas as pd
    from huggingface_hub import snapshot_download

    folder = snapshot_download(repo_id=DATASET, repo_type="dataset", allow_patterns=["*.parquet"])
    files = sorted(Path(folder).rglob("*.parquet"))
    if not files:
        raise SystemExit(f"No parquet files found in {folder}")
    frames = []
    for path in files:
        frame = pd.read_parquet(path)
        missing = [c for c in NEEDED if c not in frame.columns]
        if missing:
            raise SystemExit(f"{path.name}: missing columns {missing}; found {list(frame.columns)}")
        frames.append(frame[NEEDED])
    return pd.concat(frames, ignore_index=True), files


def clean(text) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def to_number(value) -> float | None:
    match = NUMBER.search(str(value))
    return float(match.group()) if match else None


def main() -> None:
    import yaml

    parser = argparse.ArgumentParser()
    parser.add_argument("--min-count", type=int, default=50,
                        help="drop any name, unit or range string seen fewer times (default 50)")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--out", type=Path, default=ROOT / "reference" / "nidaankosha_stats.json")
    args = parser.parse_args()

    tests = yaml.safe_load((ROOT / "reference" / "panels.yaml").read_text(encoding="utf-8"))["tests"]
    wanted = {t["loinc"]: tid for tid, t in tests.items() if t.get("loinc")}

    frame, files = load_frame()
    frame["loinc"] = frame["loinc"].astype(str).str.strip()
    frame = frame[frame["loinc"].isin(wanted)]

    def frequent(series) -> list[dict]:
        counts = Counter(clean(v) for v in series.dropna() if clean(v))
        return [{"name": k, "count": n} for k, n in counts.most_common(args.top) if n >= args.min_count]

    result = {}
    for loinc, group in frame.groupby("loinc"):
        numbers = sorted(n for n in (to_number(v) for v in group["value"]) if n is not None)
        if len(numbers) < args.min_count:
            continue

        def pct(q: float) -> float:
            return round(numbers[min(len(numbers) - 1, int(q * len(numbers)))], 4)

        result[loinc] = {
            "test_id": wanted[loinc],
            "n": len(numbers),
            "name_variants": frequent(group["test_name"]),
            "units": [{"unit": u["name"], "count": u["count"]} for u in frequent(group["unit"])],
            "range_formats": [{"range": r["name"], "count": r["count"]}
                              for r in frequent(group["display_ranges"])],
            "value_percentiles": {f"p{int(q * 100)}": pct(q)
                                  for q in (0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99)},
        }

    out = {
        "source": f"https://huggingface.co/datasets/{DATASET}",
        "attribution": "Derived from NidaanKosha-100k-V1.0 by Eka Care, licensed CC-BY-SA-4.0. "
                       "Aggregates only; no individual readings are included.",
        "license": "CC-BY-SA-4.0",
        "min_count": args.min_count,
        "files_read": [p.name for p in files],
        "tests": dict(sorted(result.items())),
    }
    args.out.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {args.out} for {len(result)} of {len(wanted)} tests.")
    missing = sorted(set(wanted.values()) - {v["test_id"] for v in result.values()})
    if missing:
        print("No data (check their LOINC codes in panels.yaml):", ", ".join(missing))


if __name__ == "__main__":
    main()
