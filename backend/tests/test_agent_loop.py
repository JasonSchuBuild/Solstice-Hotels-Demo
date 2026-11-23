"""Agent loop and tool access control, run offline with a scripted fake model."""
from types import SimpleNamespace as NS

from solstice import runtime_store
from solstice.agent.runner import AgentSession


class _Block(NS):
    def model_dump(self):
        return {k: v for k, v in self.__dict__.items()}


def _text(t):
    return _Block(type="text", text=t)


def _tool(name, args, id_="t1"):
    return _Block(type="tool_use", id=id_, name=name, input=args)


class FakeClient:
    """Returns pre-scripted responses in order; records what it was sent."""
    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        content = self.script.pop(0)
        stop = "tool_use" if any(b.type == "tool_use" for b in content) else "end_turn"
        return NS(content=content, stop_reason=stop, usage=NS(input_tokens=10, output_tokens=5))


def test_loop_runs_tool_then_answers():
    fake = FakeClient([
        [_tool("verify_guest", {"reservation_id": "R55004", "last_name": "Chen"})],
        [_tool("request_late_checkout", {"reservation_id": "R55004"}, "t2")],
        [_text("You're confirmed for 2 PM checkout.")],
    ])
    s = AgentSession("concierge", "guest", client=fake)
    r = s.send("I'm Michael Chen, R55004. Can I check out late?")
    assert r.text == "You're confirmed for 2 PM checkout."
    assert [st.tool for st in r.steps] == ["verify_guest", "request_late_checkout"]
    assert r.steps[1].output["status"] == "CONFIRMED"          # Platinum
    assert runtime_store.read_all("traces")


def test_guest_cannot_read_unverified_reservation():
    fake = FakeClient([[_tool("check_cancellation_terms", {"reservation_id": "R55001"})], [_text("Please verify.")]])
    r = AgentSession("concierge", "guest", client=fake).send("cancel R55001")
    assert r.steps[0].ok is False and "not verified" in r.steps[0].output["error"]


def test_guest_cannot_read_someone_elses_reservation():
    fake = FakeClient([
        [_tool("verify_guest", {"reservation_id": "R55001", "last_name": "Bennett"})],
        [_tool("check_cancellation_terms", {"reservation_id": "R55004"}, "t2")],
        [_text("Sorry, I can't.")],
    ])
    r = AgentSession("concierge", "guest", client=fake).send("hi")
    assert r.steps[1].ok is False


def test_staff_only_tools_hidden_from_guests():
    names = set(AgentSession("concierge", "guest", client=FakeClient([])).tools)
    assert "lookup_reservation" not in names and "search_guests" not in names
    assert "lookup_reservation" in AgentSession("concierge", "staff", client=FakeClient([])).tools


def test_escalation_attaches_transcript_and_routes_safety_urgently():
    fake = FakeClient([
        [_tool("escalate_to_staff", {"category": "safety_or_security", "summary": "Guest reports a threat.",
                                     "recommended_next_step": "Call guest now."})],
        [_text("I've alerted our security team.")],
    ])
    AgentSession("concierge", "guest", client=fake).send("someone is threatening me in the lobby")
    t = runtime_store.read_all("tickets")[0]
    assert t["priority"] == "URGENT" and "Regional Security" in t["route_to"]
    assert t["transcript"][0]["text"].startswith("someone is threatening")


def test_group_proposal_status_set_by_rules_not_model():
    fake = FakeClient([
        [_tool("create_group_proposal", {"inquiry_id": "INQ-2009", "cover_note": "Approved!", "property_code": "SOL-PHX",
                                         "arrival": "2026-07-28", "departure": "2026-07-31", "rooms": 15,
                                         "room_type": "Deluxe King", "requested_discount_pct": 17})],
        [_text("done")],
    ])
    r = AgentSession("group_sales", "staff", client=fake).send("approve INQ-2009")
    assert r.steps[0].output["status"] == "PENDING_HUMAN_APPROVAL"


