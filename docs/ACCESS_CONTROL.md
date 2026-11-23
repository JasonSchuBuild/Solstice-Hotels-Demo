# Access Control: Demo Gate vs. Production

How the demo separates guests from staff, and what changes before real use.

## What the demo does

- The terminal app opens with a mode menu: **Guest**, **Front desk staff**, **Group sales**, **Admin**.
- Staff modes ask for the staff PIN (`access.staff_pin`, default `1234`); Admin asks for a separate admin PIN (`access.admin_pin`, default `4321`). Both live in `config/settings.yaml`; `SOLSTICE_STAFF_PIN` / `SOLSTICE_ADMIN_PIN` in `.env` override them. Input is hidden, 3 attempts, then exit. Neither PIN opens the other role.
- **Admin console** (`backend/solstice/admin.py`): read-only view of agent settings, group rules, health checks (API key set, models reachable, data loads, prompts and policy present, runtime folder writable), tools per mode, activity (latency vs. target, tokens, escalations, failed PINs and verifications) and data quality issues. It never calls the model for text and never prints secrets, only whether they are set and where from. Changes are made by editing the YAML/markdown files. The exceptions are two admin-only switches, both saved to Azure Blob Storage when deployed (`backend/solstice/settings_store.py`) and logged to the audit trail: the website theme (Appearance tab, `themes.py`) and **demo open access** (Access tab, `open_access.py`). Demo open access lets staff and admin sign in with a blank PIN so a live demo can run with or without PINs, with no deploy or restart. It is off by default, off if storage can't be read, and the master switch `access.allow_open_access` in `config/settings.yaml` (set it to false for any deployment that should never offer it) disables it entirely. A wrong PIN still fails, and the browser's `?demo=on` switch has no effect on it. While it is on, anyone with the site address has staff and admin access.
- **Web app:** the same PINs gate `/staff` and `/admin`, checked on the server. After 5 wrong PINs from one address, that address is locked out for 5 minutes. Staff sessions don't survive a page reload, and sessions expire after 30 idle minutes.
- **The PINs are a demo convenience, not security.** It stops a guest at a shared demo screen from wandering into staff tools. Anyone with access to the files can read the PIN or call the code directly.

## What is already enforced in code (and stays in production)

These do not depend on the PIN and hold in every mode:

| Control | Where |
|---|---|
| Mode is fixed for the session; tools are filtered by mode **in code**, so chat text ("I'm staff") cannot unlock staff tools | `backend/solstice/tools/registry.py` → `tools_for`; `tests/test_cli_access.py` |
| Guests must verify (confirmation number + last name) before any reservation detail is shared | `tools/concierge_tools.py` → `verify_guest` |
| Guest PII is masked; payment data never leaves the data store, even for staff | `data/masking.py`, `data/store.py`; `tests/test_masking.py` |
| Pricing and approval status come from the rules engine, not the model | `rules/group_rules.py`; `tests/test_group_rules.py` |
| Guest verification locks after 3 failed attempts per chat (`access.max_failed_verifications`); the agent must hand off to staff | `tools/concierge_tools.py` → `verify_guest`; `tests/test_cli_access.py` |
| Audit log of every tool call (session, agent, mode, tool, record IDs), staff PIN attempts and failed verifications, with no names or free text | `data/runtime/audit.jsonl`; `agent/runner.py`, `cli.py` |

## Cost and abuse guardrails (in place)

Thresholds live in `config/settings.yaml` (`limits`, `agent.max_history_turns`); code in `backend/solstice/web/limits.py`; tests in `tests/test_web_api.py`.

| Layer | Default | What happens |
|---|---|---|
| Message length | guest 1,000 chars, staff 4,000 | Rejected with a friendly message (also capped in the page) |
| Messages per chat | 30 | "Please start a new conversation" |
| Messages per client address | 20 per 10 minutes | "You're sending messages quickly"; a new chat doesn't reset it |
| New chats per client address | 400 per hour (raised from 20 for demos and testing; set it back to 20 before public use) | Blocks scripted session churn |
| Daily token budget | 2,000,000 tokens (UTC day) | Guests get "limit reached, the front desk can help" with **no model call**; staff keep working |
| Conversation history sent to the model | last 12 user messages | Long chats don't get more expensive every turn; verification is kept |
| Reply size / tool rounds / turn time | 8,192 tokens / 8 rounds / 45 s (90 s group sales) | Existing caps; past the round or time cap, the agent hands off to staff with a ticket |
| Prompt rules | `config/prompts/shared_guardrails.md` §8–9 | Off-topic requests declined; "ignore your instructions", prompt extraction and fake authority ("I'm the GM") refused |

