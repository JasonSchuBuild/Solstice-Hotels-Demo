"""Web API: sessions, PIN gate, mode isolation, chat, graceful degradation, admin (no real model calls)."""
import pytest
from fastapi.testclient import TestClient

from solstice import runtime_store
from solstice.agent.runner import AgentSession
from solstice.web import app as web
from solstice.config import get_settings
from solstice.web.limits import UsageLimiter
from solstice.web.sessions import SessionStore
from tests.test_agent_loop import FakeClient, _text, _tool


class BrokenClient:
    """Simulates the model provider being down."""
    def __init__(self):
        self.messages = self

    def create(self, **kw):
        raise ConnectionError("provider down")


@pytest.fixture
def client(monkeypatch):
    scripts: list = []
    monkeypatch.setattr(web, "store", SessionStore())
    monkeypatch.setattr(web, "limiter", UsageLimiter())
    monkeypatch.setattr(web, "agent_factory",
                        lambda agent, mode: AgentSession(agent, mode, client=scripts.pop(0) if scripts else FakeClient([])))
    c = TestClient(web.app)
    c.scripts = scripts
    return c


def _start(c, view, pin=None):
    r = c.post("/api/sessions", json={"view": view, "pin": pin})
    return r, (r.json().get("token") if r.status_code == 200 else None)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_pages_and_health_probe_load(client):
    for path in ("/", "/staff", "/admin", "/static/common.js", "/healthz"):
        assert client.get(path).status_code == 200, path


def test_guest_session_needs_no_pin(client):
    r, token = _start(client, "guest")
    assert r.status_code == 200 and r.json()["mode"] == "guest" and token


@pytest.mark.parametrize("view,good,bad", [("front_desk", "1234", "4321"), ("group_sales", "1234", "0000"),
                                           ("admin", "4321", "1234")])
def test_staff_and_admin_need_their_own_pin(client, view, good, bad):
    assert _start(client, view, bad)[0].status_code == 401
    assert _start(client, view, good)[0].status_code == 200


def test_pin_lockout_after_repeated_failures(client):
    for _ in range(5):
        assert _start(client, "admin", "0000")[0].status_code == 401
    assert _start(client, "admin", "4321")[0].status_code == 429   # locked even with the right PIN


def test_guest_chat_hides_tool_details(client):
    client.scripts.append(FakeClient([
        [_tool("verify_guest", {"reservation_id": "R55004", "last_name": "Chen"})],
        [_text("Verified.")],
    ]))
    _, token = _start(client, "guest")
    r = client.post("/api/chat", json={"message": "Michael Chen R55004"}, headers=_auth(token)).json()
    assert r["text"] == "Verified." and r["steps"] == []


def test_staff_chat_shows_tool_trace(client):
    client.scripts.append(FakeClient([
        [_tool("lookup_reservation", {"reservation_id": "R55004"})],
        [_text("Found it.")],
    ]))
    _, token = _start(client, "front_desk", "1234")
    r = client.post("/api/chat", json={"message": "look up R55004"}, headers=_auth(token)).json()
    assert r["steps"][0]["tool"] == "lookup_reservation" and r["steps"][0]["ok"]


def test_guest_token_cannot_use_admin_or_staff_endpoints(client):
    _, token = _start(client, "guest")
    assert client.get("/api/admin/settings", headers=_auth(token)).status_code == 403
    assert client.get("/api/staff/tickets", headers=_auth(token)).status_code == 403
    assert client.get("/api/admin/settings").status_code == 401


def test_admin_cannot_chat(client):
    _, token = _start(client, "admin", "4321")
    assert client.post("/api/chat", json={"message": "hi"}, headers=_auth(token)).status_code == 403


def test_model_outage_degrades_to_staff_ticket(client):
    client.scripts.append(BrokenClient())
    _, token = _start(client, "guest")
    r = client.post("/api/chat", json={"message": "I need help with my booking"}, headers=_auth(token)).json()
    assert r["degraded"] is True and "ESC-" in r["text"]
    ticket = runtime_store.read_all("tickets")[0]
    assert ticket["transcript"][0]["text"] == "I need help with my booking"
    assert any(e["event"] == "model_unavailable" for e in runtime_store.read_all("audit"))


def test_admin_endpoints_return_data(client):
    _, token = _start(client, "admin", "4321")
    h = _auth(token)
    assert client.get("/api/admin/settings", headers=h).json()["max_tool_rounds"] > 0
    assert any(c["check"] == "data" for c in client.get("/api/admin/health", headers=h).json())
    assert "concierge/guest" in client.get("/api/admin/tools", headers=h).json()
    assert "turns" in client.get("/api/admin/activity", headers=h).json()
    assert isinstance(client.get("/api/admin/data-quality", headers=h).json(), list)


# ---------------- cost and abuse guardrails ----------------

def _limits(monkeypatch, **kw):
    for k, v in kw.items():
        monkeypatch.setitem(get_settings().raw["limits"], k, v)


def _say(c, token, text="hi"):
    return c.post("/api/chat", json={"message": text}, headers=_auth(token))


def _replies(c, n):
    for _ in range(n):
        c.scripts.append(FakeClient([[_text("ok")]] * 10))


def test_guest_message_length_limit(client):
    _, token = _start(client, "guest")
    r = _say(client, token, "x" * 1001)
    assert r.status_code == 413 and "1,000 characters" in r.json()["detail"]


