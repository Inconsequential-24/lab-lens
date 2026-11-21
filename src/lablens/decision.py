"""Next-step decision table (PLAN.md section 4): top to bottom, first match wins."""
from __future__ import annotations

from lablens import reference
from lablens.flag_engine import normalize_printed_flag
from lablens.schemas import Flag, FlaggedTest, Recommendation, Severity

_RANK = {Severity.UNKNOWN: 0, Severity.NORMAL: 1, Severity.MILD: 2, Severity.MARKED: 3,
         Severity.CRITICAL: 4}
CONFIRM = "please confirm this result with the lab"
VERIFY = "please verify"


def _rec(step, urgency, rule, ids, package=None, note=None) -> Recommendation:
    return Recommendation(next_step=step, urgency=urgency, rule_id=rule,
                          reason_test_ids=sorted(set(ids)), package_id=package, note=note)


def _package_match(abnormal: dict[str, FlaggedTest], packages: dict) -> str | None:
    flags = {(tid, t.flag.value) for tid, t in abnormal.items()}
    for pid, pkg in packages.items():
        if not set(abnormal) <= set(pkg.get("allowed_abnormal", [])):
            continue
        need_all = [(p["test"], p["flag"]) for p in pkg.get("requires_all", [])]
        need_any = [(p["test"], p["flag"]) for p in pkg.get("requires_any", [])]
        if need_all and not all(n in flags for n in need_all):
            continue
        if need_any and not any(n in flags for n in need_any):
            continue
        return pid
    return None


def route_next_step(tests: list[FlaggedTest], packages: dict | None = None) -> Recommendation:
    if packages is None:
        packages = reference.load_packages()
    recognised = [t for t in tests if t.test_id]
    # Duplicates: keep the most severe row per test_id for routing.
    abnormal: dict[str, FlaggedTest] = {}
    for t in recognised:
        if t.flag in (Flag.LOW, Flag.HIGH):
            cur = abnormal.get(t.test_id)
            if cur is None or _RANK[t.severity] > _RANK[cur.severity]:
                abnormal[t.test_id] = t
    printed_only = [t.test_id for t in recognised if t.flag is Flag.NORMAL
                    and normalize_printed_flag(t.printed_flag) in (Flag.LOW, Flag.HIGH)]
    note = CONFIRM if any(t.flag_disagrees_with_printed for t in recognised) else None

    critical = [t.test_id for t in recognised if t.is_critical]
    if critical:
        return _rec("doctor_consult", "urgent", "R1_critical", critical, note=note)
    marked = [tid for tid, t in abnormal.items() if t.severity is Severity.MARKED]
    if marked or len(abnormal) >= 3:
        return _rec("doctor_consult", "soon", "R2_marked", abnormal, note=note)
    if abnormal and not printed_only:
        pid = _package_match(abnormal, packages)
        if pid:
            return _rec("follow_up_test_package", "routine", "R3_package", abnormal, pid, note)
    if abnormal:
        return _rec("doctor_consult", "routine", "R4_mild", list(abnormal) + printed_only,
                    note=note)
    if printed_only:
        return _rec("doctor_consult", "routine", "R4_printed_flag", printed_only, note=CONFIRM)
    unverified = [t.test_id for t in recognised
                  if t.flag is Flag.UNKNOWN and not reference.is_informational(t.test_id)]
    if unverified:
        return _rec("no_action", "none", "R5_verify", unverified, note=VERIFY)
    return _rec("no_action", "none", "R6_normal", [])
