import pytest

from lablens import config
from lablens.budget import BudgetExceeded, BudgetGuard, cost_inr


def test_cost_matches_plan_rates():
    assert cost_inr(1_000_000, 0) == pytest.approx(22.5)
    assert cost_inr(0, 1_000_000) == pytest.approx(135.0)
    assert cost_inr(0, 500_000, 500_000) == pytest.approx(135.0)  # thinking billed as output
    assert cost_inr(7700, 2100) == pytest.approx(0.45, abs=0.01)
    with pytest.raises(ValueError):
        cost_inr(-1, 0)


def test_plan_cap_constants():
    assert config.BUDGET_CAP_INR == 500.0 and config.BUDGET_GUARD_INR == 450.0


def test_record_persists_and_counts_failures(tmp_path):
    g = BudgetGuard(tmp_path / "b.sqlite")
    g.record("extract", 1_000_000, 0, status="error")
    g.record("extract", 0, 0, 1_000_000, status="retry")
    assert BudgetGuard(tmp_path / "b.sqlite").spent_inr() == pytest.approx(157.5)


def test_guard_trips_before_passing_limit(tmp_path):
    g = BudgetGuard(tmp_path / "b.sqlite", guard_inr=150.0)
    g.record("render_en", 0, 1_000_000)  # ₹135
    assert g.allows(0, 100_000)  # +₹13.5 -> 148.5
    with pytest.raises(BudgetExceeded):
        g.check(0, 200_000)  # +₹27 -> 162


def test_concurrent_reservations_never_exceed_guard(tmp_path):
    import threading
    path = tmp_path / "b.sqlite"
    BudgetGuard(path, guard_inr=100.0)
    each = cost_inr(0, 100_000)  # ₹13.5 -> at most 7 fit
    ok, barrier = [], threading.Barrier(20)

    def worker():
        g = BudgetGuard(path, guard_inr=100.0)
        barrier.wait()
        try:
            rid = g.check(0, 100_000)
        except BudgetExceeded:
            return
        ok.append(rid)
        g.record("render_en", 0, 100_000, reservation=rid)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(ok) == 7
    assert BudgetGuard(path).spent_inr() == pytest.approx(7 * each)


def test_reservation_settles_and_releases(tmp_path):
    g = BudgetGuard(tmp_path / "b.sqlite", guard_inr=150.0)
    rid = g.check(0, 1_000_000)  # reserves ₹135
    assert g.spent_inr() == pytest.approx(135.0)
    with pytest.raises(BudgetExceeded):
        g.check(0, 200_000)
    g.record("render_en", 0, 100_000, reservation=rid)  # settles at actual ₹13.5
    assert g.spent_inr() == pytest.approx(13.5)
    rid2 = g.check(0, 100_000)
    g.release(rid2)
    assert g.spent_inr() == pytest.approx(13.5)
