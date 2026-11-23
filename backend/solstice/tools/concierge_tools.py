"""Concierge tools: guest identity, reservation facts, policy checks, requests.

Access rule enforced in code (not just the prompt): in guest mode a caller must
verify with confirmation number + last name, and can then only touch their own
reservations. Staff mode can look up any reservation, still masked.
"""
from __future__ import annotations

from solstice.config import get_settings
from solstice.data.store import Reservation, _property_label, get_store, property_view, reservation_view
from solstice.rules import guest_policies as gp
from solstice import runtime_store
from solstice.tools.registry import ToolContext, ToolError, attach_data_warnings, tool

RID = {"type": "string", "description": "Reservation / confirmation number, e.g. R55001"}


def _reservation_for(ctx: ToolContext, reservation_id: str) -> Reservation:
    r = get_store().reservation(reservation_id)
    if ctx.mode == "guest":
        if not ctx.verified_guest_id:
            raise ToolError("Guest is not verified. Ask for confirmation number and last name, then call verify_guest.")
        if not r or r.guest_id != ctx.verified_guest_id:
            raise ToolError("That reservation is not on this verified guest's profile.")
    if not r:
        raise ToolError(f"No reservation found for '{reservation_id}'.")
    return r


def _audience(ctx: ToolContext) -> str:
    return "staff" if ctx.mode == "staff" else "guest"


# ---------------- identity & lookup ----------------

@tool("verify_guest",
      "Verify a guest's identity with their confirmation number and last name. Required before sharing any "
      "reservation details in guest mode. Returns all of the guest's reservations on success.",
      {"reservation_id": RID, "last_name": {"type": "string"}}, ["reservation_id", "last_name"])
def verify_guest(ctx: ToolContext, reservation_id: str, last_name: str) -> dict:
    limit = get_settings().max_failed_verifications
    if ctx.failed_verifications >= limit:
        raise ToolError("Verification is locked for this chat after too many failed attempts. Do not retry. "
                        "Offer to hand off to the front desk with escalate_to_staff.")
    store = get_store()
    r = store.verify_guest(reservation_id, last_name)
    if not r:
        ctx.failed_verifications += 1
        left = limit - ctx.failed_verifications
        runtime_store.append("audit", {"event": "verification_failed", "session_id": ctx.session_id,
                                       "agent": ctx.agent, "mode": ctx.mode, "attempts_left": left})
        return {"verified": False, "attempts_left": left,
                "message": "No match for that confirmation number and last name."}
    ctx.verified_guest_id = r.guest_id
    mine = store.reservations_for_guest(r.guest_id)
    out = {"verified": True, "reservations": [reservation_view(x, _audience(ctx)) for x in mine]}
    return attach_data_warnings(ctx, out, *[x.reservation_id for x in mine], *[x.property_code for x in mine])


@tool("lookup_reservation", "Staff only: look up any reservation by confirmation number (masked).",
      {"reservation_id": RID}, ["reservation_id"], modes=("staff",))
def lookup_reservation(ctx: ToolContext, reservation_id: str) -> dict:
    r = _reservation_for(ctx, reservation_id)
    return attach_data_warnings(ctx, reservation_view(r, "staff"), r.reservation_id, r.property_code)


@tool("search_guests", "Staff only: find reservations by guest last name. Several guests can share a name — confirm with the confirmation number.",
      {"last_name": {"type": "string"}}, ["last_name"], modes=("staff",))
def search_guests(ctx: ToolContext, last_name: str) -> dict:
    hits = [r for r in get_store().reservations if r.last_name.lower() == last_name.strip().lower()]
    return attach_data_warnings(ctx, {"matches": [reservation_view(r, "staff") for r in hits]},
                                *[r.reservation_id for r in hits])


LIST_FOCUS = ("arriving", "in_house", "recent")
LIST_MAX = 25   # a scoped shortlist, never a dump of every guest


@tool("list_reservations",
      "Staff only: a short, scoped list of reservations to see who is in focus. Scope it with a property and a focus: "
      "'arriving' (upcoming arrivals, soonest first), 'in_house' (staying tonight) or 'recent' (most recent past "
      "arrivals, newest first). Capped at 25 rows; compact fields only (use lookup_reservation for details). "
      "Show the result as a markdown table with reservation_id as the first column.",
      {"property_code": {"type": "string", "description": "Optional, e.g. SOL-CHI. Omit for all properties."},
       "focus": {"type": "string", "enum": list(LIST_FOCUS), "description": "Default 'arriving'."},
       "status": {"type": "string", "description": "Optional exact status filter, e.g. Confirmed, Checked-in, Cancelled."},
       "limit": {"type": "integer", "description": f"Rows to return, default 10, max {LIST_MAX}."}},
      [], modes=("staff",))