def test_reply_cut_off_at_max_tokens_is_flagged():
    class Capped(FakeClient):
        def create(self, **kw):
            r = super().create(**kw)
            r.stop_reason = "max_tokens"
            return r
    r = AgentSession("group_sales", "staff", client=Capped([[_text("Suggested reply: Thank you for your interest in five")]])).send("x")
    assert r.truncated and "cut short" in r.text
    assert runtime_store.read_all("traces")[-1]["truncated"] is True


def test_out_of_tool_rounds_hands_off_with_a_ticket():
    from solstice.config import get_settings
    rounds = get_settings().max_tool_rounds
    fake = FakeClient([[_tool("get_property_info", {"property_code": "SOL-CHI"}, f"t{i}")] for i in range(rounds)])
    r = AgentSession("concierge", "guest", client=fake).send("tell me everything about Chicago")
    tickets = runtime_store.read_all("tickets")
    assert len(tickets) == 1 and tickets[0]["ticket_id"] in r.text
    assert tickets[0]["transcript"][0]["text"] == "tell me everything about Chicago"


def test_medical_escalation_is_urgent():
    fake = FakeClient([
        [_tool("escalate_to_staff", {"category": "medical", "summary": "Guest slipped and hurt their ankle.",
                                     "recommended_next_step": "Send the manager on duty now."})],
        [_text("I've alerted the manager on duty.")],
    ])
    AgentSession("concierge", "guest", client=fake).send("I slipped in the shower and hurt my ankle")
    assert runtime_store.read_all("tickets")[0]["priority"] == "URGENT"


def test_unknown_tool_fails_soft():
    fake = FakeClient([[_tool("issue_refund", {"amount": 500})], [_text("I'll escalate.")]])
    r = AgentSession("concierge", "guest", client=fake).send("refund me")
    assert r.steps[0].ok is False


def test_system_prompt_contains_policy_and_guardrails():
    s = AgentSession("concierge", "guest", client=FakeClient([]))
    assert "ESCALATION MATRIX" in s.system and "Grounded or nothing" in s.system


def test_failed_model_call_rolls_back_history_so_the_chat_keeps_working():
    class FlakyOnce(FakeClient):
        def create(self, **kw):
            if not self.calls:
                self.calls.append(kw)
                raise TimeoutError("model timed out")
            return super().create(**kw)
    s = AgentSession("concierge", "guest", client=FlakyOnce([[_text("Happy to help.")]]))
    try:
        s.send("first try")
    except TimeoutError:
        pass
    assert s.messages == []                                   # nothing half-finished left behind
    assert s.ctx.transcript[0]["text"] == "first try"         # staff still see what was asked
    assert s.send("follow-up").text == "Happy to help."
    assert [m["role"] for m in s.messages] == ["user", "assistant"]


def test_turn_deadline_hands_off_instead_of_hanging(monkeypatch):
    import solstice.agent.runner as runner
    clock = iter([0.0, 0.0, 50.0, 50.0, 50.0, 50.0])   # second round starts past the 45 s budget
    monkeypatch.setattr(runner.time, "perf_counter", lambda: next(clock, 50.0))
    fake = FakeClient([[_tool("get_property_info", {"property_code": "SOL-CHI"})], [_text("never sent")]])
    s = AgentSession("concierge", "guest", client=fake)
    r = s.send("tell me about Chicago")
    assert len(fake.calls) == 1 and "passed this conversation" in r.text
    assert runtime_store.read_all("tickets")
    assert s.messages[-1]["role"] == "assistant"          # history is closed off, so a follow-up is valid
    assert fake.calls[0]["timeout"] <= 30


def test_reply_cut_off_mid_tool_call_does_not_break_the_next_turn():
    class Capped(FakeClient):
        def create(self, **kw):
            r = super().create(**kw)
            r.stop_reason = "max_tokens"
            return r
    s = AgentSession("concierge", "guest", client=Capped([[_text("Let me check"), _tool("get_property_info", {})]]))
    s.send("x")
    assert all(b["type"] != "tool_use" for b in s.messages[-1]["content"])
