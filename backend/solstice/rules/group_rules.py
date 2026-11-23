"""Group booking rules engine — deterministic, no LLM.

The agent gathers requirements and explains results; this module decides.
Keeping pricing and approval logic out of the model is what guarantees the agent
can't "talk itself into" a discount or invent a rate.

Decision outcomes (worst wins):
  NEEDS_CLARIFICATION  - required info missing; ask before pricing anything
  CANNOT_ACCOMMODATE   - hard stop at this property (blackout, capacity, routing)
  NEEDS_HUMAN_APPROVAL - priced, but outside auto-approve rules -> Sales/GM
  READY_TO_SEND        - inside all rules; Sales can send the draft as-is
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from solstice.config import get_settings, load_yaml
from solstice.data.store import DataStore, Property

DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SEVERITY = {"pass": 0, "info": 0, "flag": 1, "block": 2}


@dataclass
class GroupRequest:
    property_code: str
    arrival: date | None
    departure: date | None
    rooms: int | None
    room_type: str | None
    requested_discount_pct: int | None = 0
    budget_per_night: int | None = None
    meeting_capacity_needed: int | None = None
    event_type: str = ""


@dataclass
class Check:
    rule: str
    status: str          # pass | info | flag | block
    detail: str
    source: str          # where the rule comes from (data column, policy, config)


@dataclass
class Evaluation:
    property_code: str
    property_name: str
    decision: str
    checks: list[Check] = field(default_factory=list)
    missing_info: list[str] = field(default_factory=list)
    required_followups: list[str] = field(default_factory=list)
    pricing: dict | None = None
    availability: dict | None = None
    suggested_dates: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _rules() -> dict:
    # Re-read when config/group_rules.yaml changes, so a live edit applies to the next check.
    return load_yaml(get_settings().path("group_rules"))


def _nights(a: date, d: date) -> list[date]:
    return [a + timedelta(days=i) for i in range((d - a).days)]


def _overlaps_blackout(p: Property, a: date, d: date) -> tuple[date, date] | None:
    for start, end in p.blackouts:
        if a <= end and d > start:      # any night inside [start, end]
            return start, end
    return None


def _ceiling_for(p: Property, nights: list[date]) -> tuple[int, str]:
    """Property discount ceiling, lowered by any seasonal cap that touches the stay."""
    ceiling, source = p.auto_approve_max_discount_pct, "properties.csv: max_discount_auto_approve_pct"
    for cap in _rules().get("seasonal_discount_caps", []):
        if cap["property"] != p.code:
            continue
        hit = [n for n in nights if n.month in cap["months"] and DOW[n.weekday()] in cap["nights_of_week"]]
        if hit and cap["cap_pct"] < ceiling:
            ceiling = cap["cap_pct"]
            source = f"config/group_rules.yaml seasonal cap — \"{cap['source_note']}\""
    return ceiling, source


def _suggest_dates(p: Property, a: date, d: date) -> list[dict]:
    """Nearest same-length windows before/after the blackout that clash with it."""
    clash = _overlaps_blackout(p, a, d)
    if not clash:
        return []
    length = (d - a).days
    start, end = clash
    after_a = end + timedelta(days=1)
    before_d = start
    out = [{"arrival": (before_d - timedelta(days=length)).isoformat(), "departure": before_d.isoformat(), "note": "just before blackout"},
           {"arrival": after_a.isoformat(), "departure": (after_a + timedelta(days=length)).isoformat(), "note": "just after blackout"}]
    today = get_settings().today
    return [o for o in out if date.fromisoformat(o["arrival"]) > today]


def evaluate(store: DataStore, req: GroupRequest) -> Evaluation:
    today = get_settings().today
    p = store.property(req.property_code)
    if p is None:
        return Evaluation(req.property_code, "unknown", "NEEDS_CLARIFICATION",
                          missing_info=[f"Unknown property code '{req.property_code}'."])

    ev = Evaluation(p.code, p.name, "READY_TO_SEND")

    # ---- 1. Required information -------------------------------------------------
    if not req.arrival or not req.departure:
        ev.missing_info.append("Confirmed arrival and departure dates")
    elif req.departure <= req.arrival:
        ev.missing_info.append("Departure must be after arrival")
    elif req.arrival <= today:
        ev.missing_info.append(f"Arrival {req.arrival} is not in the future (today is {today})")
    if not req.rooms or req.rooms <= 0:
        ev.missing_info.append("Exact number of rooms (an estimate like 'around 25' can't be priced)")
    if not req.room_type or req.room_type not in p.rooms_by_type:
        ev.missing_info.append(f"Room type (one of: {', '.join(p.rooms_by_type)})")
    if ev.missing_info:
        ev.decision = "NEEDS_CLARIFICATION"
        return ev

    nights = _nights(req.arrival, req.departure)
    discount = req.requested_discount_pct or 0

    # ---- 2. Blackout dates (hard stop) ---------------------------------------------
    clash = _overlaps_blackout(p, req.arrival, req.departure)
    if clash:
        ev.checks.append(Check("blackout_dates", "block",
                               f"Stay overlaps blackout {clash[0]} to {clash[1]}. No group holds accepted.",
                               "properties.csv: blackout_dates"))
        ev.suggested_dates = _suggest_dates(p, req.arrival, req.departure)
    else:
        ev.checks.append(Check("blackout_dates", "pass", "No blackout overlap.", "properties.csv: blackout_dates"))

    # ---- 3. Block size vs. auto-approve limit ---------------------------------------
    if req.rooms > p.auto_approve_max_rooms:
        ev.checks.append(Check("block_size", "flag",
                               f"{req.rooms} rooms exceeds auto-approve limit of {p.auto_approve_max_rooms}. GM/Sales approval required.",
                               "properties.csv: group_block_auto_approve_max_rooms"))
    else:
        ev.checks.append(Check("block_size", "pass",
                               f"{req.rooms} rooms is within auto-approve limit of {p.auto_approve_max_rooms}.",
                               "properties.csv: group_block_auto_approve_max_rooms"))

    # ---- 4. Discount vs. ceiling (incl. seasonal caps) ------------------------------
    ceiling, ceiling_src = _ceiling_for(p, nights)
    if discount > ceiling:
        ev.checks.append(Check("discount", "flag",
                               f"Requested {discount}% exceeds the {ceiling}% auto-approve ceiling by {discount - ceiling} pts.",
                               ceiling_src))
    else:
        ev.checks.append(Check("discount", "pass", f"Requested {discount}% is within the {ceiling}% ceiling.", ceiling_src))

    # ---- 5. Room inventory (type capacity minus existing reservations) --------------
    type_total = p.rooms_by_type.get(req.room_type, 0)
    per_night = [{"night": n.isoformat(), "available": type_total - store.booked_rooms(p.code, req.room_type, n)} for n in nights]
    min_avail = min(x["available"] for x in per_night)
    ev.availability = {"room_type": req.room_type, "room_type_inventory": type_total,
                       "min_available_any_night": min_avail, "per_night": per_night,
                       "basis": "Inventory minus reservations in the sample export. Pending live PMS/CRS confirmation."}
    if req.rooms > min_avail:
        ev.checks.append(Check("inventory", "block",
                               f"Only {min_avail} {req.room_type} rooms available on the tightest night; {req.rooms} requested.",
                               "properties.csv room counts minus guest_profiles.csv reservations"))
    else:
        ev.checks.append(Check("inventory", "pass",
                               f"{min_avail} {req.room_type} rooms available on the tightest night.",
                               "properties.csv room counts minus guest_profiles.csv reservations"))

    # ---- 6. Meeting space ----------------------------------------------------------
    if req.meeting_capacity_needed:
        if req.meeting_capacity_needed > p.max_meeting_capacity:
            ev.checks.append(Check("meeting_capacity", "block",
                                   f"Needs {req.meeting_capacity_needed} people; max capacity is {p.max_meeting_capacity}.",
                                   "properties.csv: max_meeting_capacity"))
        else:
            ev.checks.append(Check("meeting_capacity", "pass",
                                   f"{req.meeting_capacity_needed} people fits (max {p.max_meeting_capacity}).",
                                   "properties.csv: max_meeting_capacity"))

    # ---- 7. Property-specific rules from notes --------------------------------------
    for rule in _rules().get("property_rules", []):
        if rule["property"] != p.code:
            continue
        src = f"properties.csv notes — \"{rule['source_note']}\""
        t = rule["type"]
        if t == "min_lead_time_days" and req.rooms > rule["applies_if_rooms_over"]:
            lead = (req.arrival - today).days
            if lead < rule["days"]:
                ev.checks.append(Check("lead_time", "flag", f"Only {lead} days lead time; {rule['days']}+ required for blocks over {rule['applies_if_rooms_over']} rooms.", src))
        elif t == "route_elsewhere" and req.rooms > rule["applies_if_rooms_over"]:
            ev.checks.append(Check("routing", "block", rule["message"], src))
        elif t == "required_followup" and any(k in req.event_type.lower() for k in rule["applies_if_event_type_contains"]):
            ev.required_followups.append(rule["message"])
            ev.checks.append(Check("required_followup", "info", rule["message"], src))
        elif t == "advisory":
            weekend = any(DOW[n.weekday()] in ("Fri", "Sat") for n in nights)
            months_hit = any(n.month in rule.get("applies_if_months", []) for n in nights)
            if (rule.get("applies_if_weekend_nights") and weekend) or months_hit:
                ev.checks.append(Check("advisory", "info", rule["message"], src))

    # ---- 8. Pricing ---------------------------------------------------------------
    base = p.base_rates.get(req.room_type)
    if base is None:
        ev.checks.append(Check("rate_data", "block",
                               f"No valid published rate for {req.room_type} at {p.code}. Will not quote; Sales to confirm rate.",
                               "properties.csv base rates (data quality issue)"))
    else:
        applied = min(discount, ceiling)
        n, r = len(nights), req.rooms
        rate_req = round(base * (1 - discount / 100), 2)
        rate_ceiling = round(base * (1 - applied / 100), 2)
        ev.pricing = {
            "room_type": req.room_type, "base_rate": base, "nights": n, "rooms": r, "room_nights": n * r,
            "requested_discount_pct": discount, "auto_approve_ceiling_pct": ceiling,
            "rate_at_requested_discount": rate_req, "total_at_requested_discount": round(rate_req * n * r, 2),
            "rate_within_rules": rate_ceiling, "discount_within_rules_pct": applied,
            "total_within_rules": round(rate_ceiling * n * r, 2),
            "budget_per_night": req.budget_per_night,
            "within_budget_at_rules_rate": (rate_ceiling <= req.budget_per_night) if req.budget_per_night else None,
            "note": "Room rate only, before tax. Published base rate; seasonal rate adjustments are applied by Sales.",
        }
        if req.budget_per_night and rate_ceiling > req.budget_per_night:
            ev.checks.append(Check("budget", "info",
                                   f"Rate within rules (${rate_ceiling}) is above stated budget (${req.budget_per_night}).",
                                   "inquiry: stated_budget_per_night"))

    # ---- Decision -----------------------------------------------------------------
    worst = max((SEVERITY[c.status] for c in ev.checks), default=0)
    ev.decision = {0: "READY_TO_SEND", 1: "NEEDS_HUMAN_APPROVAL", 2: "CANNOT_ACCOMMODATE"}[worst]
    return ev


PROXIMITY = ("same city", "same state", "other state")


def find_alternatives(store: DataStore, req: GroupRequest, exclude: str | None = None) -> list[dict]:
    """Evaluate the same request at every other property; best fits first.

    A group booked for Phoenix needs a hotel near Phoenix, so location comes before price: workable
    properties first (ready, then needs approval), and within those the same city, then the same state,
    then the rest; price breaks ties. Each result says how near it is so the agent can tell Sales.
    """
    rank = {"READY_TO_SEND": 0, "NEEDS_HUMAN_APPROVAL": 1, "CANNOT_ACCOMMODATE": 2, "NEEDS_CLARIFICATION": 3}
    home = store.properties.get((req.property_code or "").upper())
    results = []
    for code, p in store.properties.items():
        if exclude and code == exclude.upper():
            continue
        alt = GroupRequest(**{**req.__dict__, "property_code": code})
        ev = evaluate(store, alt)
        if home is None:
            near = None
        elif p.city.lower() == home.city.lower() and p.state == home.state:
            near = PROXIMITY[0]
        else:
            near = PROXIMITY[1] if p.state == home.state else PROXIMITY[2]
        results.append({
            "property_code": code, "property_name": ev.property_name, "city": f"{p.city}, {p.state}",
            "proximity": near, "decision": ev.decision,
            "issues": [c.detail for c in ev.checks if c.status in ("flag", "block")],
            "rate_within_rules": (ev.pricing or {}).get("rate_within_rules"),
        })
    results.sort(key=lambda x: (rank[x["decision"]] >= 2,
                                PROXIMITY.index(x["proximity"]) if x["proximity"] else 0,
                                rank[x["decision"]], x["rate_within_rules"] or 1e9))
    return results
