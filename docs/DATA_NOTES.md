# Data Notes — what we found in the sample exports and how the agent handles it

Real hotel data is messy. These are the issues found in the provided exports and the design decision taken for each. Every item here is covered by a test in `backend/tests/`.

## How bad data is caught and surfaced (`backend/solstice/data/quality.py`)

1. **At load:** every row of every export is validated: invalid or negative rates, room counts that don't add up, unparseable blackout dates, impossible stay dates, nights that don't match dates, unknown properties, room types or statuses, duplicate IDs, incomplete inquiries. Each issue gets a severity (error / warning / info) and a note on how the agent handles it.
2. **While the agent works:** when a tool touches a record with a known issue, the result carries `data_quality_warnings`. The prompt tells the agent not to use that field and to say it needs confirmation. At the same time an **alert** is logged for the data owner (`data/runtime/alerts.jsonl`, once per issue per session).
3. **On request:** staff can ask "any data issues?" or "anything wrong with Providence's data?". The `get_data_quality_report` tool lists issues and recent alerts. The CLI shows the issue count when a staff session starts.

The sample data is fairly clean, so the test suite also **injects one fault of each kind** into a copy of the data and confirms every one is caught (`test_data_quality.py`).

## Synthetic 10x data (`data/synthetic/`)

A seeded script, not an LLM, generates about 10x the sample data with the same columns: 100 properties, 253 reservations and 100 group inquiries. A script was chosen so the numbers stay consistent (room types sum to the total, rates fit the rate plan, nights match the dates) and the labels are exact.

```powershell
cd backend
.\.venv\Scripts\python.exe -m solstice.data.synthetic             # 10x, seed 7; --scale 14 gives ~140 properties
$env:SOLSTICE_DATA_DIR = "data/synthetic"                         # the app, CLI or evals now load it
Remove-Item Env:SOLSTICE_DATA_DIR                                 # back to the sample data
```

- **Labeled:** `labels/expected_issues.csv` lists every issue the quality checks should find: 27 seeded faults covering all 17 fault kinds (e.g. negative rate, unparseable blackout, duplicate reservation id, arrival before the inquiry was received), plus 7 incomplete inquiries. `labels/inquiry_scenarios.csv` gives each inquiry's designed scenario (within rules, over the block limit, over the discount ceiling, blackout, meeting too big, not enough rooms, needs clarification), its expected decision and the flags it must raise. Each inquiry's `notes` column says the same in words, like the sample's answer key.
- **Fictional people:** names from short lists, emails at example.com, phones in the 555-01xx range, random card last-4s. IDs are marked synthetic: `SYN-###`, `G9####`, `R9####`, `INQ-9###`.
- **Tested** (`backend/tests/test_synthetic.py`): the quality checks find exactly the labeled issues, with no false alarms on the clean rows; the rules engine reaches the designed decision for all 95 unfaulted inquiries; the same seed gives identical files; and the checked-in copy matches a fresh run, so the labels can't go stale if the demo date changes.

## Data quality issues

| Finding | Where | How it's handled |
|---|---|---|
| SOL-PVD suite base rate is **-395** | `properties.csv` | Treated as missing. The agent never quotes a suite rate for Providence and routes to Sales instead. |
| `Accessible King` appears on a reservation but has no rate column | `guest_profiles.csv` / `properties.csv` | **Assumption:** priced at the standard rate. Inventory comes from `accessible_rooms`. |
| Guest `G10004` has two reservations | `guest_profiles.csv` | Expected (repeat guest). Verification returns both of the guest's reservations. |
| Two unrelated guests named **Michael Smith** | `G10009`, `G10010` | Guests verify with confirmation number + last name, never name alone. The staff name search warns about duplicates. |
| Guest names that match GM names (Marcus Webb, Owen Fitzgerald, Renee Okafor-Bailey) | both files | Identity always comes from the reservation, never from a name match. |
| No live availability, parking, or amenity data | n/a | The agent says so instead of guessing (Policy 12). Requests go to the property as *pending*. Group inventory = room-type count minus booked reservations, labeled "pending PMS confirmation". |
| Sample dates are mid-2026 | all | The demo date is pinned to **2026-07-12** in `config/settings.yaml`, so date windows give stable answers. |

## Internal notes that conflict with written policy

| Reservation | Note says | Policy says | Agent behavior |
|---|---|---|---|
| R55004 (Platinum) | Suite upgrade "NOT guaranteed" | Policy 6: Platinum gets a *guaranteed* upgrade to the next room class (Deluxe → Suite), based on same-day inventory | Follows policy. Because this is a policy conflict, it escalates with `policy_gap_or_conflict` and doesn't promise either way. |
| R55020 | Best Available Rate allows same-day cancel of remaining nights before 6 PM | Not in the written policy | Treated as unverified. The agent doesn't promise it and escalates to the manager. |

Rule in the prompt: **written policy wins over notes; conflicts get escalated.**

## Group inquiries: the `notes` column

The inquiry export includes a `notes` column that reads like an analyst's expected outcome. It is **hidden from the agent** (so the agent reasons from the rules, not the answer) and used as the **answer key in the test suite**.

The rules engine matches every expected outcome, and catches four issues the notes missed:

| Inquiry | Missed by the notes |
|---|---|
| INQ-2010 | Dates 2027-05-04 → 05-06 are inside SOL-SAC's **blackout** (2027-05-03 → 05-07), not just the seasonal discount cap. |
| INQ-2003 | Besides the SXSW blackout, the 250-person keynote exceeds SOL-AUS's **220 max meeting capacity**. |
| INQ-2005 | 22 rooms also exceeds SOL-SAC's **20-room** auto-approve limit. |
| INQ-2008 | 28 rooms exceeds SOL-CMH's 20-room limit, and the 12% discount exceeds its 10% ceiling, in addition to the insurance follow-up. |

## Rules that only existed as free text

Property notes such as "ski-season weekends cap at 8%" were turned into structured, cited rules in `config/group_rules.yaml`. Assumptions made while doing that:

- **SOL-SAC "weekdays":** a stay night falling Mon–Fri.
- **SOL-DEN "Thu–Sun":** a stay night falling Thu–Sun in Dec–Feb.
- **SOL-PVD over 15 rooms:** the Boston sister property isn't in the directory, so the request is a hard stop with a handoff to Sales.
- **SOL-PHX summer rates (~20% lower):** shown as an advisory note only. Quotes use the published base rate, because "~20%" isn't a rate the agent can quote.