Every limit hit is written to the audit log (kind only, never the client address) and shown on the admin Activity tab with today's token use vs. budget.

Known limits of the demo version: counters are in memory per instance (reset on restart); the daily budget counts uncached input + output tokens, so prompt-cache reads (billed at ~10%) aren't included. **The hard spending cap is at the provider:** use a demo-only Anthropic API key in its own workspace with a monthly spend limit.

## Hardening for real use

**1. Replace the PIN with real identity**
- Staff sign in through the hotel's identity provider (e.g., Microsoft Entra ID) with SSO and MFA. No shared PINs or passwords.
- Guests authenticate through the existing guest channel (app login, loyalty account, or a one-time code sent to the email/phone on the reservation) instead of typing a confirmation number into an open chat.

**2. Role-based access, decided server-side**
- Map directory groups to roles: `guest`, `front_desk`, `front_desk_manager` (comp authority above $50), `group_sales`, `data_owner`, `platform_admin`.
- Admin becomes a separate web console behind SSO + MFA for the `platform_admin` group only. Settings changes go through source control and deployment (reviewed, versioned, reversible), not live edits; health and activity come from monitoring (e.g., Application Insights) instead of local log files.
- The backend derives the role from the verified token on every request and builds the tool list from it. The client never sends "mode=staff".
- Scope staff by property: a Denver associate sees Denver reservations only.

**3. Sessions**
- Short-lived tokens, idle timeout for staff sessions on shared front-desk terminals, re-authentication for sensitive actions (comps above authority, refunds).

**4. Secrets**
- API keys and connection strings in a managed secret store (e.g., Azure Key Vault) accessed by managed identity. No `.env` files on servers. *(Done in the Azure demo: the key is only in Key Vault, read by the app's managed identity. The demo key is in its own Anthropic workspace with a monthly spend limit.)*
- Next step: **workload identity federation** with the Anthropic API. The app exchanges its Azure managed-identity token for short-lived Anthropic tokens, so no static model key exists anywhere. Needs a federation rule and service account in the Anthropic Console, the SDK's federation settings on the container, and token refresh in the app. (Or use Claude in Foundry with Entra ID auth, which also removes the key.)
- Rotate keys; separate keys per environment (dev / staging / prod).

**5. Least-privilege data access**
- The agent's service identity gets read-only access to the PMS/CRS/loyalty views it needs, with PII masked at the source where possible.
- Write actions (service requests, proposals, escalations) go through the systems' own APIs with their own permission checks, not direct database writes.

**6. Audit and monitoring** *(demo version in place: `audit.jsonl` + verification lockout)*
- Log who (named user + role, not just a session), what tool, which record, and when, for every tool call, to a tamper-evident store (e.g., Log Analytics / SIEM). Keep transcripts per the retention policy, with PII masked.
- Alert on unusual patterns: repeated failed verifications, a staff account querying many guests, attempts to request staff-only actions from guest mode.
- Rate-limit guest verification across sessions and IP/device (the demo limits per chat session only, so starting a new chat resets it).

**6b. Abuse and cost controls at scale**
- Rate limiting at the edge (Azure Front Door WAF rate-limit rules or API Management policies), not in the app, with counters in a shared store (e.g., Azure Cache for Redis) so limits hold across replicas.
- Bot protection on the guest page (Front Door WAF bot rules) and per-guest limits after verification.
- Spend caps per environment at the provider, plus Azure budgets and alerts on the subscription.

**7. Prompt-injection resilience**
- Keep authority decisions in code, not the prompt: tool availability by role, rules-engine approvals, masking before data reaches the model.
- Treat text in guest messages, emails and inquiry notes as data. Out-of-policy actions always route to a human.

**8. Before go-live**
- Security review and penetration test of the guest-facing channel.
- Privacy review of what the model sees and what is logged (PCI scope stays out: no card data reaches the agent).

## Demo talking point

"The PIN is a stand-in for SSO. The parts that protect guests, like tool access by role, masking and rules-based approvals, are already enforced in code and don't change. Going to production swaps the front door, not the walls."
