from datetime import datetime

from solstice.data.store import get_store
from solstice.rules.guest_policies import (
    cancellation_terms, comp_authority, late_checkout_entitlement, service_recovery_window,
)


def r(rid):
    return get_store().reservation(rid)


def test_service_recovery_13_days_late_is_outside_window():
    # G10012 called 2026-07-05, checked out 2026-06-22, never reported during stay
    out = service_recovery_window(r("R55012"), datetime(2026, 7, 5, 10))
    assert out["eligible_for_refund_credit_or_comp"] is False
    assert "points" in out["if_not_eligible"].lower()


def test_service_recovery_reported_during_stay_counts():
    out = service_recovery_window(r("R55012"), datetime(2026, 7, 5, 10), reported_during_stay=True)
    assert out["eligible_for_refund_credit_or_comp"] is True


def test_advance_purchase_not_cancellable():
    assert cancellation_terms(r("R55002"), datetime(2026, 7, 1))["cancellable"] is False


def test_bar_free_cancel_deadline():
    out = cancellation_terms(r("R55001"), datetime(2026, 7, 10, 12))   # check-in 2026-07-14
    assert out["free_cancellation"] is True
    assert out["free_cancellation_deadline"] == "2026-07-11T15:00"


def test_bar_inside_72h_charges_one_night():
    out = cancellation_terms(r("R55001"), datetime(2026, 7, 12, 12))
    assert out["free_cancellation"] is False


def test_comp_limit_adds_up_small_items():
    assert comp_authority([30, 25])["front_desk_can_approve"] is False
    assert comp_authority([45])["front_desk_can_approve"] is True
    assert comp_authority([0], includes_full_night=True)["front_desk_can_approve"] is False


def test_late_checkout_by_tier():
    assert late_checkout_entitlement(r("R55004"))["guaranteed"] is True     # Platinum
    assert late_checkout_entitlement(r("R55003"))["latest_time"] == "1:00 PM"  # Gold
    assert late_checkout_entitlement(r("R55023"))["guaranteed"] is False    # None
