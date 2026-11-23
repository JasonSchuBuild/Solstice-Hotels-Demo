"""Website theme: which look every page uses, chosen by an admin and saved so it survives restarts.

Saved through solstice/settings_store.py (a file locally, Azure Blob Storage when deployed). If the store is
unreachable the site falls back to the default theme: a storage hiccup must never take a page down.
Available themes and the default are in config/themes.yaml.
"""
from __future__ import annotations

import logging
import threading
import time

from solstice import runtime_store, settings_store
from solstice.config import REPO_ROOT, load_yaml

log = logging.getLogger("solstice.themes")

DOC = "theme.json"
CACHE_SECONDS = 30   # how long one app instance trusts what it last read (writes update it at once)


def catalog() -> dict:
    return load_yaml(REPO_ROOT / "config" / "themes.yaml")


def available() -> list[dict]:
    return catalog()["themes"]


def default_id() -> str:
    return catalog()["default"]


def is_valid(theme_id: str) -> bool:
    return any(t["id"] == theme_id for t in available())


_backend = None
_cache: tuple[float, str] | None = None
_lock = threading.Lock()


def backend():
    global _backend
    if _backend is None:
        _backend = settings_store.make(DOC)
    return _backend


def reset_cache() -> None:
    global _cache
    _cache = None


def current() -> str:
    """The active theme id. Cached briefly; falls back to the default if the store is unreadable."""
    global _cache
    now = time.monotonic()
    if _cache and now - _cache[0] < CACHE_SECONDS:
        return _cache[1]
    theme = default_id()
    try:
        data = backend().read()
        if data and is_valid(data.get("theme", "")):
            theme = data["theme"]
    except Exception:
        log.exception("could not read the saved theme; using the default")
        # Retry soon rather than caching a failure for the full window.
        _cache = (now - CACHE_SECONDS + 5, theme)
        return theme
    _cache = (now, theme)
    return theme


def save(theme_id: str, actor: str = "admin") -> str:
    """Persist a new theme. Raises ValueError for an unknown id; storage errors propagate to the caller."""
    global _cache
    if not is_valid(theme_id):
        raise ValueError(f"Unknown theme: {theme_id}")
    with _lock:
        backend().write({"theme": theme_id, "updated_at": runtime_store.now_iso(), "updated_by": actor})
        _cache = (time.monotonic(), theme_id)
    runtime_store.append("audit", {"event": "theme_changed", "theme": theme_id, "by": actor,
                                   "store": backend().name})
    return theme_id


def status() -> dict:
    return {"current": current(), "default": default_id(), "themes": available(), "store": backend().name}