def test_staff_can_send_longer_messages(client):
    client.scripts.append(FakeClient([[_text("ok")]]))
    _, token = _start(client, "front_desk", "1234")
    assert _say(client, token, "x" * 3000).status_code == 200


def test_chat_length_limit(client, monkeypatch):
    _limits(monkeypatch, max_messages_per_chat=2)
    _replies(client, 1)
    _, token = _start(client, "guest")
    assert _say(client, token).status_code == 200
    assert _say(client, token).status_code == 200
    r = _say(client, token)
    assert r.status_code == 429 and "new conversation" in r.json()["detail"]


def test_rate_limit_per_address(client, monkeypatch):
    _limits(monkeypatch, messages_per_window=3)
    _replies(client, 2)
    _, t1 = _start(client, "guest")
    _, t2 = _start(client, "guest")
    assert [_say(client, t).status_code for t in (t1, t1, t2)] == [200, 200, 200]
    assert _say(client, t2).status_code == 429          # a new chat doesn't reset the address limit
    assert any(e.get("kind") == "rate_limited" for e in runtime_store.read_all("audit"))


def test_new_chat_limit(client, monkeypatch):
    _limits(monkeypatch, new_chats_per_hour=2)
    assert _start(client, "guest")[0].status_code == 200
    assert _start(client, "guest")[0].status_code == 200
    assert _start(client, "guest")[0].status_code == 429


def test_daily_budget_stops_guests_not_staff(client, monkeypatch):
    _limits(monkeypatch, daily_token_budget=100)
    web.limiter.record_tokens(100)
    fake = FakeClient([])
    client.scripts.append(fake)
    _, guest = _start(client, "guest")
    r = _say(client, guest).json()
    assert r["limit"] == "daily_budget" and r["degraded"] and fake.calls == []   # no model call
    client.scripts.append(FakeClient([[_text("ok")]]))
    _, staff = _start(client, "front_desk", "1234")
    assert _say(client, staff).json()["text"] == "ok"


def test_tokens_are_counted(client):
    client.scripts.append(FakeClient([[_text("ok")]]))
    _, token = _start(client, "guest")
    _say(client, token)
    assert web.limiter.tokens_today() == 15                     # FakeClient reports 10 in + 5 out


def test_limit_hits_never_log_client_address(client, monkeypatch):
    _limits(monkeypatch, new_chats_per_hour=0)
    _start(client, "guest")
    assert "testclient" not in str(runtime_store.read_all("audit"))


def test_history_is_trimmed_but_verification_kept(monkeypatch):
    monkeypatch.setitem(get_settings().raw["agent"], "max_history_turns", 2)
    fake = FakeClient([[_tool("verify_guest", {"reservation_id": "R55004", "last_name": "Chen"})], [_text("hi")],
                       [_text("a")], [_text("b")]])
    s = AgentSession("concierge", "guest", client=fake)
    for m in ("one", "two", "three"):
        s.send(m)
    sent = fake.calls[-1]["messages"]
    user_texts = [m["content"] for m in sent if m["role"] == "user" and isinstance(m["content"], str)]
    assert user_texts == ["two", "three"] and sent[0]["role"] == "user"
    assert s.ctx.verified_guest_id is not None


def test_settings_never_expose_pins(client):
    _, token = _start(client, "admin", "4321")
    body = client.get("/api/admin/settings", headers=_auth(token)).text
    assert "1234" not in body and "4321" not in body


def test_restart_gives_a_fresh_staff_session_without_a_pin(client):
    _, token = _start(client, "front_desk", "1234")
    r = client.post("/api/sessions/restart", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["view"] == "front_desk" and r.json()["token"] != token
    # old session is gone, new one works
    assert client.post("/api/sessions/restart", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_restart_is_refused_for_guests_and_strangers(client):
    _, guest = _start(client, "guest")
    assert client.post("/api/sessions/restart", headers={"Authorization": f"Bearer {guest}"}).status_code == 401
    assert client.post("/api/sessions/restart").status_code == 401


def test_overlapping_turns_in_one_chat_are_refused_not_interleaved(client):
    client.scripts.append(FakeClient([[_text("ok")]]))
    _, tok = _start(client, "guest")
    ws = web.store.get(tok)
    ws.agent_session.lock.acquire()             # a turn is still running
    try:
        r = client.post("/api/chat", json={"message": "hello?"}, headers=_auth(tok))
        assert r.status_code == 409 and "still working" in r.json()["detail"]
    finally:
        ws.agent_session.lock.release()
    assert client.post("/api/chat", json={"message": "hello?"}, headers=_auth(tok)).json()["text"] == "ok"


def test_warm_up_never_raises(monkeypatch):
    import solstice.data.store as st
    monkeypatch.setattr(st, "get_store", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    web.warm_up()


def test_pages_link_static_files_by_content_hash(client):
    """A deploy must reach browsers that cached the old common.js/style.css: the URL changes with the file."""
    import re
    html = client.get("/").text
    refs = re.findall(r'/static/(common\.js|style\.css)\?v=([0-9a-f]{10})"', html)
    assert {r[0] for r in refs} == {"common.js", "style.css"}
    assert client.get(f"/static/common.js?v={refs[0][1]}").status_code == 200
