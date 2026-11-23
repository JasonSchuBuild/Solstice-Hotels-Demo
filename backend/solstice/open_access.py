"""Demo open access: lets the staff and admin web pages sign in with a BLANK PIN.

An admin flips it from the console (Admin -> Access), so a live demo can run with or without PINs and no
deploy or restart. It is saved through solstice/settings_store.py, so it survives restarts in Azure.

Safe by default: off unless an admin turned it on, and off whenever the saved value can't be read.
`access.allow_open_access` in config/settings.yaml is the master switch: when false the toggle is refused and
a blank PIN never works, for a deployment that should never offer it.
The browser's ?demo=on switch has nothing to do with this; only the server decides.
"""
from __future__ import annotations

import logging
import threading
import time

from solstice import runtime_store, settings_store
from solstice.config import get_settings

log = logging.getLogger("solstice.open_access")

DOC = "open_access.json"
CACHE_SECONDS = 5   # short: turning it OFF should take effect right away


class NotAllowed(Exception):
    """The master switch (access.allow_open_access) is off."""


_backend = None
_cache: tuple[float, bool] | None = None
_lock = threading.Lock()


def backend():
    global _backend
    if _backend is None:
        _backend = settings_store.make(DOC)
    return _backend


def reset_cache() -> None:
    global _cache
    _cache = None


def allowed() -> bool:
    return bool(get_settings().raw["access"].get("allow_open_access", False))


def is_on() -> bool:
    global _cache
    if not allowed():
        return False
    now = time.monotonic()
    if _cache and now - _cache[0] < CACHE_SECONDS:
        return _cache[1]
    try:
        data = backend().read()
        on = bool(data and data.get("enabled") is True)
    except Exception:
        log.exception("could not read the open-access setting; treating it as off")
        on = False
    _cache = (now, on)
    return on


def set_enabled(enabled: bool, actor: str = "admin") -> bool:
    """Persist the setting. Raises NotAllowed if the master switch is off; storage errors propagate."""
    global _cache
    if not allowed():
        raise NotAllowed()
    with _lock:
        backend().write({"enabled": bool(enabled), "updated_at": runtime_store.now_iso(), "updated_by": actor})
        _cache = (time.monotonic(), bool(enabled))
    runtime_store.append("audit", {"event": "open_access_changed", "enabled": bool(enabled), "by": actor,
                                   "store": backend().name})
    return bool(enabled)


def status() -> dict:
    return {"allowed": allowed(), "enabled": is_on(), "store": backend().name}
