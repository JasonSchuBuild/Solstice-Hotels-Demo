"""list_reservations: scoped, capped, staff-only, masked."""
import pytest

from solstice.tools.concierge_tools import LIST_MAX, list_reservations
from solstice.tools.registry import ToolContext, ToolError, tools_for

STAFF = ToolContext(agent="concierge", mode="staff", session_id="t")


def test_staff_only():
    assert "list_reservations" in {t.name for t in tools_for("concierge", "staff")}
    assert "list_reservations" not in {t.name for t in tools_for("concierge", "guest")}


def test_arriving_is_soonest_first_and_confirmed_only():
    out = list_reservations(STAFF, focus="arriving", limit=25)
    dates = [r["check_in"] for r in out["reservations"]]
    assert dates == sorted(dates)
    assert all(r["status"] == "Confirmed" and r["check_in"] >= out["as_of"] for r in out["reservations"])


def test_scoped_to_property():
    out = list_reservations(STAFF, property_code="sol-chi", focus="recent")
    assert out["property_code"] == "SOL-CHI"
    assert all(r["property_code"] == "SOL-CHI" for r in out["reservations"])


def test_recent_is_newest_first():
    dates = [r["check_in"] for r in list_reservations(STAFF, focus="recent", limit=25)["reservations"]]
    assert dates == sorted(dates, reverse=True)


def test_limit_is_capped_and_total_reported():
    out = list_reservations(STAFF, focus="recent", limit=9999)
    assert out["shown"] <= LIST_MAX
    assert out["total_matching"] >= out["shown"]


def test_rows_are_compact_and_carry_no_contact_details():
    row = list_reservations(STAFF, focus="recent", limit=1)["reservations"][0]
    assert set(row) == {"reservation_id", "guest_name", "property_code", "property_name", "check_in", "check_out",
                        "room_type", "loyalty_tier", "status", "has_special_requests"}


def test_bad_inputs_are_refused():
    with pytest.raises(ToolError):
        list_reservations(STAFF, property_code="SOL-NOPE")
    with pytest.raises(ToolError):
        list_reservations(STAFF, focus="everyone")


def test_views_name_the_city_so_the_model_does_not_guess_it():
    from solstice.data.store import get_store, reservation_view
    r = get_store().reservation("R55004")
    assert "Denver" in reservation_view(r, "staff")["property_name"]
    assert "Denver" in reservation_view(r, "guest")["property_name"]
