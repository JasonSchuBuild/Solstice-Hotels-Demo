# Model outage: graceful degradation

**Agent:** concierge · **Mode:** guest · **Model:** unavailable (simulated)

**What this shows:** when the model can't be reached, the guest isn't left hanging: they get a clear message and a reference, and staff get a ticket with the conversation attached.

---

**Guest:** Hi, I need to change the dates on my reservation for next week.

**Assistant:**

> I'm sorry, I can't answer right now because our assistant is temporarily unavailable. I've passed your message to the front desk team (reference ESC-82E339), and they'll follow up with you. For anything urgent, please call the front desk directly.

**Ticket created for staff:**

```json
{
  "ticket_id": "ESC-82E339",
  "priority": "SAME_DAY",
  "route_to": "Manager on duty / AGM (same day)",
  "category": "other",
  "summary": "The assistant was unavailable, so this conversation was handed to staff automatically.",
  "recommended_next_step": "Read the transcript and follow up with the guest.",
  "transcript": [
    {
      "role": "user",
      "text": "Hi, I need to change the dates on my reservation for next week."
    }
  ]
}
```
