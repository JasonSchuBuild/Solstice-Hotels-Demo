"""Escalation = a warm handoff, not a dead end.

The model writes the summary; the code attaches everything else (verified
reservation, masked transcript, routing per Policy 15) so the human picking it up
never has to ask the guest to start over.
"""
from __future__ import annotations

from solstice.data.masking import scrub_free_text
from solstice.data.store import get_store, reservation_view
from solstice import runtime_store
from solstice.tools.registry import ToolContext, tool

CATEGORIES = ["refund_or_comp_over_authority", "billing_dispute", "outside_policy_window", "safety_or_security",
              "medical", "legal", "media_inquiry", "vip_arrival", "policy_gap_or_conflict", "guest_upset", "other"]

# Policy 15 routing. Policy 15 names safety, threats and law enforcement as "any hour, no exceptions".
# It doesn't name medical; we treat it as urgent too, since the route below says "immediately".
URGENT = {"safety_or_security", "medical"}
ROUTE = {
    "safety_or_security": "General Manager + Regional Security (immediately, any hour)",
    "medical": "Manager on duty (immediately). If there is an emergency, call 911 first.",
    "legal": "General Manager (same day)",
}
DEFAULT_ROUTE = "Manager on duty / AGM (same day)"


@tool("escalate_to_staff",
      "Hand the conversation to a human with full context. Use for anything outside the agent's authority: "
      "refunds/comps over limits, disputes, anything medical, legal or safety-related, media, policy gaps or "
      "conflicts, or an upset guest. The transcript and reservation are attached automatically.",
      {"category": {"type": "string", "enum": CATEGORIES},
       "summary": {"type": "string", "description": "2-4 sentences: what happened and what the guest wants"},
       "what_agent_already_did": {"type": "string"},
       "recommended_next_step": {"type": "string"},
       "policy_refs": {"type": "array", "items": {"type": "string"}, "description": "e.g. ['Policy 5', 'Policy 7']"},
       "reservation_id": {"type": "string", "description": "If known"}},
      ["category", "summary", "recommended_next_step"],
      agents=("concierge", "group_sales"))
def escalate_to_staff(ctx: ToolContext, category: str, summary: str, recommended_next_step: str,
                      what_agent_already_did: str = "", policy_refs: list[str] | None = None,
                      reservation_id: str | None = None) -> dict:
    res = get_store().reservation(reservation_id) if reservation_id else None
    if res and ctx.mode == "guest" and res.guest_id != ctx.verified_guest_id:
        res = None   # never attach someone else's reservation
    ticket = runtime_store.append("tickets", {
        "ticket_id": runtime_store.new_id("ESC"),
        "status": "OPEN",
        "priority": "URGENT" if category in URGENT else "SAME_DAY",
        "route_to": ROUTE.get(category, DEFAULT_ROUTE),
        "category": category,
        "summary": summary,
        "what_agent_already_did": what_agent_already_did,
        "recommended_next_step": recommended_next_step,
        "policy_refs": policy_refs or [],
        "property_code": res.property_code if res else None,
        "reservation": reservation_view(res, "staff") if res else None,
        "guest_verified": bool(ctx.verified_guest_id),
        "transcript": [{"role": m["role"], "text": scrub_free_text(m["text"])} for m in ctx.transcript],
        "source": f"{ctx.agent}/{ctx.mode}", "session_id": ctx.session_id,
    })
    return {"ticket_id": ticket["ticket_id"], "priority": ticket["priority"], "routed_to": ticket["route_to"],
            "message": "Ticket created with full conversation context. Tell the guest who will follow up and when."}
