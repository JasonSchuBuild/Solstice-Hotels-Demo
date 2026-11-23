# Net-new tool: data quality checks and alerts

**What it is:** a tool the brief didn't hand over. It checks every row of the source data, warns the agent mid-conversation when a record it's using is bad, alerts the data owner, and lets staff ask "any data issues?".

**Code:** `backend/solstice/data/quality.py` (checks and alerts), `backend/solstice/tools/data_quality_tools.py` (`get_data_quality_report`), `backend/solstice/tools/registry.py` (`attach_data_warnings`). **Tests:** `backend/tests/test_data_quality.py`. **Details of each finding:** `docs/DATA_NOTES.md`.

## Why the agent needs it

The brief's first guardrail is "never invent a policy, rate or availability". An agent can follow that rule perfectly and still quote a wrong number if the **source data** is wrong. The model has no way to know that a rate in a CSV is a typo; it just reads the value it's given.

The sample data proves the risk is real:

| What we found | What would have happened without the tool |
|---|---|
| Providence suite base rate is **-$395** | A group quote with a negative rate, or the model "fixing" it to $395, which is an invented rate |
| INQ-2004 has no arrival date and "around 25" rooms | A proposal priced on guessed dates and room count |
| Four outcomes the analyst's notes missed (blackout, meeting capacity, room limits) | Proposals that look approved but break the rules |

At 140 properties, fed by several systems, errors like these are guaranteed. A hotel's data team usually finds them weeks later, if at all. The agent touches the data hundreds of times a day, so it's the best-placed thing to notice.

## How it works

1. **At load:** every row is validated (invalid or negative rates, impossible dates, room counts that don't add up, unknown properties or room types, duplicate IDs, incomplete inquiries). Each issue gets a severity and a note on how the agent should handle it.
2. **During a conversation:** when a tool touches a record with a known issue, its result includes `data_quality_warnings`. The guardrails tell the agent not to use that field and to say it needs confirmation. Guests hear "the team will confirm that"; staff hear exactly what's wrong.
3. **Alert:** at the same moment, an alert is logged for the data owner, once per issue per session, so the fix happens at the source.
4. **On request:** staff ask "any data issues?" and get the full list, including how often each issue was hit.

## See it

- Transcript: [`docs/transcripts/11-bad-data.md`](transcripts/11-bad-data.md). The agent refuses to quote the Providence suite rate, offers properties whose rates are valid, and lists the open issues.
- Admin page → **Data quality** tab: every issue with its severity and handling.
- Admin page → **Health**: data quality shows as a warning while an error is open.

## Production version

Alerts go to the data owner's queue (Teams channel or service desk ticket) instead of a log file. Checks run on every data refresh from the PMS/CRS, and the issue count becomes a data-health metric on the operations dashboard.
