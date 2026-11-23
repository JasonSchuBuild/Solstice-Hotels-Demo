# Cancelling a non-refundable rate

**Agent:** concierge · **Mode:** guest · **Model:** claude-haiku-5-5 · **Demo date:** 2026-07-12

**What this shows:** A kind but firm 'no' grounded in the cancellation terms tool, plus what the guest can do instead.

---

**Guest:** James Okoye, R55002. My flight got cancelled. Can I cancel my reservation and get my money back?

<details><summary>Tools called: <code>verify_guest</code>, <code>check_cancellation_terms</code></summary>

`verify_guest` · ok · 0 ms

```json
{
  "input": {
    "reservation_id": "R55002",
    "last_name": "Okoye"
  },
  "output": {
    "verified": true,
    "reservations": [
      {
        "reservation_id": "R55002",
        "guest_name": "James Okoye",
        "property_code": "SOL-CLT",
        "check_in": "2026-07-15",
        "check_out": "2026-07-16",
        "nights": 1,
        "room_type": "Standard Double",
        "rate_plan": "Advance Purchase",
        "nightly_rate_usd": 169,
        "status": "Confirmed",
        "loyalty_tier": "None",
        "loyalty_points": 0,
        "special_requests": "",
        "card_on_file": true,
        "internal_notes_for_staff_handling": ""
      }
    ]
  }
}
```

`check_cancellation_terms` · ok · 0 ms

```json
{
  "input": {
    "reservation_id": "R55002"
  },
  "output": {
    "policy": "3",
    "cancellable": false,
    "penalty": "Non-refundable, non-changeable",
    "reason": "Advance Purchase is non-refundable and non-changeable, including for weather, flights or illness. Front desk cannot waive this. Travel insurance is the guest's recourse."
  }
}
```

</details>

**Assistant:**

> Thank you, James. I've verified your reservation R55002 at our Charlotte property (SOL-CLT) for check-in on July 15, 2026.
>
> I'm sorry about your cancelled flight. Unfortunately, your booking is an Advance Purchase rate, which is non-refundable and non-changeable under our Advance Purchase policy. That applies to flight cancellations as well, and I'm not able to waive it. Your reservation can't be cancelled for a refund.
>
> If you bought travel insurance, your policy may cover the cost of the room, so it's worth checking with your provider. I can also help with anything else on this stay, such as a service request for the property team to confirm.

<sub>3.17s · 1165 in / 432 out tokens</sub>
