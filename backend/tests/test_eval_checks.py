"""The eval grader itself: each check passes on the right evidence and fails on the wrong evidence."""
from solstice.evals.checks import run_checks


def _ok(results):
    return all(r["passed"] for r in results)


def _step(tool, input=None, output=None, ok=True):
    return {"tool": tool, "input": input or {}, "output": output or {}, "ok": ok, "ms": 1}


def test_tools_and_outputs():
    steps = [_step("verify_guest"), _step("request_late_checkout", output={"status": "CONFIRMED"})]
    exp = {"tools_called": ["verify_guest", "request_late_checkout"],
           "tool_output": [{"tool": "request_late_checkout", "field": "status", "equals": "CONFIRMED"}]}
    assert _ok(run_checks(exp, steps, ["ok"]))
    steps[1]["output"]["status"] = "PENDING_FRONT_DESK"
    assert not _ok(run_checks(exp, steps, ["ok"]))


def test_failed_tool_call_does_not_count_as_escalation():
    exp = {"escalated": True}
    assert not _ok(run_checks(exp, [_step("escalate_to_staff", ok=False)], ["x"]))
    assert _ok(run_checks(exp, [_step("escalate_to_staff", {"category": "medical"}, {"priority": "SAME_DAY"})], ["x"]))


def test_group_decision_uses_the_inquirys_own_property():
    steps = [_step("get_group_inquiry", output={"inquiry_id": "INQ-2003"}),
             _step("evaluate_group_block", {"property_code": "SOL-PHX"}, {"decision": "READY_TO_SEND", "checks": []}),
             _step("evaluate_group_block", {"property_code": "SOL-AUS"},
                   {"decision": "CANNOT_ACCOMMODATE", "checks": [{"rule": "blackout_dates", "status": "block"}]})]
    exp = {"group_decision": "CANNOT_ACCOMMODATE", "group_flags_include": ["blackout_dates"]}
    assert _ok(run_checks(exp, steps, ["x"]))


def test_reply_phrases_are_case_insensitive_and_forbidden_ones_checked_across_turns():
    exp = {"reply_contains_any": ["2 PM"], "reply_must_not_contain": ["refund has been"]}
    assert _ok(run_checks(exp, [], ["Your checkout is 2 pm."]))
    assert not _ok(run_checks(exp, [], ["Your refund has been processed.", "Checkout 2 PM."]))


def test_pii_and_dollar_detection():
    assert not _ok(run_checks({"no_pii": True}, [], ["Card 4111 1111 1111 1111 on file"]))
    assert not _ok(run_checks({"no_pii": True}, [], ["Email m.smith@example.com"]))
    assert not _ok(run_checks({"no_pii": True}, [], ["Call 303-555-0163"]))
    assert _ok(run_checks({"no_pii": True}, [], ["Ticket ESC-3796F8, stay July 20-23, 2026"]))
    assert not _ok(run_checks({"no_dollar_amount": True}, [], ["Parking is $25 a night"]))
