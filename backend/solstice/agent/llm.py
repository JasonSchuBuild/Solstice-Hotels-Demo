"""The one place that knows which model provider we use.

Today: Anthropic API directly. Production: Claude in Microsoft Foundry, which
uses the same Messages API. Switching = changing this function, nothing else.
"""
from __future__ import annotations

import os
import threading


_client = None
_client_key = None
_lock = threading.Lock()


def get_client():
    """One client for the whole app, so every chat reuses the same warm HTTPS connections to the model
    instead of opening (and TLS-handshaking) a new pool per conversation. Rebuilt only if the timeout
    settings change. The Anthropic client is safe to share across threads."""
    global _client, _client_key
    import anthropic  # imported lazily so tests can run without the SDK

    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.")
    from solstice.config import get_settings

    s = get_settings()
    key = (s.request_timeout_s, s.max_retries)
    with _lock:
        if _client is None or _client_key != key:
            # Fail fast so the web app's "assistant unavailable" handoff runs in seconds, not minutes.
            _client = anthropic.Anthropic(timeout=s.request_timeout_s, max_retries=s.max_retries)
            _client_key = key
        return _client
