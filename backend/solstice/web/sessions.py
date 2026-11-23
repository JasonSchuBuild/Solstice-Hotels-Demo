"""Web sessions and the demo PIN gate.

Each browser chat gets a random token that maps to one AgentSession on the server.
The agent and mode are fixed when the session is created; the browser can never
change them. Sessions live in memory (fine for a single-replica demo; production
uses Entra ID sign-in and a shared store, see docs/ACCESS_CONTROL.md).
"""
from __future__ import annotations

import hmac
import secrets
import threading
import time
from dataclasses import dataclass, field

from solstice import open_access, runtime_store
from solstice.config import get_settings

IDLE_TIMEOUT_S = 30 * 60
PIN_MAX_FAILURES = 5          # per client address...
PIN_LOCKOUT_S = 5 * 60        # ...then locked for this long

# What each page may start. view -> (agent, mode, pin role or None)
VIEWS = {
    "guest": ("concierge", "guest", None),
    "front_desk": ("concierge", "staff", "staff"),
    "group_sales": ("group_sales", "staff", "staff"),
    "admin": (None, "admin", "admin"),
}


@dataclass
class WebSession:
    view: str
    agent: str | None
    mode: str
    agent_session: object | None = None      # AgentSession, None for admin
    last_seen: float = field(default_factory=time.time)
    messages: int = 0                        # user messages sent in this chat


class SessionStore:
    def __init__(self):
        self._sessions: dict[str, WebSession] = {}
        self._pin_failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    # ----- PIN gate -----
    def pin_locked(self, client: str) -> bool:
        now = time.time()
        recent = [t for t in self._pin_failures.get(client, []) if now - t < PIN_LOCKOUT_S]
        self._pin_failures[client] = recent
        return len(recent) >= PIN_MAX_FAILURES

    def check_pin(self, role: str, pin: str, client: str) -> bool:
        pin = (pin or "").strip()
        s = get_settings()
        if not pin and open_access.is_on():   # demo open access (admin toggle): a blank PIN is let in, and logged as such
            runtime_store.append("audit", {"event": "pin", "role": role, "ok": True, "channel": "web",
                                           "open_access": True})
            return True
        ok = hmac.compare_digest(pin, s.pin_for(role))
        runtime_store.append("audit", {"event": "pin", "role": role, "ok": ok, "channel": "web"})
        if not ok:
            self._pin_failures.setdefault(client, []).append(time.time())
        return ok

    # ----- sessions -----
    def create(self, view: str, agent_factory=None) -> tuple[str, WebSession]:
        agent, mode, _ = VIEWS[view]
        agent_session = agent_factory(agent, mode) if agent else None
        token = secrets.token_urlsafe(24)
        ws = WebSession(view, agent, mode, agent_session)
        with self._lock:
            self._expire()
            self._sessions[token] = ws
        return token, ws

    def get(self, token: str | None) -> WebSession | None:
        with self._lock:
            self._expire()
            ws = self._sessions.get(token or "")
            if ws:
                ws.last_seen = time.time()
            return ws

    def end(self, token: str | None) -> None:
        with self._lock:
            self._sessions.pop(token or "", None)

    def _expire(self) -> None:
        now = time.time()
        for t in [t for t, s in self._sessions.items() if now - s.last_seen > IDLE_TIMEOUT_S]:
            del self._sessions[t]
