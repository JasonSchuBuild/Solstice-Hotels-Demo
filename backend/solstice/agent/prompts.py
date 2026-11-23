"""Builds the system prompt from the markdown files in config/prompts/.

Order: shared guardrails -> role prompt -> today's date -> policy reference.
The policy doc is short (~2k tokens), so it goes in whole and is prompt-cached.
"""
from __future__ import annotations

from solstice.config import get_settings


def build_system_prompt(agent: str, mode: str) -> str:
    s = get_settings()
    d = s.path("prompts_dir")
    parts = [
        (d / "shared_guardrails.md").read_text(encoding="utf-8"),
        (d / f"{agent}.md").read_text(encoding="utf-8"),
        f"## Session\n- Today's date: {s.today.isoformat()}\n- Mode: {mode} "
        f"({'a front-desk associate is using this' if mode == 'staff' else 'you are talking directly to a guest'})",
        "## Solstice Front Desk Policy Reference (authoritative)\n\n" + s.path("policy_doc").read_text(encoding="utf-8"),
    ]
    return "\n\n---\n\n".join(parts)
