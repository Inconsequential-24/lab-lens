"""Deterministic synthetic data and splits for the ML nodes (PLAN.md sections 4 and 13).

Labels come from panels.yaml, packages.yaml and the flag engine, so they are circular by
construction; held-out splits use unseen generation rules, unseen aliases and unseen tests.
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

from lablens import reference
from lablens.flag_engine import compute_flag, is_critical

SEED = 1234
GT_DIR = Path(__file__).resolve().parents[3] / "data" / "ground_truth"

# ---------------------------------------------------------------- names
TRAIN_RULES = ("case", "spacing", "punct", "typo", "suffix")
HELDOUT_RULES = ("vowels", "abbrev")
ABBREV = {"total": "tot.", "cholesterol": "chol.", "count": "cnt", "serum": "s.",
          "hemoglobin": "hb", "haemoglobin": "hb", "direct": "dir.", "indirect": "ind.",
          "ratio": "rt", "protein": "prot.", "bilirubin": "bili", "glucose": "glu",
          "lymphocytes": "lymphs", "neutrophils": "neut", "platelet": "plt",
          "corpuscular": "corp.", "concentration": "conc.", "volume": "vol."}
# Names the pipeline must NOT map: unsupported tests, package items, other common lab words.
UNKNOWN_NAMES = [
    "Vitamin B12", "Serum Iron", "TIBC", "Ferritin", "Transferrin Saturation", "Apolipoprotein B",
    "Fasting Plasma Glucose", "Free T4", "Free T3", "Vitamin D (25-OH)", "Serum Creatinine",
    "Blood Urea", "BUN", "Uric Acid", "Serum Sodium", "Potassium", "Chloride", "Calcium",
    "ESR", "C-Reactive Protein", "CRP", "Glucose Random", "Post Prandial Glucose",
    "Urine Protein", "Urine Sugar", "Prothrombin Time", "INR", "Reticulocyte Count",
    "Serum Magnesium", "Phosphorus", "Amylase", "Lipase", "LDH", "CPK", "Troponin I",
    "PSA Total", "Anti TPO", "HBsAg", "Insulin Fasting", "Folic Acid", "Absolute Neutrophil Count",
    "Peripheral Smear", "Bleeding Time", "Clotting Time", "Blood Group", "Specific Gravity",
    "Pus Cells", "Epithelial Cells", "Ketone Bodies", "Microalbumin",
]


def _aliases(t: dict) -> list[str]:
    return list(dict.fromkeys([t["name"], *t.get("aliases", [])]))


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def variant(name: str, rule: str, rng: random.Random, tid: str, method: str | None) -> str:
    if rule == "case":
        return rng.choice([name.upper(), name.lower(), name.title()])
    if rule == "spacing":
        return rng.choice([name.replace(" ", ""), "  ".join(name.split()), f" {name} "])
    if rule == "punct":
        s = re.sub(r"[()\-:/.,]", " ", name)
        return rng.choice([" ".join(s.split()), name.replace(" ", rng.choice(["-", ".", "_"]))])
    if rule == "typo":
        if len(name) < 5:
            return name.upper()
        i = rng.randrange(1, len(name) - 1)
        op = rng.choice(["del", "swap", "sub"])
        if op == "del":
            return name[:i] + name[i + 1:]
        if op == "swap":
            return name[:i] + name[i + 1] + name[i] + name[i + 2:]
        return name[:i] + rng.choice("aeiourstn") + name[i + 1:]
    if rule == "suffix":
        return rng.choice([f"{name} ({tid})", f"{name} - {method or 'Calculated'}", f"{name}, Serum"])
    if rule == "vowels":  # drop interior vowels of words longer than 4 letters
        return " ".join(re.sub(r"(?<=\w)[aeiou](?=\w)", "", w, flags=re.I) if len(w) > 4 else w
                        for w in name.split())
    if rule == "abbrev":
        return " ".join(ABBREV.get(w.lower(), w) for w in name.split())
    raise ValueError(rule)


def gt_names(prefix: str) -> list[tuple[str, str]]:
    """(printed_name, test_id) pairs from ground truth files starting with `prefix` (D or E)."""
    pairs = set()
    for f in sorted(GT_DIR.glob(f"{prefix}*.json")):
        for row in json.loads(f.read_text(encoding="utf-8"))["tests"]:
            pairs.add((row["printed_name"], row["test_id"]))
    return sorted(pairs, key=lambda p: (p[0], str(p[1])))


def name_splits(seed: int = SEED) -> dict[str, list[tuple[str, str | None]]]:
    """train / dev / heldout lists of (name, test_id or None). Disjoint by exact string."""
    rng = random.Random(seed)
    tests = reference.load_tests()
    train, held, dev_known = [], [], []
    for tid, t in tests.items():
        names = _aliases(t)
        extra = names[1:]
        k = len(extra) // 3 if len(extra) >= 3 else 0  # hold out whole aliases
        held_alias = set(rng.sample(extra, k))
        rest = [a for a in extra if a not in held_alias]
        dev_alias = set(rng.sample(rest, 1)) if len(rest) >= 2 else set()  # tuning confusers
        for n in names:
            dst = held if n in held_alias else dev_known if n in dev_alias else train
            dst.append((n, tid))
            for rule in TRAIN_RULES:
                for _ in range(3):
                    dst.append((variant(n, rule, rng, tid, t.get("method")), tid))
            for rule in HELDOUT_RULES:
                held.append((variant(n, rule, rng, tid, t.get("method")), tid))
    train += [(n, tid) for n, tid in gt_names("D")]
    unk = UNKNOWN_NAMES[:]
    rng.shuffle(unk)
    dev_unknown, held_unknown = unk[: len(unk) // 2], unk[len(unk) // 2:]
    train_set = {n for n, _ in train + dev_known}
    held = [p for p in dict.fromkeys(held) if p[0] not in train_set]
    for u in held_unknown:
        held += [(u, None), (variant(u, rng.choice(TRAIN_RULES), rng, "", None), None)]
    held = list(dict.fromkeys(held))
    train = list(dict.fromkeys(train))
    train_set = {n for n, _ in train}
    dev_known = [p for p in dict.fromkeys(dev_known) if p[0] not in train_set]
    # dev = unseen aliases + known-unknowns; used only to tune threshold and margin
    return {"train": train, "dev": dev_known + [(u, None) for u in dev_unknown], "heldout": held}


# ---------------------------------------------------------------- flags / patterns
def feature_ids() -> list[str]:
    return list(reference.load_tests())


def _patterns(flags: dict[str, str]) -> dict[str, list[str]]:
    """Rule labels: package pattern -> abnormal tests in its group (ignores R3's mild/allowed gate)."""
    out = {}
    for pid, pkg in reference.load_packages().items():
        have = {(t, f) for t, f in flags.items()}
        need_all = [(p["test"], p["flag"]) for p in pkg.get("requires_all", [])]
        need_any = [(p["test"], p["flag"]) for p in pkg.get("requires_any", [])]
        if (need_all and all(n in have for n in need_all)) or (need_any and any(n in have for n in need_any)):
            out[pid] = [t for t in pkg["allowed_abnormal"] if flags.get(t) in ("low", "high")]
    return out


def pattern_labels(flags: dict[str, str]) -> list[int]:
    hits = _patterns(flags)
    return [int(p in hits) for p in reference.load_packages()]


def flag_vector(flags: dict[str, str]) -> list[int]:
    v = []
    for tid in feature_ids():
        f = flags.get(tid)
        v += [int(f == "low"), int(f == "high")]
    return v


def synth_flag_sets(n: int, seed: int) -> list[dict[str, str]]:
    rng = random.Random(seed)
    panels = reference.load_yaml("panels.yaml")["panels"]
    pkgs = list(reference.load_packages().values())
    out = []
    for _ in range(n):
        chosen = rng.sample(list(panels), rng.randint(1, 3))
        flags = {}
        for p in chosen:
            for t in panels[p]["tests"]:
                r = rng.random()
                flags[t] = "normal" if r < 0.8 else ("low" if r < 0.9 else "high")
        if rng.random() < 0.4:  # plant a package pattern so positives are not rare
            pkg = rng.choice(pkgs)
            for req in pkg.get("requires_all", []) or [rng.choice(pkg["requires_any"])]:
                flags[req["test"]] = req["flag"]
        out.append(flags)
    return out


def gt_flag_sets(prefix: str) -> list[dict[str, str]]:
    return [{r["test_id"]: r["expected_flag"] for r in json.loads(f.read_text("utf-8"))["tests"]}
            for f in sorted(GT_DIR.glob(f"{prefix}*.json"))]


def flag_rows(test_ids: list[str], n_per: int, seed: int) -> list[tuple[list[float], str, bool]]:
    """(features [value, low, high], rule flag, rule critical) for synthetic numeric rows."""
    rng = random.Random(seed)
    tests, crit = reference.load_tests(), reference.load_critical_values()
    rows = []
    for tid in test_ids:
        for rng_ in (tests[tid].get("ref") or {}).values():
            lo, hi = rng_
            if lo is None and hi is None:
                continue
            a, b = (lo if lo is not None else 0.0), (hi if hi is not None else 2 * lo)
            w = max(b - a, 1e-3)
            c = crit.get(tid) or {}
            for i in range(n_per):
                if c and i % 10 == 0:  # oversample critical territory
                    v = rng.choice([x for x in (c.get("low"), c.get("high")) if x is not None])
                    v *= rng.uniform(0.5, 1.0) if v == c.get("low") else rng.uniform(1.0, 1.5)
                else:
                    v = rng.uniform(max(0.0, a - 0.8 * w), b + 0.8 * w)
                rows.append(_flag_row(v, lo, hi, c))
    return rows


def _flag_row(v, lo, hi, c):
    nan = float("nan")
    feats = [v, nan if lo is None else lo, nan if hi is None else hi]
    return feats, compute_flag(v, "=", lo, hi).value, is_critical(v, "=", c)


def gt_flag_rows(prefix: str):
    crit = reference.load_critical_values()
    rows = []
    for f in sorted(GT_DIR.glob(f"{prefix}*.json")):
        for r in json.loads(f.read_text("utf-8"))["tests"]:
            v, ref = r["value"], r["ref"]
            if v["number"] is None or v["comparator"] != "=" or r["expected_flag"] not in ("low", "normal", "high"):
                continue
            if ref["low"] is None and ref["high"] is None:
                continue
            feats, rule, critical = _flag_row(v["number"], ref["low"], ref["high"], crit.get(r["test_id"]))
            rows.append((feats, r["expected_flag"], critical, rule))
    return rows


def flag_test_split(seed: int = SEED) -> tuple[list[str], list[str]]:
    """Hold out whole tests (unseen ranges/scales) for the flag model."""
    ids = [t for t, v in reference.load_tests().items() if v.get("ref")]
    rng = random.Random(seed)
    crit = [t for t in ids if t in reference.load_critical_values()]
    rest = [t for t in ids if t not in crit]
    held = sorted(rng.sample(crit, 2) + rng.sample(rest, len(ids) // 4 - 2))
    return [t for t in ids if t not in held], held
