"""Where the agent's *outputs* land: escalation tickets, service requests,
group proposals and turn traces. Plain JSON files under data/runtime/.

The staff console reads these. In production they become rows in the ticketing
system / CRM, and traces go to Application Insights.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from solstice.config import get_settings


def _dir() -> Path:
    d = get_settings().path("runtime_dir")
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6].upper()}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append(kind: str, record: dict) -> dict:
    """kind: tickets | requests | proposals | traces"""
    record = {"created_at": now_iso(), **record}
    with open(_dir() / f"{kind}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")
    return record


def read_all(kind: str) -> list[dict]:
    p = _dir() / f"{kind}.jsonl"
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
