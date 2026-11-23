# Front desk: lookups and comp authority

**Agent:** concierge · **Mode:** staff · **Model:** claude-haiku-5-5 · **Demo date:** 2026-07-12

**What this shows:** Staff-only tools: search by last name (two guests share a name), masked lookup, and the $50 comp limit.

---

**Staff:** Find guests named Smith.

<details><summary>Tools called: <code>search_guests</code></summary>

`search_guests` · ok · 0 ms

```json
{
  "input": {
    "last_name": "Smith"
  },
  "output": {
    "matches": [
      {
        "reservation_id": "R55009",
        "guest_name": "Michael Smith",
        "property_code": "SOL-SAC",
        "check_in": "2026-07-25",
        "check_out": "2026-07-26",
        "nights": 1,
        "room_type": "Standard King",
        "rate_plan": "Advance Purchase",
        "nightly_rate_usd": 179,
        "status": "Confirmed",
        "loyalty_tier": "None",
        "loyalty_points": 0,
        "special_requests": "",
        "card_on_file": true,
        "guest_id": "G10009",
        "email": "m***@example.com",
        "phone": "***-***-0108",
        "member_since": "",
        "internal_notes_for_staff_handling": ""
      },
      {
        "reservation_id": "R55010",
        "guest_name": "Michael Smith",
        "property_code": "SOL-CHI",
        "check_in": "2026-07-25",
        "check_out": "2026-07-28",
        "nights": 3,
        "room_type": "Deluxe King",
        "rate_plan": "Corporate Negotiated",
        "nightly_rate_usd": 259,
        "status": "Confirmed",
        "loyalty_tier": "Gold",
        "loyalty_points": 14200,
        "special_requests": "",
        "card
  … (truncated)
```

</details>

**Assistant:**

> I found two reservations under the last name Smith. Both are named Michael Smith, so please confirm by confirmation number:
>
> 1. **R55009**: Michael Smith, Solstice Sacramento (SOL-SAC)
>    - Check-in July 25, 2026, check-out July 26 (1 night)
>    - Standard King, Advance Purchase, $179/night
>    - Status: Confirmed, card on file, no loyalty membership
>
> 2. **R55010**: Michael Smith, Solstice Chicago (SOL-CHI)
>    - Check-in July 25, 2026, check-out July 28 (3 nights)
>    - Deluxe King, Corporate Negotiated, $259/night
>    - Status: Confirmed, card on file, Gold member since 2018 (14,200 points)
>
> These are two different guests with the same name. Which one do you need to work on?

<sub>2.3s · 713 in / 334 out tokens</sub>

**Staff:** Pull up R55010.

<details><summary>Tools called: <code>lookup_reservation</code></summary>

`lookup_reservation` · ok · 0 ms

```json
{
  "input": {
    "reservation_id": "R55010"
  },
  "output": {
    "reservation_id": "R55010",
    "guest_name": "Michael Smith",
    "property_code": "SOL-CHI",
    "check_in": "2026-07-25",
    "check_out": "2026-07-28",
    "nights": 3,
    "room_type": "Deluxe King",
    "rate_plan": "Corporate Negotiated",
    "nightly_rate_usd": 259,
    "status": "Confirmed",
    "loyalty_tier": "Gold",
    "loyalty_points": 14200,
    "special_requests": "",
    "card_on_file": true,
    "guest_id": "G10010",
    "email": "m***@example.com",
    "phone": "***-***-0199",
    "member_since": "2018",
    "internal_notes_for_staff_handling": "Do not confuse with guest G10009 (unrelated, same name)."
  }
}
```

</details>

**Assistant:**

> Here are the details for R55010:
>
> - **Guest:** Michael Smith (Gold member since 2018, 14,200 points)
> - **Property:** Solstice Chicago (SOL-CHI)
> - **Dates:** Check-in July 25, 2026, check-out July 28 (3 nights)
> - **Room:** Deluxe King, Corporate Negotiated rate, $259/night
> - **Status:** Confirmed
> - **Payment:** Card on file
> - **Special requests:** None on file
>
> Is there anything you need for this reservation, such as a comp check, a service request, or a cancellation terms check?

<sub>1.91s · 2163 in / 258 out tokens</sub>

**Staff:** Can I give him a $40 F&B credit plus a $25 parking comp for the noise issue?

<details><summary>Tools called: <code>check_comp_authority</code>, <code>check_service_recovery_eligibility</code></summary>

`check_comp_authority` · ok · 0 ms

```json
{
  "input": {
    "amounts_usd": [
      40,
      25
    ],
    "includes_full_night": false
  },
  "output": {
    "policy": "7",
    "total_usd": 65,
    "front_desk_can_approve": false,
    "approver": "AGM or GM sign-off required"
  }
}
```

`check_service_recovery_eligibility` · ok · 0 ms

```json
{
  "input": {
    "reservation_id": "R55010",
    "reported_during_stay": false
  },
  "output": {
    "policy": "5",
    "window_closes": "2026-07-31T11:00",
    "reported_during_stay": false,
    "eligible_for_refund_credit_or_comp": true,
    "if_not_eligible": null,
    "approval_needed": "Comp/refund amounts follow Policy 7 authority limits."
  }
}
```

</details>

**Assistant:**

> The $65 total is over front-desk authority. Under Policy 7, front desk can comp up to $50 per stay, so this needs AGM or GM sign-off.
>
> The service recovery check also raises a question. R55010 is for a stay that hasn't happened yet (check-in July 25, 2026), so I can't see a noise issue on this reservation. The system shows the complaint as not reported during the stay, with a window closing July 31, 2026 at 11:00. Before you go further, please confirm whether the noise issue happened on a different stay, or whether the guest is reporting something from an earlier visit.
>
> If the complaint is valid, I can send it to the AGM or GM with the details. Would you like me to do that?

<sub>4.3s · 3589 in / 795 out tokens</sub>
