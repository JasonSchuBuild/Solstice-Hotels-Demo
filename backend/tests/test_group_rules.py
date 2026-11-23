"""Group rules engine vs. the 10 sample inquiries.

The source CSV's `notes` column reads like an analyst's expected outcome. We use
it as an answer key here (and hide it from the agent). In three cases the engine
finds MORE than the notes did — those are asserted explicitly below and called
out in docs/DATA_NOTES.md.
"""
import pytest

from solstice.data.store import get_store
from solstice.rules.group_rules import GroupRequest, evaluate, find_alternatives


def _eval(inq_id):
    s = get_store()
    i = s.inquiries[inq_id]
    return evaluate(s, GroupRequest(i.preferred_property, i.arrival, i.departure, i.rooms_requested,
                                    i.room_type, i.requested_discount_pct, i.budget_per_night,
                                    i.meeting_capacity_needed, i.event_type))


def _flags(ev):
    return {c.rule for c in ev.checks if c.status in ("flag", "block")}


@pytest.mark.parametrize("inq, decision, must_flag", [
    ("INQ-2001", "READY_TO_SEND", set()),
    ("INQ-2002", "NEEDS_HUMAN_APPROVAL", {"block_size", "discount"}),
    ("INQ-2003", "CANNOT_ACCOMMODATE", {"blackout_dates"}),
    ("INQ-2004", "NEEDS_CLARIFICATION", set()),
    ("INQ-2005", "CANNOT_ACCOMMODATE", {"meeting_capacity"}),
    ("INQ-2006", "READY_TO_SEND", set()),
    ("INQ-2007", "CANNOT_ACCOMMODATE", {"routing"}),
    ("INQ-2008", "NEEDS_HUMAN_APPROVAL", set()),
    ("INQ-2009", "NEEDS_HUMAN_APPROVAL", {"discount"}),
    ("INQ-2010", "CANNOT_ACCOMMODATE", {"discount"}),
])
def test_inquiry_outcomes(inq, decision, must_flag):
    ev = _eval(inq)
    assert ev.decision == decision
    assert must_flag <= _flags(ev)


def test_2009_flags_only_the_discount():
    """The brief's trap: don't reject the whole inquiry for one problem."""
    assert _flags(_eval("INQ-2009")) == {"discount"}


def test_2008_youth_group_requires_insurance_followup():
    assert any("insurance" in f.lower() for f in _eval("INQ-2008").required_followups)


def test_2010_seasonal_cap_applies():
    ev = _eval("INQ-2010")
    assert ev.pricing["auto_approve_ceiling_pct"] == 8


# ---- Findings beyond the analyst notes ----

def test_2010_is_also_inside_sacramento_blackout():
    """Notes only mention the seasonal cap; 2027-05-04..06 is inside SAC blackout 05-03..05-07."""
    assert "blackout_dates" in _flags(_eval("INQ-2010"))


def test_2003_ballroom_also_too_small():
    """250-person keynote vs. 220 max capacity at SOL-AUS."""
    assert "meeting_capacity" in _flags(_eval("INQ-2003"))


def test_2005_and_2008_also_exceed_room_limit():
    assert "block_size" in _flags(_eval("INQ-2005"))   # 22 > 20 at SAC
    assert "block_size" in _flags(_eval("INQ-2008"))   # 28 > 20 at CMH


# ---- Pricing / data quality ----

def test_never_quotes_invalid_rate():
    """SOL-PVD suite rate is -395 in the source data."""
    s = get_store()
    from datetime import date
    ev = evaluate(s, GroupRequest("SOL-PVD", date(2026, 9, 1), date(2026, 9, 3), 5, "Suite"))
    assert ev.pricing is None
    assert "rate_data" in _flags(ev)


def test_pricing_math():
    p = _eval("INQ-2001").pricing
    assert p["rate_within_rules"] == round(219 * 0.90, 2)
    assert p["total_within_rules"] == round(219 * 0.90 * 2 * 18, 2)


def test_alternatives_rank_workable_first():
    s = get_store()
    i = s.inquiries["INQ-2005"]
    alts = find_alternatives(s, GroupRequest(i.preferred_property, i.arrival, i.departure, i.rooms_requested,
                                             i.room_type, i.requested_discount_pct, i.budget_per_night,
                                             i.meeting_capacity_needed, i.event_type), exclude="SOL-SAC")
    assert alts[0]["decision"] in ("READY_TO_SEND", "NEEDS_HUMAN_APPROVAL")


def _alts_for(store, qid):
    i = store.inquiries[qid]
    return find_alternatives(store, GroupRequest(i.preferred_property, i.arrival, i.departure, i.rooms_requested,
                                                 i.room_type, i.requested_discount_pct, i.budget_per_night,
                                                 i.meeting_capacity_needed, i.event_type),
                             exclude=i.preferred_property)


def test_alternatives_rank_nearest_first(monkeypatch):
    """Found by the synthetic evals: ranking by price alone sent 12 of 14 alternatives out of state (7 of
    them to one Houston hotel). Among workable options, same city beats same state beats elsewhere."""
    from solstice.data import store as store_mod
    monkeypatch.setenv("SOLSTICE_DATA_DIR", "data/synthetic")
    store_mod.get_store.cache_clear()
    try:
        s = store_mod.get_store()
        order = ("same city", "same state", "other state")
        checked = near_first = 0
        for qid, i in s.inquiries.items():
            if i.preferred_property not in s.properties or not i.rooms_requested or not i.arrival:
                continue
            alts = _alts_for(s, qid)
            workable = [a for a in alts if a["decision"] in ("READY_TO_SEND", "NEEDS_HUMAN_APPROVAL")]
            ranks = [order.index(a["proximity"]) for a in workable]
            assert ranks == sorted(ranks), qid                      # never a farther hotel ahead of a nearer one
            assert alts[:len(workable)] == workable, qid            # and workable options always come first
            checked += 1
            near_first += bool(ranks) and ranks[0] < 2
        assert checked >= 80 and near_first >= 30, (checked, near_first)

        # The tool hands the agent only the best few: 99 alternatives made replies hit the token cap.
        from solstice.tools.group_tools import MAX_ALTERNATIVES, find_alternative_properties
        from solstice.tools.registry import ToolContext
        i = s.inquiries["INQ-9055"]
        out = find_alternative_properties(
            ToolContext(agent="group_sales", mode="staff", session_id="t"), property_code=i.preferred_property,
            arrival=i.arrival.isoformat(), departure=i.departure.isoformat(), rooms=i.rooms_requested,
            room_type=i.room_type, meeting_capacity_needed=i.meeting_capacity_needed)
        assert len(out["alternatives"]) == MAX_ALTERNATIVES and out["properties_checked"] == len(s.properties) - 1
        assert sum(out["workable_by_proximity"].values()) == out["workable"]
    finally:
        store_mod.get_store.cache_clear()
