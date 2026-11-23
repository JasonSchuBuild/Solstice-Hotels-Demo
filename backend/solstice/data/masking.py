"""PII masking. Every value the agent (LLM) sees passes through here first.

Rule of thumb: the model gets just enough to help the guest and nothing it could
leak. Payment data is never passed through at all, not even the last 4 digits.
"""
from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_PHONE_RE = re.compile(r"\b(\d{3})[-. ]?(\d{3})[-. ]?(\d{4})\b")
# 13-19 digit runs (with optional spaces/dashes) look like card numbers.
_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def mask_email(email: str) -> str:
    if not email:
        return ""
    return _EMAIL_RE.sub(lambda m: f"{m.group(1)}***@{m.group(2)}", email)


def mask_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    return f"***-***-{digits[-4:]}" if len(digits) >= 4 else ""


def scrub_free_text(text: str) -> str:
    """Defense in depth for notes/requests typed by staff or guests."""
    if not text:
        return ""
    text = _CARD_RE.sub("[REDACTED-CARD]", text)
    text = _EMAIL_RE.sub(lambda m: f"{m.group(1)}***@{m.group(2)}", text)
    text = _PHONE_RE.sub(lambda m: f"***-***-{m.group(3)}", text)
    return text
