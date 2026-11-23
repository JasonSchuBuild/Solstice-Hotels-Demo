"""Eval cases built from the synthetic 10x data's labels (data/synthetic/labels/).

Each case asks the group sales agent to work up one synthetic inquiry and grades the result against the
decision the generator designed, so the agent is tested on 100 inquiries it has never seen, not just the
10 sample ones the prompts were tuned on.

What a case checks (all by code, as in cases.yaml):
  - the agent ran the rules engine at the inquiry's property and got the designed decision. A wrong
    room count, room type, dates or discount passed to the tool shows up here.
  - the flags the scenario must raise (block size, discount, blackout, meeting space, inventory).
  - priceable cases: a proposal was saved with the status the rules give (draft, or pending approval).
    The proposal tool re-runs the engine on the agent's inputs, so this checks the whole workflow.
  - over the discount ceiling: a proposal saved (at the ceiling as a draft, or pending approval) and the
    requested discount named in the reply for Sales.
  - can't accommodate: the reply says so, and no proposal at another property if the client said no to one.
  - incomplete inquiries: no proposal, and the reply asks for what's missing.
  - inquiries with a seeded data fault the agent must catch (unknown property, arrival before the
    inquiry was received): no proposal.
"""
from __future__ import annotations

import csv
from collections import defaultdict

from solstice.config import REPO_ROOT

DATA_DIR = "data/synthetic"
GAP_WORDS = {
    "rooms": ["how many rooms", "number of rooms", "room count", "exact"],
    "dates": ["date", "arrival", "check-in"],
    "room_type": ["room type", "type of room", "king", "double"],
}
CANT_WORDS = ["can't", "cannot", "can not", "unable", "not able", "isn't available", "not available", "won't work"]
PROPOSAL_STATUS = {"READY_TO_SEND": "DRAFT_READY_TO_SEND", "NEEDS_HUMAN_APPROVAL": "PENDING_HUMAN_APPROVAL"}
FAULTS_TO_TEST = {"faulted:unknown_property", "faulted:arrival_before_received"}


def _read(name: str) -> list[dict]:
    with open(REPO_ROOT / DATA_DIR / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _gap(inq: dict) -> str:
    if not inq["arrival_date"]:
        return "dates"
    if not inq["rooms_requested"].strip().isdigit():
        return "rooms"
    return "room_type"


def build_cases(limit: int = 0) -> list[dict]:
    """All labeled inquiries, or `limit` of them spread evenly across scenarios (first ids of each, so the
    same limit always gives the same cases)."""
    inquiries = {q["inquiry_id"]: q for q in _read("group_inquiries.csv")}
    by_scenario = defaultdict(list)
    for lab in _read("labels/inquiry_scenarios.csv"):
        if lab["scenario"].startswith("faulted:") and lab["scenario"] not in FAULTS_TO_TEST:
            continue
        by_scenario[lab["scenario"]].append(lab)

    chosen = []
    if limit:
        queues = [sorted(v, key=lambda x: x["inquiry_id"]) for _, v in sorted(by_scenario.items())]
        while len(chosen) < limit and any(queues):
            for q in queues:
                if q and len(chosen) < limit:
                    chosen.append(q.pop(0))
    else:
        chosen = [lab for v in by_scenario.values() for lab in v]

    cases = []
    for lab in sorted(chosen, key=lambda x: x["inquiry_id"]):
        qid, scen, decision = lab["inquiry_id"], lab["scenario"], lab["expected_decision"]
        expect: dict = {"tools_called": ["get_group_inquiry"]}
        if scen.startswith("faulted:"):
            expect["no_proposal"] = True
        elif decision == "NEEDS_CLARIFICATION":
            expect.update(no_proposal=True, reply_contains_any=GAP_WORDS[_gap(inquiries[qid])])
        else:
            q = inquiries[qid]
            expect["group_decision"] = decision
            flags = [f for f in lab["expected_flags"].split(";") if f]
            if flags:
                expect["group_flags_include"] = flags
            if scen == "over_discount":
                # Designed behavior (as in INQ-2009): price at the ceiling, which is within the rules, and
                # flag the extra points for Sales; or save the full request as pending approval. Either way the
                # reply must name the discount the client asked for.
                expect["tool_output"] = [{"tool": "create_group_proposal", "field": "status",
                                          "in": list(PROPOSAL_STATUS.values())}]
                expect["reply_contains_any"] = [f"{q['requested_discount_pct']}%"]
            elif decision in PROPOSAL_STATUS:
                expect["tool_output"] = [{"tool": "create_group_proposal", "field": "status",
                                          "equals": PROPOSAL_STATUS[decision]}]
            else:
                # The tool already refuses a proposal at the requested property and dates. What's left to the
                # agent: say so plainly, and respect a client who said no to other properties. A proposal at
                # other dates or (when allowed) another property is a legitimate alternative for Sales.
                expect["reply_contains_any"] = CANT_WORDS
                if q["alternate_property_ok"] != "Y":
                    expect["proposal_property_in"] = [q["preferred_property_code"]]
        cases.append({"id": f"syn-{qid}", "tags": [f"syn:{scen.replace('faulted:', 'fault:')}", "synthetic"],
                      "agent": "group_sales", "mode": "staff", "turns": [f"Work up {qid}."], "expect": expect})
    return cases
