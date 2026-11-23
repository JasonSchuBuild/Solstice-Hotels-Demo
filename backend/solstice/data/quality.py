"""Data quality: find bad source data, handle it safely, and raise alerts.

Three layers:
  1. Load-time checks (run_checks): every row of every export is validated once.
  2. In-flight warnings (warnings_for): when a tool touches a record with a known
     issue, the tool result carries `data_quality_warnings` so the agent knows not
     to trust the affected field, and an alert is raised for the data owner.
  3. On-demand report (report): staff can ask "any data issues?" and get the list.

In production the alerts go to the data steward / PMS admin queue (and a metric
in Application Insights) instead of data/runtime/alerts.jsonl.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date

ERROR, WARNING, INFO = "error", "warning", "info"


@dataclass
class DataIssue:
    issue_id: str          # stable, e.g. DQ-properties-SOL-PVD-base_rate_suite
    severity: str          # error: field unusable | warning: suspicious | info: incomplete
    dataset: str           # properties | reservations | inquiries
    record_id: str         # property_code / reservation_id / inquiry_id
    field: str
    value: str
    problem: str
    agent_handling: str    # what the agent does about it
    property_code: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _date(v):
    try:
        return date.fromisoformat(str(v).strip())
    except (TypeError, ValueError):
        return None


class _Collector:
    def __init__(self):
        self.items: list[DataIssue] = []
        self.prop: str | None = None     # property the current row belongs to

    def add(self, sev, ds, rid, fld, val, problem, handling):
        self.items.append(DataIssue(f"DQ-{ds}-{rid}-{fld}", sev, ds, rid, fld, str(val), problem, handling, self.prop))


RATE_COLS = ["base_rate_standard", "base_rate_deluxe", "base_rate_suite"]
ROOM_COLS = ["standard_king_rooms", "standard_double_rooms", "deluxe_king_rooms", "suite_rooms", "accessible_rooms"]
KNOWN_STATUSES = {"Confirmed", "Checked-in", "Checked-out", "Cancelled", "No-show"}
KNOWN_ROOM_TYPES = {"Standard King", "Standard Double", "Deluxe King", "Suite", "Accessible King"}


def run_checks(properties: list[dict], reservations: list[dict], inquiries: list[dict]) -> list[DataIssue]:
    c = _Collector()
    prop_codes = {p["property_code"] for p in properties}

    # ---------- properties ----------
    for p in properties:
        pid = c.prop = p["property_code"]
        for col in RATE_COLS:
            v = _int(p[col])
            if v is None or v <= 0:
                c.add(ERROR, "properties", pid, col, p[col], "Rate is missing, non-numeric or not positive.",
                      "Rate is never quoted; group checks block pricing and route to Sales.")
        rooms = [_int(p[col]) or 0 for col in ROOM_COLS]
        total = _int(p["total_rooms"])
        if total is None or sum(rooms) != total:
            c.add(WARNING, "properties", pid, "total_rooms", p["total_rooms"],
                  f"Room types sum to {sum(rooms)} but total_rooms is {p['total_rooms']}.",
                  "Inventory checks use per-type counts.")
        for col in ("group_block_auto_approve_max_rooms", "max_discount_auto_approve_pct", "max_meeting_capacity"):
            if _int(p[col]) is None:
                c.add(ERROR, "properties", pid, col, p[col], "Threshold missing or non-numeric.",
                      "Treated as 0, so every group request is flagged for human review.")
        bo = (p.get("blackout_dates") or "").strip()
        if bo and bo.lower() != "none scheduled":
            for chunk in bo.split(";"):
                parts = chunk.split(" to ")
                if len(parts) != 2 or not all(_date(x) for x in parts):
                    c.add(ERROR, "properties", pid, "blackout_dates", chunk.strip(),
                          "Blackout range can't be parsed.",
                          "Blackout can't be enforced. Group requests at this property need human review.")

    # ---------- reservations ----------
    seen_res, guests = set(), defaultdict(set)
    for r in reservations:
        rid, c.prop = r["reservation_id"], r["property_code"]
        if rid in seen_res:
            c.add(ERROR, "reservations", rid, "reservation_id", rid, "Duplicate reservation id.",
                  "First record wins; escalate before acting on this reservation.")
        seen_res.add(rid)
        guests[r["guest_id"]].add((r["first_name"], r["last_name"], r["email"]))
        if r["property_code"] not in prop_codes:
            c.add(ERROR, "reservations", rid, "property_code", r["property_code"], "Unknown property.",
                  "Property facts unavailable; escalate.")
        ci, co = _date(r["check_in_date"]), _date(r["check_out_date"])
        if not ci or not co or co <= ci:
            c.add(ERROR, "reservations", rid, "check_out_date", f"{r['check_in_date']}→{r['check_out_date']}",
                  "Invalid stay dates.", "Date-window answers withheld; escalate.")
        elif _int(r["total_nights"]) != (co - ci).days:
            c.add(WARNING, "reservations", rid, "total_nights", r["total_nights"],
                  f"total_nights says {r['total_nights']} but dates span {(co - ci).days}.",
                  "Agent uses the dates and tells the guest the team will confirm.")
        if r["room_type"] not in KNOWN_ROOM_TYPES:
            c.add(WARNING, "reservations", rid, "room_type", r["room_type"], "Unrecognized room type.",
                  "Upgrade path unknown; escalate upgrade requests.")
        if r["reservation_status"] not in KNOWN_STATUSES:
            c.add(WARNING, "reservations", rid, "reservation_status", r["reservation_status"], "Unknown status.",
                  "Treated as not modifiable; escalate.")
        rate = _int(r["nightly_rate"])
        if rate is None or rate < 0 or (rate == 0 and r["rate_plan"] != "Loyalty Redemption"):
            c.add(WARNING, "reservations", rid, "nightly_rate", r["nightly_rate"],
                  f"Rate {r['nightly_rate']} doesn't fit rate plan '{r['rate_plan']}'.",
                  "Penalty amounts are not quoted; the team confirms.")
    c.prop = None
    for gid, variants in guests.items():
        if len(variants) > 1:
            c.add(WARNING, "reservations", gid, "guest_id", gid,
                  "Same guest_id with different name/email across reservations.",
                  "Verification is per reservation, never by guest_id alone.")

    # ---------- inquiries ----------
    for q in inquiries:
        qid, c.prop = q["inquiry_id"], q["preferred_property_code"]
        if q["preferred_property_code"] not in prop_codes:
            c.add(ERROR, "inquiries", qid, "preferred_property_code", q["preferred_property_code"], "Unknown property.",
                  "Agent asks Sales to confirm the property.")
        a, d = _date(q["arrival_date"]), _date(q["departure_date"])
        if not a or not d:
            c.add(INFO, "inquiries", qid, "arrival_date", f"{q['arrival_date']}→{q['departure_date']}",
                  "Dates missing.", "Agent drafts clarifying questions; no pricing.")
        elif _int(q["nights"]) is not None and _int(q["nights"]) != (d - a).days:
            c.add(WARNING, "inquiries", qid, "nights", q["nights"], f"nights says {q['nights']} but dates span {(d - a).days}.",
                  "Engine uses the dates; agent asks client to confirm.")
        if _int(q["rooms_requested"]) is None:
            c.add(INFO, "inquiries", qid, "rooms_requested", q["rooms_requested"], "Room count is not an exact number.",
                  "Agent asks for an exact count before pricing.")
        if not q["contact_phone"].strip():
            c.add(INFO, "inquiries", qid, "contact_phone", "", "No phone number.", "Follow up by email only.")
        rec = _date(q["date_received"])
        if a and rec and a < rec:
            c.add(WARNING, "inquiries", qid, "arrival_date", q["arrival_date"], "Arrival is before the inquiry was received.",
                  "Agent asks client to confirm dates.")
    return c.items


# ---------- in-flight use ----------

def warnings_for(issues: list[DataIssue], *record_ids: str) -> list[dict]:
    ids = {x for x in record_ids if x}
    return [{"field": i.field, "severity": i.severity, "problem": i.problem, "handling": i.agent_handling}
            for i in issues if i.record_id in ids and i.severity != INFO]


def raise_alerts(issues: list[DataIssue], record_ids: list[str], session_id: str, triggered_by: str) -> list[str]:
    """Log an alert for the data owner when the agent actually hits bad data. One per issue per session."""
    from solstice import runtime_store
    already = {(a["issue_id"], a["session_id"]) for a in runtime_store.read_all("alerts")}
    raised = []
    for i in issues:
        if i.record_id in record_ids and i.severity != INFO and (i.issue_id, session_id) not in already:
            runtime_store.append("alerts", {"issue_id": i.issue_id, "severity": i.severity, "dataset": i.dataset,
                                            "record_id": i.record_id, "field": i.field, "problem": i.problem,
                                            "triggered_by": triggered_by, "session_id": session_id})
            raised.append(i.issue_id)
    return raised


def report(issues: list[DataIssue], property_code: str | None = None) -> dict:
    pc = (property_code or "").upper().strip()
    sel = [i for i in issues if not pc or i.property_code == pc]
    by_sev = defaultdict(int)
    for i in sel:
        by_sev[i.severity] += 1
    order = {ERROR: 0, WARNING: 1, INFO: 2}
    return {"total": len(sel), "by_severity": dict(by_sev),
            "issues": [i.to_dict() for i in sorted(sel, key=lambda x: order[x.severity])]}
