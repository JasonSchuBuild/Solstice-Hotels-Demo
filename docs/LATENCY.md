# Latency targets

Targets live in `config/settings.yaml` → `latency`. Every turn is timed and compared with its target; the admin **Activity** tab shows the result, and the staff console flags any reply that runs over.

| Who's waiting | Target (p95, complete reply) | Measured (2026-11-18, Haiku 5.5, local) |
|---|---|---|
| **Guests and front desk** (live chat) | **6 seconds** | median 2.1 s, p95 3.3 s (41 turns) |
| **Group sales** (back-office) | **20 seconds** | median 3.5 s, p95 10.5 s (8 turns) |

The eval suite (`docs/EVALS.md`) deliberately includes the heaviest turns: verify, check a policy and escalate, all in one reply. On those, concierge's slowest turn per case had a p95 of 6.8–8.0 s, just over the target (7.5 s on the 2026-11-20 re-run, with 7 of 81 runs over 6 s, all of them escalations). Group sales stayed inside its target (p95 14.6–16.5 s; 15.2 s on 2026-11-20).

p95 means 95 out of 100 replies arrive within the target. We set targets on p95, not the average, because the slow replies are the ones guests remember.

## Why 6 seconds for guests

The production constraint is **the alternative the guest has**. A guest asking "can I get a late checkout?" can also pick up the phone and call the front desk. The agent is only worth using if it's quicker and less effort than that call, which means:

- **It has to feel like a conversation.** Most answers need one or two tool calls (verify the guest, check the policy) plus the model's reply. On Haiku that's 2–4 seconds. Six seconds leaves headroom for the slower turns (verification plus a request plus an escalation) without the guest wondering whether it's broken.
- **The front desk uses the same agent with a guest in front of them.** An associate can fill a few seconds of conversation; much more than that and they'll stop using the tool and look it up themselves.
- **Anything longer gets a typing indicator, and anything failing falls back fast.** Model calls time out after 30 seconds with one retry (`model.request_timeout_s`, `max_retries`), and a whole turn stops at 45 seconds (`agent.turn_deadline_s`); either way the guest gets "I've passed this to the front desk" and a ticket is created. A slow model never leaves a guest waiting indefinitely.

## Why 20 seconds for group sales

Group sales is back-office work. Today, turning an inquiry into a priced, rule-checked proposal takes a salesperson hours to days: checking blackout dates, room limits, discount ceilings and meeting space across properties. The agent does that in one turn, but it calls more tools (load the inquiry, run the rules, check alternative properties, save a proposal) and writes a longer report. Twenty seconds is still orders of magnitude faster than the manual process, and nobody is standing at a desk waiting.

## What drives latency, and the levers we use

| Driver | Lever | Status |
|---|---|---|
| Model speed | Claude Haiku 5.5 by default (fastest current model); Sonnet/Opus only if quality needs it | In place, swappable in config |
| Re-sending the same long system prompt and policy every turn | Prompt caching | In place |
| Tool rounds per answer | Tools return everything needed in one call (e.g., verification returns all the guest's reservations); cap of 8 rounds | In place |
| Long conversations getting slower and costlier | Only the last 12 user messages are sent | In place |
| Cold start after scaling to zero | Warm windows (cron) keep one replica up during demo hours; an HTTP scale rule plus a 30-minute cooldown keep it up while anyone is chatting; data, prompts, model client and storage token are warmed at startup; always-on in production | In place |
| A slow or stuck turn leaving the user waiting | Whole-turn budget (`agent.turn_deadline_s`: 45 s live chat, 90 s group sales), then a staff handoff with a ticket; the browser waits 150 s, so the server always answers first | In place |
| One failed or overlapping turn breaking the rest of the chat | Failed turns roll back the model history; a second message while one is running gets "still working" instead of interleaving | In place |
| Opening a new HTTPS connection per chat | One shared model client for the app, so connections stay warm | In place |
| Waiting for the whole reply before showing anything | **Stream the reply** so the first words appear in about a second | Not built yet (next step) |

## How we'll know in production

Application Insights records latency per turn, per agent and per tool. Azure Monitor alerts when p95 exceeds the target for 15 minutes, and the fallback rate (model failures handed to staff) is tracked alongside, because a fast system that often fails isn't meeting the goal.
