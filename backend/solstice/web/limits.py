"""Cost and abuse limits for the web app.

Layers (all thresholds in config/settings.yaml -> limits):
  - message length, per mode
  - messages per chat
  - messages per client address in a rolling window
  - new chats per client address per hour
  - a daily token budget across all chats (guests are stopped when it's reached; staff aren't)

Counters live in memory, per app instance. That's right for the single-replica demo.
Production moves rate limiting to the edge (Azure Front Door / API Management) and the
counters to a shared store. The hard spending cap belongs at the model provider
(a demo-only API key with a monthly spend limit).
"""
from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timezone

from solstice import runtime_store
from solstice.config import get_settings


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


class LimitExceeded(Exception):
    """kind: message_too_long | chat_limit | rate_limited | new_chat_limit | daily_budget"""
    def __init__(self, kind: str, message: str, status: int = 429):
        super().__init__(message)
        self.kind, self.message, self.status = kind, message, status


class UsageLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._messages: dict[str, deque] = {}
        self._new_chats: dict[str, deque] = {}
        self._day = _today()
        self._tokens_today = self._tokens_from_traces(self._day)
        self.hits: dict[str, int] = {}

    # ----- checks (raise LimitExceeded) -----

    def check_new_chat(self, client: str) -> None:
        cap = get_settings().limit("new_chats_per_hour")
        with self._lock:
            q = self._window(self._new_chats, client, 3600)
            if len(q) >= cap:
                self._hit("new_chat_limit", client)
                raise LimitExceeded("new_chat_limit", "You've started a lot of conversations. Please wait a while and try again.")
            q.append(time.time())

    def check_message(self, client: str, mode: str, text: str, messages_in_chat: int) -> None:
        s = get_settings()
        max_chars = s.limit("max_message_chars_staff" if mode == "staff" else "max_message_chars_guest")
        if len(text) > max_chars:
            self._hit("message_too_long", client)
            raise LimitExceeded("message_too_long",
                                f"That message is too long. Please keep it under {max_chars:,} characters.", 413)
        if messages_in_chat >= s.limit("max_messages_per_chat"):
            self._hit("chat_limit", client)
            raise LimitExceeded("chat_limit", "This conversation has reached its length limit. "
                                              "Please start a new conversation to continue.")
        window_s = s.limit("window_minutes") * 60
        with self._lock:
            q = self._window(self._messages, client, window_s)
            if len(q) >= s.limit("messages_per_window"):
                self._hit("rate_limited", client)
                raise LimitExceeded("rate_limited", "You're sending messages quickly. "
                                                    "Please wait a few minutes and try again.")
            q.append(time.time())
        if mode == "guest" and self.tokens_today() >= s.limit("daily_token_budget"):
            self._hit("daily_budget", client)
            raise LimitExceeded("daily_budget", "Our online assistant has reached its limit for today. "
                                                "The front desk team can help you directly.", 200)

    # ----- accounting -----

    def record_tokens(self, n: int) -> None:
        with self._lock:
            self._roll_day()
            self._tokens_today += n

    def tokens_today(self) -> int:
        with self._lock:
            self._roll_day()
            return self._tokens_today

    def status(self) -> dict:
        budget = get_settings().limit("daily_token_budget")
        used = self.tokens_today()
        return {"tokens_today": used, "daily_token_budget": budget,
                "budget_used_pct": round(100 * used / budget, 1) if budget else 0,
                "limit_hits": dict(self.hits)}

    # ----- internals -----

    def _window(self, store: dict, key: str, seconds: float) -> deque:
        q = store.setdefault(key, deque())
        cutoff = time.time() - seconds
        while q and q[0] < cutoff:
            q.popleft()
        return q

    def _roll_day(self) -> None:
        if _today() != self._day:
            self._day, self._tokens_today = _today(), 0

    def _hit(self, kind: str, client: str) -> None:
        self.hits[kind] = self.hits.get(kind, 0) + 1
        # The client address is used for counting only; it's not written to the audit log.
        runtime_store.append("audit", {"event": "limit_hit", "kind": kind})

    @staticmethod
    def _tokens_from_traces(day: str) -> int:
        """Re-count today's usage after a restart (when the runtime logs survived)."""
        return sum(t.get("input_tokens", 0) + t.get("output_tokens", 0)
                   for t in runtime_store.read_all("traces") if str(t.get("created_at", "")).startswith(day))