def list_reservations(ctx: ToolContext, property_code: str = "", focus: str = "arriving",
                      status: str = "", limit: int = 10) -> dict:
    store, today = get_store(), get_settings().today
    focus = (focus or "arriving").strip().lower()
    if focus not in LIST_FOCUS:
        raise ToolError(f"Unknown focus '{focus}'. Use one of: {', '.join(LIST_FOCUS)}.")
    code = (property_code or "").strip().upper()
    if code and not store.property(code):
        raise ToolError(f"Unknown property code '{property_code}'. Valid: {', '.join(store.properties)}.")
    limit = max(1, min(int(limit or 10), LIST_MAX))

    rows = [r for r in store.reservations if not code or r.property_code == code]
    if status.strip():
        rows = [r for r in rows if r.status.lower() == status.strip().lower()]
    if focus == "arriving":
        rows = sorted((r for r in rows if r.check_in >= today and r.status == "Confirmed"), key=lambda r: r.check_in)
    elif focus == "in_house":
        rows = sorted((r for r in rows if r.check_in <= today < r.check_out and r.status in ("Confirmed", "Checked-in")),
                      key=lambda r: r.check_in)
    else:
        rows = sorted((r for r in rows if r.check_in <= today), key=lambda r: r.check_in, reverse=True)

    shown = rows[:limit]
    out = {"as_of": today.isoformat(), "focus": focus, "property_code": code or "all",
           "total_matching": len(rows), "shown": len(shown),
           "reservations": [{
               "reservation_id": r.reservation_id, "guest_name": f"{r.first_name} {r.last_name}",
               "property_code": r.property_code, "property_name": _property_label(r.property_code),
               "check_in": r.check_in.isoformat(), "check_out": r.check_out.isoformat(), "room_type": r.room_type,
               "loyalty_tier": r.loyalty_tier, "status": r.status,
               "has_special_requests": bool(r.special_requests.strip())} for r in shown]}
    return attach_data_warnings(ctx, out, *[r.reservation_id for r in shown])


@tool("get_property_info",
      "Facts about a Solstice property: location, room types and counts, published base rates, meeting space, "
      "GM and notes. Does NOT include parking, amenities or live availability.",
      {"property_code": {"type": "string", "description": "e.g. SOL-CHI"}}, ["property_code"],
      agents=("concierge", "group_sales"))
def get_property_info(ctx: ToolContext, property_code: str) -> dict:
    p = get_store().property(property_code)
    if not p:
        raise ToolError(f"Unknown property code '{property_code}'. Valid: {', '.join(get_store().properties)}")
    return attach_data_warnings(ctx, property_view(p), p.code)


# ---------------- policy calculators ----------------

@tool("check_cancellation_terms",
      "Exact cancellation terms for a reservation right now (free-cancel deadline, penalty, or non-refundable). "
      "Use instead of calculating dates yourself.",
      {"reservation_id": RID}, ["reservation_id"])
def check_cancellation_terms(ctx: ToolContext, reservation_id: str) -> dict:
    r = _reservation_for(ctx, reservation_id)
    return attach_data_warnings(ctx, gp.cancellation_terms(r, gp.as_of(get_settings().today)), r.reservation_id)


@tool("check_service_recovery_eligibility",
      "Whether a complaint about a stay is inside the 72-hour service-recovery window (Policy 5).",
      {"reservation_id": RID,
       "reported_during_stay": {"type": "boolean", "description": "True if the guest says they told staff during the stay."}},
      ["reservation_id"])
def check_service_recovery(ctx: ToolContext, reservation_id: str, reported_during_stay: bool = False) -> dict:
    r = _reservation_for(ctx, reservation_id)
    return attach_data_warnings(ctx, gp.service_recovery_window(r, gp.as_of(get_settings().today), reported_during_stay),
                                r.reservation_id)


@tool("check_comp_authority",
      "Whether a set of comps for one stay is inside front-desk authority ($50 total, Policy 7) or needs AGM/GM.",
      {"amounts_usd": {"type": "array", "items": {"type": "number"}},
       "includes_full_night": {"type": "boolean"}}, ["amounts_usd"], modes=("staff",))
def check_comp_authority(ctx: ToolContext, amounts_usd: list[float], includes_full_night: bool = False) -> dict:
    return gp.comp_authority(amounts_usd, includes_full_night)


# ---------------- requests ----------------

@tool("request_late_checkout",
      "Request late checkout. Platinum is confirmed automatically (2 PM, guaranteed); everyone else is submitted "
      "to the front desk as a pending request.",
      {"reservation_id": RID}, ["reservation_id"])
def request_late_checkout(ctx: ToolContext, reservation_id: str) -> dict:
    r = _reservation_for(ctx, reservation_id)
    if r.status not in ("Confirmed", "Checked-in"):
        raise ToolError(f"Reservation is {r.status}; late checkout not applicable.")
    ent = gp.late_checkout_entitlement(r)
    rec = runtime_store.append("requests", {
        "request_id": runtime_store.new_id("REQ"), "type": "late_checkout", "reservation_id": r.reservation_id,
        "property_code": r.property_code, "status": "CONFIRMED" if ent["guaranteed"] else "PENDING_FRONT_DESK",
        "detail": f"Late checkout to {ent['latest_time']} on {r.check_out}", "policy": ent["policy"],
        "session_id": ctx.session_id,
    })
    return {**ent, "request_id": rec["request_id"], "status": rec["status"]}


SERVICE_TYPES = ["early_check_in", "rollaway_bed", "bedding_or_pillows", "room_location", "connecting_rooms",
                 "celebration_or_turndown", "accessibility", "amenity_booking", "other"]


@tool("submit_service_request",
      "Send a request (early check-in, rollaway, bedding, room location, amenity booking, etc.) to the property's "
      "front desk queue. Requests are PENDING until the property confirms — never tell the guest it is guaranteed.",
      {"reservation_id": RID, "request_type": {"type": "string", "enum": SERVICE_TYPES},
       "details": {"type": "string", "description": "What the guest asked for, in plain words"}},
      ["reservation_id", "request_type", "details"])
def submit_service_request(ctx: ToolContext, reservation_id: str, request_type: str, details: str) -> dict:
    r = _reservation_for(ctx, reservation_id)
    rec = runtime_store.append("requests", {
        "request_id": runtime_store.new_id("REQ"), "type": request_type, "reservation_id": r.reservation_id,
        "property_code": r.property_code, "status": "PENDING_FRONT_DESK", "detail": details,
        "session_id": ctx.session_id,
    })
    return {"request_id": rec["request_id"], "status": rec["status"],
            "message": "Sent to the property team; they confirm based on same-day availability."}
