"""Front-desk policy calculations — deterministic, no LLM.

LLMs are unreliable at date math ("is 13 days after checkout inside 72 hours?").
These functions answer those questions exactly and cite the policy section, so
the agent explains a decision instead of computing one.

Policy numbers refer to data/policies/front_desk_policy.md.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from solstice.data.store import Reservation

CHECK_IN_TIME = time(15, 0)     # Policy 1
CHECK_OUT_TIME = time(11, 0)    # Policy 1
FRONT_DESK_COMP_LIMIT = 50      # Policy 7


def cancellation_terms(r: Reservation, now: datetime) -> dict:
    """Policies 2, 3, 4. Assumption: the 72 hours count back from 3:00 PM on the check-in date."""
    if r.status in ("Cancelled", "No-show", "Checked-out"):
        return {"policy": "2/3/4", "cancellable": False, "reason": f"Reservation status is {r.status}."}
    if r.rate_plan == "Advance Purchase":
        return {"policy": "3", "cancellable": False, "penalty": "Non-refundable, non-changeable",
                "reason": "Advance Purchase is non-refundable and non-changeable, including for weather, flights or illness. "
                          "Front desk cannot waive this. Travel insurance is the guest's recourse."}
    if r.rate_plan in ("Best Available Rate", "Corporate Negotiated"):
        deadline = datetime.combine(r.check_in, CHECK_IN_TIME) - timedelta(hours=72)
        free = now <= deadline
        return {"policy": "2", "cancellable": True, "free_cancellation": free,
                "free_cancellation_deadline": deadline.isoformat(timespec="minutes"),
                "penalty": None if free else f"One night's room and tax (${r.nightly_rate} + tax) charged to card on file"}
    return {"policy": "none", "cancellable": None,
            "reason": f"No written cancellation policy for rate plan '{r.rate_plan}'. Escalate rather than guess."}


def service_recovery_window(r: Reservation, now: datetime, reported_during_stay: bool = False) -> dict:
    """Policy 5. 72 hours from checkout; an in-stay report counts as reported on time."""
    deadline = datetime.combine(r.check_out, CHECK_OUT_TIME) + timedelta(hours=72)
    inside = reported_during_stay or now <= deadline
    return {
        "policy": "5",
        "window_closes": deadline.isoformat(timespec="minutes"),
        "reported_during_stay": reported_during_stay,
        "eligible_for_refund_credit_or_comp": inside,
        "if_not_eligible": None if inside else "Loyalty points may be offered as goodwill; no refund or comp.",
        "approval_needed": "Comp/refund amounts follow Policy 7 authority limits." if inside else None,
    }


def comp_authority(amounts_usd: list[float], includes_full_night: bool = False) -> dict:
    """Policy 7. Small issues in one stay are added together before checking the $50 limit."""
    total = round(sum(amounts_usd), 2)
    front_desk_ok = total <= FRONT_DESK_COMP_LIMIT and not includes_full_night
    return {"policy": "7", "total_usd": total, "front_desk_can_approve": front_desk_ok,
            "approver": "Front desk" if front_desk_ok else "AGM or GM sign-off required"}


def late_checkout_entitlement(r: Reservation) -> dict:
    """Policies 1 and 6."""
    tier = (r.loyalty_tier or "None").title()
    if tier == "Platinum":
        return {"policy": "6", "tier": tier, "latest_time": "2:00 PM", "guaranteed": True,
                "action": "Confirm directly. Guaranteed, no blackout dates."}
    if tier == "Gold":
        return {"policy": "6", "tier": tier, "latest_time": "1:00 PM", "guaranteed": False,
                "action": "Submit request; subject to same-day availability."}
    return {"policy": "1", "tier": tier, "latest_time": "front desk discretion", "guaranteed": False,
            "action": "Submit request; at front-desk discretion based on same-day availability."}


def as_of(today: date) -> datetime:
    """Demo 'now' = noon on the configured demo date."""
    return datetime.combine(today, time(12, 0))
