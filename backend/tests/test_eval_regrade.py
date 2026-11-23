"""Re-grading a saved run: answers stay as recorded, only the verdicts follow today's checks."""
import json

from solstice.evals.__main__ import regrade, steps_from_trace


def _trace(reply, tools=()):
    t = [{"role": "system", "content": "[concierge / guest system prompt]"},
         {"role": "user", "content": "What time is checkout?"}]
    for name, out in tools:
        t += [{"role": "tool_call", "name": name, "content": json.dumps({})},
              {"role": "tool_result", "content": json.dumps(out)}]
    return t + [{"role": "assistant", "content": reply}]


def test_steps_from_trace_marks_error_only_results_as_failed():
    steps, replies = steps_from_trace(_trace("hi", [("verify_guest", {"verified": True}),
                                                    ("lookup_reservation", {"error": "Staff only"})]))
    assert [s["ok"] for s in steps] == [True, False]
    assert replies == ["hi"]


def test_regrade_flips_a_wrong_verdict_and_keeps_the_original_summary(tmp_path):
    run = tmp_path / "20260101-000000_claude-test"
    (run / "traces").mkdir(parents=True)
    # Recorded as a failure by an older grader, but the answer is right under today's checks.
    (run / "traces" / "checkout-time_rep0.json").write_text(json.dumps(_trace("Checkout is at 11:00 AM.")), encoding="utf-8")
    row = {"prompt_id": "checkout-time", "rep": 0, "prompt": "What time is checkout?", "tags": ["routine"],
           "status": "ok", "grade": {"pass": 0.0}, "checks": [], "escalated": False, "resolves_alone": True,
           "agent": "concierge", "mode": "guest", "model": "claude-test", "usage": {"input_tokens": 1,
           "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
           "cost_usd": 0.0, "latency_s": 1.0, "tool_calls": 0}
    (run / "results.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    (run / "summary.md").write_text("# Eval results: claude-test\n\n**0/1 passed** · 12s wall clock\n", encoding="utf-8")

    msg = regrade(run)

    assert "FAIL → PASS" in msg
    assert (run / "summary-original.md").read_text(encoding="utf-8").startswith("# Eval results: claude-test")
    new = (run / "summary.md").read_text(encoding="utf-8")
    assert "**1/1 passed" in new and "Re-graded offline" in new and "checkout-time (rep 0)" in new
    assert json.loads((run / "results-regraded.jsonl").read_text(encoding="utf-8"))["grade"]["pass"] == 1.0
