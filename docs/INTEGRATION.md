# Integration recommendation

How the agents plug into Solstice's property management system (PMS), central reservation system (CRS) and loyalty/CRM, what we'd tell a cautious IT team, and an honest answer to "is AI coming for our jobs?". Architecture: `docs/ARCHITECTURE.md`. Security detail: `docs/ACCESS_CONTROL.md`.

## How it plugs in

**One integration layer, not point-to-point connections.** The agent never talks to the PMS, CRS or loyalty system directly. It calls a small set of tools, and each tool calls one API published through Azure API Management. API Management handles authentication, throttling, logging and versioning in one place, and it's where IT can switch any integration off. If Solstice changes PMS vendor, only the API behind the tool changes; the agent, prompts and rules don't.

**Read first, write later, and only what's needed.** The agent's tools today map directly onto real system calls:

| Agent tool | System | Phase 1 (read) | Phase 2 (limited writes) |
|---|---|---|---|
| `verify_guest`, `lookup_reservation`, `check_cancellation_terms` | PMS | Reservation, dates, rate plan, status | n/a |
| `request_late_checkout`, `submit_service_request` | PMS | Late checkout availability | Create a request or task for the property (never change a folio) |
| `get_property_info`, `evaluate_group_block`, `find_alternative_properties` | CRS | Rates, inventory, blackout dates | n/a |
| `create_group_proposal` | CRS / sales system | n/a | Save a proposal as **pending**; group block holds are created by Sales after approval |
| loyalty tier and points | Loyalty / CRM | Tier, points, member since | Goodwill points only after manager approval |
| `escalate_to_staff` | Service desk / Microsoft Teams | n/a | Create a ticket with the masked transcript |

**Data stays where it is.** The agent reads live through the APIs instead of copying guest data into a new database. Card numbers are never returned by the APIs at all; names and contact details are masked before they reach the model. Each call is logged with who asked, which record and why.

**Phasing**

1. **Pilot (6–8 weeks), 2–3 properties, read-only.** Guest concierge for policy questions and reservation lookups; group sales assistant for internal use only. Every escalation and every proposal is still reviewed by a person. Measure: share of questions resolved without staff, escalation quality, latency, cost per conversation.
2. **Limited writes.** Service requests and late checkouts created in the PMS; proposals saved to the sales system as pending. Writes are idempotent (a retried request can't create a duplicate) and every one is attributed to the agent.
3. **Scale out** property by property, with a rollback switch per property and per tool.

## Advice for a nervous IT team

- **You control the blast radius.** The agent can only do what its tools allow, and the tools are code, not prompts. A guest can't talk it into a refund because there is no refund tool. Approvals and pricing are decided by the rules engine, not the model.
- **Start read-only and small.** Phase 1 changes nothing in your systems of record. If the pilot misbehaves, you turn the API off in API Management and the agent hands everything to staff.
- **No new place where guest data lives.** Data is read through your APIs at the moment it's needed; cards never leave the PMS; logs and tickets are masked.
- **It's your Microsoft stack.** Hosting on Azure Container Apps, sign-in with Entra ID (SSO + MFA), secrets in Key Vault with managed identities, monitoring in Application Insights, the model in Microsoft Foundry on your Azure bill. No new vendor console to secure.
- **You can see everything.** Every turn is traced: the question, each tool called, the data touched (by ID), the answer, latency and cost. Budgets and rate limits stop runaway costs.
- **Changes go through your normal release process.** Prompts, rules and thresholds are versioned files; changes are tested, reviewed and deployed like any other code, and can be rolled back.
- **It fails safe.** If the model or a hotel system is down, the guest is told plainly and a staff ticket is created with the conversation. Nothing is guessed.

## "Is AI coming for our jobs?"

An honest answer for the front desk team:

**No. It takes the repetitive questions so you can do the work only people can do.** A large share of front desk questions repeat every day: checkout time, pet policy, "can I get a late checkout?", "what's my reservation?". The agent answers those instantly, any time of day. That's time back for the guest in front of you, the upset traveler, the VIP arrival, and the judgment calls.

**It can't make the decisions that matter, by design.** Refunds, comps above $50, disputes, anything medical, legal or safety-related, and every out-of-policy group deal go to a person. When the agent hands over, the ticket arrives with the full conversation, so you start informed instead of starting over.

**It makes your job easier, not smaller.** Front desk staff get a fast assistant for lookups and policy checks. Sales gets proposals worked up in minutes instead of days, and spends the time saved on selling. Managers get escalations with context instead of "a guest called".

**What changes:** fewer repetitive calls, more time with guests, and new work in reviewing escalations, approving proposals, and helping improve the answers. We'd measure success by guest satisfaction and staff workload, and involve front desk teams in the pilot to shape what the agent does and doesn't handle.
