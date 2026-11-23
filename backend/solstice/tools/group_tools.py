"""Group sales tools. All pricing and approval decisions come from
solstice.rules.group_rules — the model never computes a rate or an approval.
"""
from __future__ import annotations

from datetime import date

from solstice.data.store import get_store, inquiry_view
from solstice.rules.group_rules import GroupRequest, evaluate, find_alternatives
from solstice import runtime_store
from solstice.tools.registry import ToolContext, ToolError, attach_data_warnings, tool

AGENTS = ("group_sales",)

BLOCK_PROPS = {
    "property_code": {"type": "string"},
    "arrival": {"type": "string", "description": "YYYY-MM-DD"},
    "departure": {"type": "string", "description": "YYYY-MM-DD"},
    "rooms": {"type": "integer"},
    "room_type": {"type": "string", "enum": ["Standard King", "Standard Double", "Deluxe King", "Suite", "Accessible King"]},
    "requested_discount_pct": {"type": "integer"},
    "budget_per_night": {"type": "integer"},
    "meeting_capacity_needed": {"type": "integer"},
    "event_type": {"type": "string"},
}
BLOCK_REQUIRED = ["property_code", "arrival", "departure", "rooms", "room_type"]
MAX_ALTERNATIVES = 8


def _req(**kw) -> GroupRequest:
    def d(v):
        try:
            return date.fromisoformat(v) if v else None
        except ValueError:
            raise ToolError(f"Date '{v}' is not YYYY-MM-DD.")
    return GroupRequest(kw["property_code"], d(kw.get("arrival")), d(kw.get("departure")), kw.get("rooms"),
                        kw.get("room_type"), kw.get("requested_discount_pct") or 0, kw.get("budget_per_night"),
                        kw.get("meeting_capacity_needed"), kw.get("event_type") or "")


@tool("list_group_inquiries", "List inbound group inquiries (id, company, property, dates, rooms).", {}, agents=AGENTS)
def list_group_inquiries(ctx: ToolContext) -> dict:
    return {"inquiries": [
        {k: v for k, v in inquiry_view(i).items()
         if k in ("inquiry_id", "company", "event_type", "preferred_property", "arrival", "departure", "rooms_requested")}
        for i in get_store().inquiries.values()]}


@tool("get_group_inquiry", "Full details of one group inquiry (contact details masked).",
      {"inquiry_id": {"type": "string"}}, ["inquiry_id"], agents=AGENTS)
def get_group_inquiry(ctx: ToolContext, inquiry_id: str) -> dict:
    i = get_store().inquiries.get(inquiry_id.upper().strip())
    if not i:
        raise ToolError(f"No inquiry '{inquiry_id}'.")
    return attach_data_warnings(ctx, inquiry_view(i), i.inquiry_id, i.preferred_property)


@tool("evaluate_group_block",
      "Run Solstice group rules for a block at one property: blackout dates, room limit, discount ceiling "
      "(incl. seasonal caps), inventory, meeting space, property-specific rules, and pricing. Returns a decision "
      "(READY_TO_SEND / NEEDS_HUMAN_APPROVAL / CANNOT_ACCOMMODATE / NEEDS_CLARIFICATION) with every check and its source.",
      BLOCK_PROPS, BLOCK_REQUIRED, agents=AGENTS)
def evaluate_group_block(ctx: ToolContext, **kw) -> dict:
    return attach_data_warnings(ctx, evaluate(get_store(), _req(**kw)).to_dict(), kw["property_code"].upper())


@tool("find_alternative_properties",
      "Evaluate the same block at every other Solstice property and return the best options: workable ones first, "
      "nearest first (same city, same state, other state), then by price. Use when the preferred property can't "
      "accommodate, or the client said alternates are OK.",
      BLOCK_PROPS, BLOCK_REQUIRED, agents=AGENTS)
def find_alternative_properties(ctx: ToolContext, **kw) -> dict:
    alts = find_alternatives(get_store(), _req(**kw), exclude=kw["property_code"])
    workable = [a for a in alts if a["decision"] in ("READY_TO_SEND", "NEEDS_HUMAN_APPROVAL")]
    near = {k: sum(a["proximity"] == k for a in workable) for k in ("same city", "same state", "other state")}
    # The whole portfolio is too much to hand the model (140 properties in production; 99 in the synthetic
    # data made replies hit the token cap). The best few are what Sales needs.
    return {"alternatives": alts[:MAX_ALTERNATIVES], "properties_checked": len(alts),
            "workable": len(workable), "workable_by_proximity": near}


@tool("create_group_proposal",
      "Save a structured proposal for Sales. The rules engine re-runs here, so the status is set by the rules, not "
      "by you: inside the rules it is a DRAFT ready to send; anything flagged goes to PENDING_HUMAN_APPROVAL.",
      {**BLOCK_PROPS, "inquiry_id": {"type": "string"},
       "cover_note": {"type": "string", "description": "Short client-facing summary of the offer"}},
      BLOCK_REQUIRED + ["inquiry_id", "cover_note"], agents=AGENTS)
def create_group_proposal(ctx: ToolContext, inquiry_id: str, cover_note: str, **kw) -> dict:
    ev = evaluate(get_store(), _req(**kw))
    if ev.decision in ("NEEDS_CLARIFICATION", "CANNOT_ACCOMMODATE"):
        raise ToolError(f"Cannot create a proposal: decision is {ev.decision}. Resolve or pick another property/dates.")
    status = "DRAFT_READY_TO_SEND" if ev.decision == "READY_TO_SEND" else "PENDING_HUMAN_APPROVAL"
    rec = runtime_store.append("proposals", {
        "proposal_id": runtime_store.new_id("PRO"), "inquiry_id": inquiry_id, "status": status,
        "approver": None if status.startswith("DRAFT") else "Sales + property GM",
        "cover_note": cover_note, "evaluation": ev.to_dict(), "session_id": ctx.session_id,
    })
    return {"proposal_id": rec["proposal_id"], "status": status,
            "flags_for_reviewer": [c.detail for c in ev.checks if c.status == "flag"],
            "required_followups": ev.required_followups}
