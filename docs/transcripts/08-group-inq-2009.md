# Group sales: pricing with one flag

**Agent:** group_sales · **Mode:** staff · **Model:** claude-haiku-5-5 · **Demo date:** 2026-07-12

**What this shows:** Prices the block at the allowed 15% ceiling, flags the client's extra 2 points for Sales, and the proposal status is set by code, not the model.

---

**Staff:** Work up INQ-2009.

<details><summary>Tools called: <code>get_group_inquiry</code>, <code>evaluate_group_block</code>, <code>create_group_proposal</code></summary>

`get_group_inquiry` · ok · 0 ms

```json
{
  "input": {
    "inquiry_id": "INQ-2009"
  },
  "output": {
    "inquiry_id": "INQ-2009",
    "date_received": "2026-07-11",
    "company": "Camelback Fitness Retreat",
    "contact_name": "Alicia Storm",
    "contact_email": "a***@camelbackfitness.com",
    "contact_phone": "***-***-2211",
    "event_type": "Corporate Retreat",
    "preferred_property": "SOL-PHX",
    "alternate_property_ok": false,
    "arrival": "2026-07-28",
    "departure": "2026-07-31",
    "rooms_requested": 15,
    "room_type": "Deluxe King",
    "requested_discount_pct": 17,
    "budget_per_night_usd": 175,
    "meeting_space_needed": true,
    "meeting_capacity_needed": 40,
    "special_requests": "Morning yoga sessions need a quiet room, not the main ballroom"
  }
}
```

`evaluate_group_block` · ok · 3 ms

```json
{
  "input": {
    "property_code": "SOL-PHX",
    "arrival": "2026-07-28",
    "departure": "2026-07-31",
    "rooms": 15,
    "room_type": "Deluxe King",
    "event_type": "Corporate Retreat",
    "meeting_capacity_needed": 40,
    "requested_discount_pct": 17,
    "budget_per_night": 175
  },
  "output": {
    "property_code": "SOL-PHX",
    "property_name": "Solstice Phoenix Camelback",
    "decision": "NEEDS_HUMAN_APPROVAL",
    "checks": [
      {
        "rule": "blackout_dates",
        "status": "pass",
        "detail": "No blackout overlap.",
        "source": "properties.csv: blackout_dates"
      },
      {
        "rule": "block_size",
        "status": "pass",
        "detail": "15 rooms is within auto-approve limit of 35.",
        "source": "properties.csv: group_block_auto_approve_max_rooms"
      },
      {
        "rule": "discount",
        "status": "flag",
        "detail": "Requested 17% exceeds the 15% auto-approve ceiling by 2 pts.",
        "source": "properties.csv: max_discount_auto_approve_pct"
      },
      {
        "rule": "inventory",
        "status": "pass",
        "detail": "45 Deluxe King rooms available on the tightest night.",
        "sour
  … (truncated)
```

`create_group_proposal` · ok · 0 ms

```json
{
  "input": {
    "property_code": "SOL-PHX",
    "arrival": "2026-07-28",
    "departure": "2026-07-31",
    "rooms": 15,
    "room_type": "Deluxe King",
    "inquiry_id": "INQ-2009",
    "event_type": "Corporate Retreat",
    "meeting_capacity_needed": 40,
    "requested_discount_pct": 15,
    "budget_per_night": 175,
    "cover_note": "Thank you for considering Solstice Phoenix Camelback for your corporate retreat. We can offer 15 Deluxe King rooms for July 28\u201331, 2026 (3 nights) at a 15% group discount, which brings the room rate to $177.65 per night before tax. We have meeting space for your group of 40, and we can look at a quieter room for the morning yoga sessions rather than the main ballroom. Our team will confirm final pricing and the seasonal rate with you."
  },
  "output": {
    "proposal_id": "PRO-CC2040",
    "status": "DRAFT_READY_TO_SEND",
    "flags_for_reviewer": [],
    "required_followups": []
  }
}
```

</details>

**Assistant:**

> **Decision:** Within rules at 15% off. Proposal **PRO-CC2040** saved as **DRAFT_READY_TO_SEND**. The 17% the client asked for still needs Sales approval if they want it.
>
> **Offer (SOL-PHX, Solstice Phoenix Camelback)**
> - Dates: July 28–31, 2026 (3 nights)
> - Rooms: 15 Deluxe King × 3 nights = 45 room-nights
> - Rate: $177.65/night at 15% off the $209 base
> - Total: $7,994.25 room only, pre-tax
> - Meeting space: 40 capacity fits (property max 350)
> - Availability: 45 Deluxe King rooms open each night (pending live PMS confirmation)
>
> **Flags for human review**
> - **Discount gap:** The client asked for 17%. Auto-approve ceiling is 15%, so the proposal is priced at 15%. At 17% the rate would be $173.47 and the total $7,806.15, but that needs Sales/GM approval (discount rule, `max_discount_auto_approve_pct`).
> - **Budget:** The client's stated budget is $175/night. The in-rules rate of $177.65 is about $2.65 above it. The rate at 17% ($173.47) would be under budget, which may be why they asked for it.
> - **Seasonal rate:** The property notes say June–August rates run about 20% lower. The tool quotes the published base rate and says Sales may apply the seasonal rate. I haven't calculated that; Sales should confirm the seasonal price before it goes out.
>
> **Required follow-ups**
> - Sales to decide whether to approve 17% or hold at 15%, and to confirm the seasonal rate.
> - Property to confirm a quiet room for the morning yoga sessions. The tool did not check this; it is a request, not a confirmed room.
>
> **Suggested reply to client:**
> "Thank you for considering Solstice Phoenix Camelback for your retreat. We can offer 15 Deluxe King rooms for July 28–31, 2026, at $177.65 per night before tax, which includes a 15% group discount. We have meeting space for your group of 40, and we've noted your request for a quieter room for morning yoga. Our sales team will confirm final pricing with you shortly."

<sub>9.32s · 4666 in / 1996 out tokens</sub>
