# Group sales: incomplete inquiry

**Agent:** group_sales · **Mode:** staff · **Model:** claude-haiku-5-5 · **Demo date:** 2026-07-12

**What this shows:** Doesn't price a guess: lists the clarifying questions to send to the client.

---

**Staff:** INQ-2004.

<details><summary>Tools called: <code>get_group_inquiry</code></summary>

`get_group_inquiry` · ok · 0 ms

```json
{
  "input": {
    "inquiry_id": "INQ-2004"
  },
  "output": {
    "inquiry_id": "INQ-2004",
    "date_received": "2026-07-05",
    "company": "Meridian Wealth Partners",
    "contact_name": "J. Ostrander",
    "contact_email": "j***@meridianwp.com",
    "contact_phone": "not provided",
    "event_type": "Corporate Retreat",
    "preferred_property": "SOL-DEN",
    "alternate_property_ok": false,
    "arrival": null,
    "departure": null,
    "rooms_requested": "around 25",
    "room_type": null,
    "requested_discount_pct": null,
    "budget_per_night_usd": null,
    "meeting_space_needed": true,
    "meeting_capacity_needed": null,
    "special_requests": "Need AV for presentations"
  }
}
```

</details>

**Assistant:**

> I loaded INQ-2004 (Meridian Wealth Partners, Corporate Retreat, preferred property SOL-DEN). I can't run the rules check yet because the inquiry is missing several required details.
>
> **Still needed before I can check or price it:**
>
> 1. **Arrival and departure dates.** Both are blank. Blackout dates and lead time depend on these.
> 2. **Exact room count.** The inquiry says "around 25." I need a firm number of rooms.
> 3. **Room type.** Standard King, Standard Double, Deluxe King, Suite, or Accessible King? Some may be mixed, but I'd need the split.
> 4. **Requested discount percentage.** Blank on the inquiry.
> 5. **Budget per night (USD).** Blank on the inquiry.
> 6. **Meeting space capacity.** The inquiry confirms meeting space is needed and asks for AV, but not how many people will be in the room. Please confirm the headcount for the largest session.
> 7. **Contact phone.** Listed as "not provided." Worth getting for the proposal follow-up.
>
> Once the client confirms the dates, exact room count, and room type, I'll run the SOL-DEN rules check and, if it can't accommodate, look at alternatives. Since the client has said alternates are not OK, any alternative would need Sales to confirm with them first.

<sub>3.99s · 466 in / 692 out tokens</sub>
