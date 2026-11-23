"""The synthetic eval cases, checked offline before spending a token on them.

A scripted agent that does the job right (load the inquiry, run the rules on its real values, save a
proposal when the rules allow one, ask for what's missing) must pass every case, and a do-nothing agent
must fail every case. That proves the cases and the labels agree, and that the grader can tell the difference.
"""
import csv

import pytest

from solstice.agent.runner import AgentSession
from solstice.config import REPO_ROOT
from solstice.data import store as store_mod
from solstice.evals.checks import run_checks
from solstice.evals.synthetic_cases import PROPOSAL_STATUS, build_cases
from tests.test_agent_loop import FakeClient, _text, _tool

LABELS = REPO_ROOT / "data" / "synthetic" / "labels" / "inquiry_scenarios.csv"


@pytest.fixture
def synthetic_store(monkeypatch):
    monkeypatch.setenv("SOLSTICE_DATA_DIR", "data/synthetic")
    store_mod.get_store.cache_clear()
    yield store_mod.get_store()
    store_mod.get_store.cache_clear()


def _labels():
    with open(LABELS, newline="", encoding="utf-8") as f:
        return {r["inquiry_id"]: r for r in csv.DictReader(f)}


def test_cases_cover_every_scenario():
    cases = build_cases()
    assert len(cases) == 97                       # 95 clean inquiries + 2 with a fault the agent must catch
    assert {c["tags"][0] for c in cases} >= {"syn:within_rules", "syn:over_block_limit", "syn:over_discount",
                                              "syn:blackout", "syn:meeting_too_big", "syn:not_enough_rooms",
                                              "syn:needs_clarification", "syn:fault:unknown_property",
                                              "syn:fault:arrival_before_received"}
    sample = build_cases(35)
    assert len(sample) == 35 and sample == build_cases(35)
    assert len({c["tags"][0] for c in sample}) == 9


def _ideal_script(case, store, label):
    qid = case["turns"][0].split()[-1].rstrip(".")
    script = [[_tool("get_group_inquiry", {"inquiry_id": qid})]]
    decision = label["expected_decision"]
    if decision and decision != "NEEDS_CLARIFICATION":
        q = store.inquiries[qid]
        args = {"property_code": q.preferred_property, "arrival": q.arrival.isoformat(),
                "departure": q.departure.isoformat(), "rooms": q.rooms_requested, "room_type": q.room_type,
                "event_type": q.event_type, "meeting_capacity_needed": q.meeting_capacity_needed,
                "requested_discount_pct": q.requested_discount_pct, "budget_per_night": q.budget_per_night}
        script.append([_tool("evaluate_group_block", args, "t2")])
        if decision in PROPOSAL_STATUS:
            script.append([_tool("create_group_proposal", {**args, "inquiry_id": qid, "cover_note": "Offer."}, "t3")])
    pct = store.inquiries[qid].requested_discount_pct
    script.append([_text(f"We can't do every part as asked; the {pct}% discount is noted for Sales. "
                         "Please confirm the exact number of rooms, the arrival date and the room type.")])
    return script


def _grade(case, client):
    r = AgentSession(case["agent"], case["mode"], client=client).send(case["turns"][0])
    steps = [{"tool": s.tool, "input": s.input, "output": s.output, "ok": s.ok} for s in r.steps]
    return run_checks(case["expect"], steps, [r.text])


def test_ideal_agent_passes_every_case(synthetic_store):
    labels = _labels()
    failed = []
    for case in build_cases():
        qid = case["id"].removeprefix("syn-")
        checks = _grade(case, FakeClient(_ideal_script(case, synthetic_store, labels[qid])))
        if not all(c["passed"] for c in checks):
            failed.append((case["id"], [c for c in checks if not c["passed"]]))
    assert not failed, failed[:5]


def test_do_nothing_agent_fails_every_case(synthetic_store):
    passed = [c["id"] for c in build_cases()
              if all(x["passed"] for x in _grade(c, FakeClient([[_text("I'm not able to help with that.")]])))]
    assert not passed, passed


def test_proposal_elsewhere_fails_when_client_said_no_alternates():
    steps = [{"tool": "create_group_proposal", "input": {"property_code": "syn-038"}, "output": {"status": "x"}, "ok": True}]
    assert not run_checks({"proposal_property_in": ["SYN-065"]}, steps, ["ok"])[0]["passed"]
    assert run_checks({"proposal_property_in": ["SYN-038"]}, steps, ["ok"])[0]["passed"]
    assert run_checks({"proposal_property_in": ["SYN-065"]}, [], ["ok"])[0]["passed"]   # no proposal at all is fine
