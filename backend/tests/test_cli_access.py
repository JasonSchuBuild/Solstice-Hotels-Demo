"""Staff PIN gate and mode menu in the terminal app (no API calls)."""
import pytest

from solstice import cli
from solstice.tools.registry import tools_for


def _feed(monkeypatch, *values):
    it = iter(values)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(it))


def test_correct_pin_allows_staff(monkeypatch):
    _feed(monkeypatch, "1234")
    assert cli.pin_ok("staff")


def test_three_wrong_pins_deny_staff(monkeypatch):
    _feed(monkeypatch, "0000", "1111", "9999")
    assert not cli.pin_ok("staff")


def test_pin_can_be_overridden_by_env(monkeypatch):
    monkeypatch.setenv("SOLSTICE_STAFF_PIN", "8642")
    _feed(monkeypatch, "1234", "8642")
    assert cli.pin_ok("staff")


def test_admin_pin_is_separate_from_staff_pin(monkeypatch):
    _feed(monkeypatch, "1234", "0000", "1111")   # staff PIN does not open admin
    assert not cli.pin_ok("admin")
    _feed(monkeypatch, "4321")
    assert cli.pin_ok("admin")
    _feed(monkeypatch, "4321", "0000", "1111")   # admin PIN does not open staff
    assert not cli.pin_ok("staff")


@pytest.mark.parametrize("choice,expected", [
    ("1", ("concierge", "guest")),
    ("2", ("concierge", "staff")),
    ("3", ("group_sales", "staff")),
    ("4", ("admin", "admin")),
])
def test_menu_maps_choice_to_agent_and_mode(monkeypatch, choice, expected):
    answers = iter(["x", choice])  # first answer invalid, re-prompts
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert cli.choose_from_menu() == expected


def test_pin_attempts_are_audited(monkeypatch):
    from solstice import runtime_store
    _feed(monkeypatch, "0000", "1234")
    assert cli.pin_ok("staff")
    events = [e for e in runtime_store.read_all("audit") if e["event"] == "pin"]
    assert [(e["role"], e["ok"]) for e in events] == [("staff", False), ("staff", True)]
    assert "1234" not in str(events)  # the PIN itself is never logged


def test_admin_health_checks_pass_offline():
    from solstice import admin
    checks = admin.health_checks(check_api=False)
    assert not [c for c in checks if c[0] == "FAIL"], checks
    assert {c[1] for c in checks} >= {"data", "prompts", "policy doc", "runtime folder"}


def test_admin_activity_summary_reads_runtime_logs():
    from solstice import admin, runtime_store
    runtime_store.append("traces", {"agent": "concierge", "mode": "guest", "latency_s": 2.0,
                                    "input_tokens": 100, "output_tokens": 50, "tools": [{"tool": "x", "ok": False, "ms": 1}]})
    runtime_store.append("audit", {"event": "pin", "role": "admin", "ok": False, "attempt": 1})
    a = admin.activity_summary()
    assert a["turns"] == 1 and a["tool_errors"] == 1 and a["pin_failures"] == {"admin": 1}


def test_guest_verification_locks_after_limit():
    from solstice import runtime_store
    from solstice.tools.concierge_tools import verify_guest
    from solstice.tools.registry import ToolContext, ToolError
    ctx = ToolContext(agent="concierge", mode="guest", session_id="t1")
    for _ in range(3):
        assert verify_guest(ctx, "R55004", "Wrongname")["verified"] is False
    with pytest.raises(ToolError, match="locked"):
        verify_guest(ctx, "R55004", "Chen")  # correct details, but locked
    assert ctx.verified_guest_id is None
    audit = runtime_store.read_all("audit")
    assert sum(e["event"] == "verification_failed" for e in audit) == 3
    assert "Wrongname" not in str(audit)  # no names in the audit log


def test_guest_mode_never_gets_staff_tools():
    guest = {t.name for t in tools_for("concierge", "guest")}
    staff = {t.name for t in tools_for("concierge", "staff")}
    staff_only = {"lookup_reservation", "search_guests", "list_reservations", "check_comp_authority", "get_data_quality_report"}
    assert staff_only <= staff
    assert not (staff_only & guest)
