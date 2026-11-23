# Sample transcripts

Real conversations with the Solstice agents, generated 2026-11-18 on `claude-haiku-5-5` with the real tools and sample data (demo date 2026-07-12). Guest names and reservations are from the provided sample data; payment data is masked by the tools before the model ever sees it.

Regenerate: `cd backend; .\.venv\Scripts\python.exe ..\docs\transcripts\generate_transcripts.py`. Replies vary a little between runs; the tool calls and rules outcomes don't.

| # | Transcript | Agent / mode | What it shows | Turns | Time | Tokens |
|---|---|---|---|---|---|---|
| 1 | [Late checkout for a Platinum guest](01-late-checkout-platinum.md) | concierge / guest | Verification, then a late checkout confirmed automatically because the rules engine sees Platinum. | 1 | 5.0s | 2,221 |
| 2 | [Late checkout and a rollaway for a Silver guest](02-requests-silver.md) | concierge / guest | Requests are submitted, not promised: the agent says the property will confirm. | 2 | 5.8s | 4,192 |
| 3 | [Cancelling a non-refundable rate](03-advance-purchase-cancel.md) | concierge / guest | A kind but firm 'no' grounded in the cancellation terms tool, plus what the guest can do instead. | 1 | 3.2s | 1,597 |
| 4 | [Noise complaint outside the service-recovery window](04-complaint-outside-window.md) | concierge / guest | Policy window checked by code, goodwill offered, and a warm handoff to a manager with full context. | 2 | 10.5s | 7,558 |
| 5 | [Guest reports an injury (not verified)](05-injury-unverified.md) | concierge / guest | Safety first: 911 guidance and an immediate escalation, without making verification a condition. | 1 | 4.5s | 1,685 |
| 6 | [Guardrails: prompt extraction, card data, off-topic](06-guardrails.md) | concierge / guest | Refuses to reveal instructions, never exposes payment data, declines off-topic work, stays helpful. | 3 | 4.2s | 1,302 |
| 7 | [Front desk: lookups and comp authority](07-front-desk-staff.md) | concierge / staff | Staff-only tools: search by last name (two guests share a name), masked lookup, and the $50 comp limit. | 3 | 8.5s | 7,852 |
| 8 | [Group sales: pricing with one flag](08-group-inq-2009.md) | group_sales / staff | Prices the block at the allowed 15% ceiling, flags the client's extra 2 points for Sales, and the proposal status is set by code, not the model. | 1 | 9.3s | 6,662 |
| 9 | [Group sales: blackout and alternatives](09-group-inq-2003.md) | group_sales / staff | Blackout dates are a hard stop; the agent proposes other dates and properties instead of a dead end. | 1 | 11.8s | 7,652 |
| 10 | [Group sales: incomplete inquiry](10-group-inq-2004.md) | group_sales / staff | Doesn't price a guess: lists the clarifying questions to send to the client. | 1 | 4.0s | 1,158 |
| 11 | [Bad source data: invalid rate](11-bad-data.md) | group_sales / staff | Data quality check catches an invalid rate in the source CSV, refuses to quote it, and alerts the data owner. | 2 | 10.8s | 12,033 |
| 12 | [Model outage: graceful degradation](12-model-outage.md) | concierge / guest | No dead end when the model is down: guest message plus a staff ticket with the transcript. | 1 | 0s | 0 |
