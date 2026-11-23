# Group sales: blackout and alternatives

**Agent:** group_sales · **Mode:** staff · **Model:** claude-haiku-5-5 · **Demo date:** 2026-07-12

**What this shows:** Blackout dates are a hard stop; the agent proposes other dates and properties instead of a dead end.

---

**Staff:** What can we do for INQ-2003?

<details><summary>Tools called: <code>get_group_inquiry</code>, <code>evaluate_group_block</code>, <code>find_alternative_properties</code></summary>

`get_group_inquiry` · ok · 0 ms

```json
{
  "input": {
    "inquiry_id": "INQ-2003"
  },
  "output": {
    "inquiry_id": "INQ-2003",
    "date_received": "2026-07-03",
    "company": "Longhorn Analytics Summit",
    "contact_name": "Priya Vance",
    "contact_email": "p***@longhornsummit.com",
    "contact_phone": "***-***-2277",
    "event_type": "Conference",
    "preferred_property": "SOL-AUS",
    "alternate_property_ok": false,
    "arrival": "2027-03-14",
    "departure": "2027-03-17",
    "rooms_requested": 30,
    "room_type": "Standard King",
    "requested_discount_pct": 12,
    "budget_per_night_usd": 210,
    "meeting_space_needed": true,
    "meeting_capacity_needed": 250,
    "special_requests": "Need full ballroom for keynote sessions"
  }
}
```

`evaluate_group_block` · ok · 0 ms

```json
{
  "input": {
    "property_code": "SOL-AUS",
    "arrival": "2027-03-14",
    "departure": "2027-03-17",
    "rooms": 30,
    "room_type": "Standard King",
    "event_type": "Conference",
    "meeting_capacity_needed": 250,
    "requested_discount_pct": 12,
    "budget_per_night": 210
  },
  "output": {
    "property_code": "SOL-AUS",
    "property_name": "Solstice Austin Congress Ave",
    "decision": "CANNOT_ACCOMMODATE",
    "checks": [
      {
        "rule": "blackout_dates",
        "status": "block",
        "detail": "Stay overlaps blackout 2027-03-10 to 2027-03-19. No group holds accepted.",
        "source": "properties.csv: blackout_dates"
      },
      {
        "rule": "block_size",
        "status": "pass",
        "detail": "30 rooms is within auto-approve limit of 30.",
        "source": "properties.csv: group_block_auto_approve_max_rooms"
      },
      {
        "rule": "discount",
        "status": "pass",
        "detail": "Requested 12% is within the 15% ceiling.",
        "source": "properties.csv: max_discount_auto_approve_pct"
      },
      {
        "rule": "inventory",
        "status": "pass",
        "detail": "70 Standard King rooms available on the
  … (truncated)
```

`find_alternative_properties` · ok · 0 ms

```json
{
  "input": {
    "property_code": "SOL-AUS",
    "arrival": "2027-03-14",
    "departure": "2027-03-17",
    "rooms": 30,
    "room_type": "Standard King",
    "event_type": "Conference",
    "meeting_capacity_needed": 250,
    "requested_discount_pct": 12,
    "budget_per_night": 210
  },
  "output": {
    "alternatives": [
      {
        "property_code": "SOL-PHX",
        "property_name": "Solstice Phoenix Camelback",
        "decision": "READY_TO_SEND",
        "issues": [],
        "rate_within_rules": 148.72
      },
      {
        "property_code": "SOL-TPA",
        "property_name": "Solstice Tampa Bayshore",
        "decision": "READY_TO_SEND",
        "issues": [],
        "rate_within_rules": 157.52
      },
      {
        "property_code": "SOL-CHI",
        "property_name": "Solstice Chicago Riverwalk",
        "decision": "NEEDS_HUMAN_APPROVAL",
        "issues": [
          "30 rooms exceeds auto-approve limit of 25. GM/Sales approval required."
        ],
        "rate_within_rules": 192.72
      },
      {
        "property_code": "SOL-PVD",
        "property_name": "Solstice Providence Waterplace",
        "decision": "CANNOT_ACCOMMODATE",
        "issues": [
 
  … (truncated)
```

</details>

**Assistant:**

> **Decision:** Solstice Austin (SOL-AUS) can't accommodate INQ-2003 as requested. No proposal has been created. The client said alternates are not OK, so Sales needs to confirm with Priya Vance before any alternative is proposed.
>
> **Why Austin is out**
> - **Blackout:** The stay (Mar 14–17, 2027) overlaps the Austin blackout of Mar 10–19, 2027, and no group holds are accepted in that window.
> - **Meeting space:** The keynote needs 250 people, but Austin's maximum capacity is 220.
> - **Passing checks:** 30 rooms is within the auto-approve limit, the 12% discount is within the 15% ceiling, and 70 Standard King rooms are available on each night (pending live PMS confirmation).
>
> **Options if the client will consider other dates or properties** (rates are room-only, pre-tax, from the tool; I haven't calculated totals)
>
> | Property | Status | Rate/night | Notes |
> |---|---|---|---|
> | SOL-PHX Phoenix Camelback | Ready to send | $148.72 | No issues flagged |
> | SOL-TPA Tampa Bayshore | Ready to send | $157.52 | No issues flagged |
> | SOL-CHI Chicago Riverwalk | Needs human approval | $192.72 | 30 rooms exceeds the 25-room auto-approve limit |
>
> The other properties fail on capacity (under 250 seats) and/or discount and room-count ceilings. Providence can't handle the 250 capacity either, and it's routed to a Boston-area sister property that isn't in our directory.
>
> **Austin alternate dates:** The tool suggests Mar 7–10, 2027 (just before the blackout) or Mar 20–23, 2027 (just after). I haven't checked Austin's rate or meeting space for those dates. I can run that if the client is open to moving.
>
> **Flags for human review**
> - Austin: blackout (Mar 10–19) and meeting capacity (220 max vs. 250 needed). Both are hard blocks.
> - Chicago: 30 rooms needs GM/Sales approval.
> - Austin's $199 base rate is a published figure. The tool notes seasonal adjustments are applied by Sales, so confirm the March 2027 rate before quoting.
>
> **Suggested next steps**
> 1. Ask Priya whether the 250-person keynote must be in Austin, and whether the Mar 14–17 dates are fixed.
> 2. If she's open to Phoenix or Tampa, I can save a proposal for that property. It would be a draft ready to send, and Sales would still confirm it.
> 3. If she isn't, Sales should let her know Austin can't host these dates or capacity.
>
> **Suggested reply to client (for Sales to send after review):**
> "Thank you for considering Solstice for the Longhorn Analytics Summit. Unfortunately, our Austin property is unavailable for March 14–17, 2027 because of a blackout period, and it can't seat 250 for the keynote. We have options in Phoenix and Tampa that can accommodate your room block and meeting space, and we can also look at alternate Austin dates. Could we set up a short call this week to talk through what works best for your group?"

<sub>11.84s · 5230 in / 2422 out tokens</sub>
