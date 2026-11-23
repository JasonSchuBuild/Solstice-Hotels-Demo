"""Data access layer: loads the Solstice CSV exports and serves *masked* views.

In production this module is replaced by adapters to the PMS (guest/reservation),
CRS (inventory/rates) and the loyalty/CRM system. The agent never talks to those
systems directly — it only calls tools, and tools only call this layer.

Raw records stay inside this module. Anything returned by a `*_view` function is
safe to hand to the model.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache

from solstice.config import get_settings
from solstice.data.masking import mask_email, mask_phone, scrub_free_text
from solstice.data.quality import DataIssue, run_checks, warnings_for


# ---------- helpers ----------

def _to_int(v: str) -> int | None:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _to_date(v: str) -> date | None:
    try:
        return date.fromisoformat(str(v).strip())
    except (TypeError, ValueError):
        return None


# ---------- records ----------

@dataclass
class Property:
    code: str
    name: str
    city: str
    state: str
    market_type: str
    total_rooms: int
    rooms_by_type: dict[str, int]
    base_rates: dict[str, int | None]   # None = missing/invalid in source data
    meeting_space_sqft: int
    max_meeting_capacity: int
    auto_approve_max_rooms: int
    auto_approve_max_discount_pct: int
    blackouts: list[tuple[date, date]]
    general_manager: str
    notes: str


@dataclass
class Reservation:
    guest_id: str
    first_name: str
    last_name: str
    email: str
    phone: str
    loyalty_tier: str
    loyalty_points: int
    member_since: str
    reservation_id: str
    property_code: str
    check_in: date
    check_out: date
    room_type: str
    rate_plan: str
    nightly_rate: int
    nights: int
    status: str
    payment_last4: str          # never leaves this module
    marketing_opt_in: bool
    special_requests: str
    internal_notes: str


@dataclass
class Inquiry:
    raw: dict                   # original row, for audit
    inquiry_id: str
    date_received: date | None
    company: str
    contact_name: str
    contact_email: str
    contact_phone: str
    event_type: str
    preferred_property: str
    alternate_ok: bool
    arrival: date | None
    departure: date | None
    nights: int | None
    rooms_requested: int | None
    rooms_requested_text: str
    room_type: str
    requested_discount_pct: int | None
    budget_per_night: int | None
    meeting_space_needed: bool
    meeting_capacity_needed: int | None
    special_requests: str


@dataclass
class DataStore:
    properties: dict[str, Property]
    reservations: list[Reservation]
    inquiries: dict[str, Inquiry]
    data_issues: list[DataIssue] = field(default_factory=list)

    def warnings_for(self, *record_ids: str) -> list[dict]:
        return warnings_for(self.data_issues, *record_ids)

    # ----- lookups -----

    def property(self, code: str) -> Property | None:
        return self.properties.get((code or "").upper().strip())

    def reservation(self, reservation_id: str) -> Reservation | None:
        rid = (reservation_id or "").upper().strip()
        return next((r for r in self.reservations if r.reservation_id == rid), None)

    def reservations_for_guest(self, guest_id: str) -> list[Reservation]:
        return [r for r in self.reservations if r.guest_id == guest_id]

    def verify_guest(self, reservation_id: str, last_name: str) -> Reservation | None:
        """Guest self-identification: confirmation number + last name must both match."""
        r = self.reservation(reservation_id)
        if r and r.last_name.strip().lower() == (last_name or "").strip().lower():
            return r
        return None

    def booked_rooms(self, code: str, room_type: str, night: date) -> int:
        """Rooms of a type already held by individual reservations on a given night."""
        return sum(
            1 for r in self.reservations
            if r.property_code == code and r.room_type == room_type
            and r.status in ("Confirmed", "Checked-in")
            and r.check_in <= night < r.check_out
        )


# ---------- masked views (the only shapes the model ever sees) ----------

def _property_label(code: str) -> str:
    p = get_store().property(code)
    return f"{p.name} ({p.city}, {p.state})" if p else code


def reservation_view(r: Reservation, audience: str = "guest") -> dict:
    view = {
        "reservation_id": r.reservation_id,
        "guest_name": f"{r.first_name} {r.last_name}",
        "property_code": r.property_code,
        "property_name": _property_label(r.property_code),   # so the model copies the city instead of guessing it from the code
        "check_in": r.check_in.isoformat(),
        "check_out": r.check_out.isoformat(),
        "nights": r.nights,
        "room_type": r.room_type,
        "rate_plan": r.rate_plan,
        "nightly_rate_usd": r.nightly_rate,
        "status": r.status,
        "loyalty_tier": r.loyalty_tier,
        "loyalty_points": r.loyalty_points,
        "special_requests": scrub_free_text(r.special_requests),
        "card_on_file": bool(r.payment_last4),
    }
    if audience == "staff":
        view.update({
            "guest_id": r.guest_id,
            "email": mask_email(r.email),
            "phone": mask_phone(r.phone),
            "member_since": r.member_since,
        })
    # Internal notes guide the agent's handling but are labeled so the prompt can
    # tell it never to read them back to a guest word-for-word.
    view["internal_notes_for_staff_handling"] = scrub_free_text(r.internal_notes)
    return view


def property_view(p: Property) -> dict:
    return {
        "property_code": p.code,
        "name": p.name,
        "city": f"{p.city}, {p.state}",
        "market_type": p.market_type,
        "total_rooms": p.total_rooms,
        "rooms_by_type": p.rooms_by_type,
        "published_base_rates_usd": {k: v for k, v in p.base_rates.items() if v is not None},
        "rate_data_missing_for": [k for k, v in p.base_rates.items() if v is None],
        "meeting_space_sqft": p.meeting_space_sqft,
        "max_meeting_capacity": p.max_meeting_capacity,
        "general_manager": p.general_manager,
        "notes": p.notes,
    }


def inquiry_view(i: Inquiry) -> dict:
    """Inquiry as Sales sees it. Contact details masked."""
    return {
        "inquiry_id": i.inquiry_id,
        "date_received": i.date_received.isoformat() if i.date_received else None,
        "company": i.company,
        "contact_name": i.contact_name,
        "contact_email": mask_email(i.contact_email),
        "contact_phone": mask_phone(i.contact_phone) or "not provided",
        "event_type": i.event_type,
        "preferred_property": i.preferred_property,
        "alternate_property_ok": i.alternate_ok,
        "arrival": i.arrival.isoformat() if i.arrival else None,
        "departure": i.departure.isoformat() if i.departure else None,
        "rooms_requested": i.rooms_requested if i.rooms_requested is not None else i.rooms_requested_text or None,
        "room_type": i.room_type or None,
        "requested_discount_pct": i.requested_discount_pct,
        "budget_per_night_usd": i.budget_per_night,
        "meeting_space_needed": i.meeting_space_needed,
        "meeting_capacity_needed": i.meeting_capacity_needed,
        "special_requests": scrub_free_text(i.special_requests),
    }


# ---------- loading ----------

ROOM_TYPES = {
    "Standard King": "standard_king_rooms",
    "Standard Double": "standard_double_rooms",
    "Deluxe King": "deluxe_king_rooms",
    "Suite": "suite_rooms",
    "Accessible King": "accessible_rooms",
}
RATE_FOR_TYPE = {
    "Standard King": "base_rate_standard",
    "Standard Double": "base_rate_standard",
    "Accessible King": "base_rate_standard",   # assumption: accessible rooms priced as standard
    "Deluxe King": "base_rate_deluxe",
    "Suite": "base_rate_suite",
}


def _parse_blackouts(text: str) -> list[tuple[date, date]]:
    out = []
    for chunk in (text or "").split(";"):
        if " to " in chunk:
            a, b = (_to_date(x) for x in chunk.split(" to "))
            if a and b:
                out.append((a, b))
    return out


def _read_csv(path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _load_properties(rows) -> dict[str, Property]:
    props = {}
    for r in rows:
        rates = {}
        for room_type, col in RATE_FOR_TYPE.items():
            v = _to_int(r[col])
            if v is None or v <= 0:
                v = None   # invalid rate: never quoted (logged by data/quality.py)
            rates[room_type] = v
        rooms = {t: _to_int(r[c]) or 0 for t, c in ROOM_TYPES.items()}
        total = _to_int(r["total_rooms"]) or 0
        props[r["property_code"]] = Property(
            code=r["property_code"], name=r["property_name"], city=r["city"], state=r["state"],
            market_type=r["market_type"], total_rooms=total, rooms_by_type=rooms, base_rates=rates,
            meeting_space_sqft=_to_int(r["meeting_space_sqft"]) or 0,
            max_meeting_capacity=_to_int(r["max_meeting_capacity"]) or 0,
            auto_approve_max_rooms=_to_int(r["group_block_auto_approve_max_rooms"]) or 0,
            auto_approve_max_discount_pct=_to_int(r["max_discount_auto_approve_pct"]) or 0,
            blackouts=_parse_blackouts(r["blackout_dates"]),
            general_manager=r["general_manager"], notes=r["notes"],
        )
    return props


def _load_reservations(rows) -> list[Reservation]:
    return [
        Reservation(
            guest_id=r["guest_id"], first_name=r["first_name"], last_name=r["last_name"],
            email=r["email"], phone=r["phone"], loyalty_tier=r["loyalty_tier"] or "None",
            loyalty_points=_to_int(r["loyalty_points"]) or 0, member_since=r["member_since"],
            reservation_id=r["reservation_id"], property_code=r["property_code"],
            check_in=_to_date(r["check_in_date"]), check_out=_to_date(r["check_out_date"]),
            room_type=r["room_type"], rate_plan=r["rate_plan"],
            nightly_rate=_to_int(r["nightly_rate"]) or 0, nights=_to_int(r["total_nights"]) or 0,
            status=r["reservation_status"], payment_last4=r["payment_method_last4"],
            marketing_opt_in=r["marketing_opt_in"] == "Y",
            special_requests=r["special_requests"], internal_notes=r["internal_notes"],
        )
        for r in rows
    ]


def _load_inquiries(rows) -> dict[str, Inquiry]:
    # NOTE: the source export has a `notes` column that reads like an analyst's
    # expected outcome. We deliberately do NOT give it to the agent — the agent
    # must reach conclusions from the rules. The notes are used by the test
    # suite as expected answers instead (see tests/test_group_rules.py).
    out = {}
    for r in rows:
        out[r["inquiry_id"]] = Inquiry(
            raw=r, inquiry_id=r["inquiry_id"], date_received=_to_date(r["date_received"]),
            company=r["company_name"], contact_name=r["contact_name"],
            contact_email=r["contact_email"], contact_phone=r["contact_phone"],
            event_type=r["event_type"], preferred_property=r["preferred_property_code"],
            alternate_ok=r["alternate_property_ok"] == "Y",
            arrival=_to_date(r["arrival_date"]), departure=_to_date(r["departure_date"]),
            nights=_to_int(r["nights"]), rooms_requested=_to_int(r["rooms_requested"]),
            rooms_requested_text=r["rooms_requested"], room_type=r["room_type_preference"],
            requested_discount_pct=_to_int(r["requested_discount_pct"]),
            budget_per_night=_to_int(r["stated_budget_per_night"]),
            meeting_space_needed=r["meeting_space_needed"] == "Y",
            meeting_capacity_needed=_to_int(r["meeting_capacity_needed"]),
            special_requests=r["special_requests"],
        )
    return out


def build_store(props: list[dict], res: list[dict], inq: list[dict]) -> DataStore:
    """A store from raw CSV rows (used by get_store, and by tests on generated data)."""
    return DataStore(
        properties=_load_properties(props),
        reservations=_load_reservations(res),
        inquiries=_load_inquiries(inq),
        data_issues=run_checks(props, res, inq),   # validate every row once at load
    )


@lru_cache(maxsize=1)
def get_store() -> DataStore:
    s = get_settings()
    return build_store(*(_read_csv(s.path(k)) for k in ("properties_csv", "guests_csv", "inquiries_csv")))
