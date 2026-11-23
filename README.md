# Solstice Hotel Group — Concierge & Group Sales Agent

An agentic proof of concept for Solstice Hotel Group (140 upper-midscale properties):

- **Concierge agent**: answers guest questions, handles routine requests (late checkout, service and amenity requests, loyalty status), and escalates with full context when something is outside its authority.
- **Group sales agent**: turns an inbound group inquiry into a priced, rule-checked proposal in minutes, and flags anything outside the rules for a human.

Built on Claude (default: `claude-haiku-5-5`) with a hand-written tool-calling loop. Pricing, approvals and policy date math are **deterministic Python**, not model output.

## Repo map — where to look

| I want to… | Go to |
|---|---|
| Change agent behavior or wording | `config/prompts/*.md` |
| Change the model, demo date, latency target | `config/settings.yaml` |
| Change a group rule (seasonal cap, routing, lead time) | `config/group_rules.yaml` |
| See the source data and policy | `data/raw/`, `data/policies/` |
| See how pricing and approvals are decided | `backend/solstice/rules/group_rules.py` |
| See policy date math (cancellation, service recovery, comps) | `backend/solstice/rules/guest_policies.py` |
| See what the agent can do | `backend/solstice/tools/` |
| See the agent loop | `backend/solstice/agent/runner.py` |
| See data quality checks and alerts | `backend/solstice/data/quality.py`, `docs/DATA_NOTES.md` |
| See the evals plan | `docs/EVALS.md` |
| Generate or load the synthetic 10x data | `python -m solstice.data.synthetic`, `data/synthetic/`, set `SOLSTICE_DATA_DIR=data/synthetic` (`docs/DATA_NOTES.md`) |
| See guest vs. staff access (demo PIN, production hardening) | `docs/ACCESS_CONTROL.md`, `backend/solstice/cli.py` |
| See the admin console (settings, health, activity) | `backend/solstice/admin.py` |
| Integration plan, IT advice, "will AI take our jobs?" | `docs/INTEGRATION.md` |
| Latency targets and why | `docs/LATENCY.md` |
| The net-new tool and why the agent needs it | `docs/NET_NEW_TOOL.md` |
| Every tool, its parameters and who can use it | `docs/TOOLS.md` (generated) |
| Read sample conversations | `docs/transcripts/` (regenerate with `generate_transcripts.py`) |
| Deploy to Azure (Bicep, runbook) | `infra/main.bicep`, `infra/README.md`, `Dockerfile` |
| See or change the web pages | `backend/solstice/web/static/` (HTML/CSS/JS, no build step) |
| See the web API (sessions, chat, admin) | `backend/solstice/web/app.py`, `backend/solstice/web/sessions.py` |
| See PII masking | `backend/solstice/data/masking.py`, `backend/solstice/data/store.py` |
| See tickets, requests, proposals the agent created | `data/runtime/*.jsonl` (generated) |
| See the audit log (tool calls, PIN attempts, failed verifications) | `data/runtime/audit.jsonl` (generated) |

## Run it locally (Windows / PowerShell)

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# one time: add your key
copy ..\.env.example ..\.env    # then edit ..\.env

python -m pytest                       # offline tests, no API calls

# web app (guest chat, staff console, admin dashboard)
python -m uvicorn solstice.web.app:app --port 8000
#   http://localhost:8000          guest concierge
#   http://localhost:8000/staff    front desk + group sales (staff PIN 1234)
#   http://localhost:8000/admin    settings, health, activity (admin PIN 4321)

# terminal app
python -m solstice.cli                 # menu: guest / front desk / group sales / admin
                                       # demo PINs: staff 1234, admin 4321 (not real security)
python -m solstice.cli admin           # admin console: settings, health, tools, activity, data quality
python -m solstice.cli concierge       # chat as a guest
python -m solstice.cli concierge --staff
python -m solstice.cli group_sales
python -m solstice.cli concierge --model claude-sonnet-5-5   # compare models
```

## Try these

**Concierge (guest):**
- "What time is checkout?" (no verification needed)
- "I'm Michael Chen, confirmation R55004. Can I get a late checkout?" (Platinum: confirmed 2 PM)
- "This is Robert Kalinski, R55012. It was really noisy, I want a refund." (outside the window: goodwill points + escalation)
- "James Okoye, R55002. My flight got cancelled, can I cancel?" (Advance Purchase: non-refundable)
- "Can I bring my dog?" / "I'm traveling with a service animal."

**Group sales:**
- "Work up INQ-2009." (prices it, flags only the discount)
- "What can we do for INQ-2003?" (blackout plus ballroom too small: alternatives and dates)
- "INQ-2004." (clarifying questions, no price)
- "Price 5 suites at Providence for Sept 1-3." (invalid rate in data: won't quote, raises an alert)
- "Any data issues?" (staff/sales: data quality report)
