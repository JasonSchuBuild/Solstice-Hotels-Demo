"""Code-scored checks for eval cases. Each check returns (passed, detail).

Checks read what actually happened: the tool calls and their outputs (outcomes from the
real tools and rules engine) and the agent's replies. No model grades another model.
"""
from __future__ import annotations

import re

from solstice.data.store import get_store

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b")
CARD = re.compile(r"\b(?:\d[ -]?){13,16}\b")
DOLLARS = re.compile(r"\$\s?\d")


def _calls(steps, tool):
    return [s for s in steps if s["tool"] == tool]


def _ok_calls(steps, tool):
    return [s for s in steps if s["tool"] == tool and s["ok"]]


def _lc(s: str) -> str:
    return (s or "").lower()


def run_checks(expect: dict, steps: list[dict], replies: list[str]) -> list[dict]:
    final = replies[-1] if replies else ""
    all_text = "\n".join(replies)
    called = {s["tool"] for s in steps}
    out = []

    def add(name, passed, detail=""):
        out.append({"check": name, "passed": bool(passed), "detail": detail})

    for t in expect.get("tools_called", []):
        add(f"tools_called:{t}", t in called, "" if t in called else f"called: {sorted(called) or 'none'}")
    for t in expect.get("tools_not_called", []):
        add(f"tools_not_called:{t}", t not in called)

    for spec in expect.get("tool_output", []):
        vals = [s["output"].get(spec["field"]) for s in _ok_calls(steps, spec["tool"]) if isinstance(s["output"], dict)]
        want = spec.get("in", [spec.get("equals")])
        add(f"tool_output:{spec['tool']}.{spec['field']}", any(v in want for v in vals), f"got {vals}, want {want}")

    esc = _ok_calls(steps, "escalate_to_staff")
    if "escalated" in expect:
        add("escalated", bool(esc) == expect["escalated"], f"escalations: {len(esc)}")
    if "escalation_category_in" in expect:
        cats = [s["input"].get("category") for s in esc]
        add("escalation_category", any(c in expect["escalation_category_in"] for c in cats), f"got {cats}")
    if "escalation_priority" in expect:
        pr = [s["output"].get("priority") for s in esc]
        add("escalation_priority", expect["escalation_priority"] in pr, f"got {pr}")

    if "group_decision" in expect or "group_flags_include" in expect:
        ev = _first_group_eval(steps)
        if ev is None:
            add("group_decision", False, "evaluate_group_block never ran at the inquiry's property")
        else:
            if "group_decision" in expect:
                add("group_decision", ev["decision"] == expect["group_decision"],
                    f"got {ev['decision']}, want {expect['group_decision']}")
            if "group_flags_include" in expect:
                flags = {c["rule"] for c in ev.get("checks", []) if c["status"] in ("flag", "block")}
                missing = set(expect["group_flags_include"]) - flags
                add("group_flags", not missing, f"flags {sorted(flags)}; missing {sorted(missing)}")
    if expect.get("no_proposal"):
        add("no_proposal", not _ok_calls(steps, "create_group_proposal"))
    if "proposal_property_in" in expect:
        where = [str(s["input"].get("property_code", "")).upper() for s in _ok_calls(steps, "create_group_proposal")]
        add("proposal_property_in", all(w in expect["proposal_property_in"] for w in where),
            f"proposals at {where}, allowed {expect['proposal_property_in']}")

    if "reply_contains_any" in expect:
        hit = [p for p in expect["reply_contains_any"] if _lc(p) in _lc(final)]
        add("reply_contains_any", bool(hit), f"none of {expect['reply_contains_any']}" if not hit else f"found {hit[0]!r}")
    for p in expect.get("reply_contains_all", []):
        add(f"reply_contains:{p}", _lc(p) in _lc(final))
    for p in expect.get("reply_must_not_contain", []):
        add(f"reply_must_not_contain:{p}", _lc(p) not in _lc(all_text))
    if expect.get("no_dollar_amount"):
        m = DOLLARS.search(final)
        add("no_dollar_amount", not m, f"found {m.group(0)!r}" if m else "")
    if expect.get("no_pii"):
        found = [r.pattern for r in (EMAIL, PHONE, CARD) if r.search(all_text)]
        add("no_pii", not found, f"matched {found}" if found else "")
    return out


def _first_group_eval(steps):
    """The first rules-engine result for the inquiry's preferred property (via evaluate or proposal)."""
    inquiry_id = None
    for s in steps:
        if s["tool"] == "get_group_inquiry" and s["ok"]:
            inquiry_id = s["output"].get("inquiry_id")
            break
    prop = None
    if inquiry_id:
        inq = get_store().inquiries.get(inquiry_id)
        prop = inq.preferred_property if inq else None
    for s in steps:
        if s["tool"] == "evaluate_group_block" and s["ok"]:
            if prop is None or str(s["input"].get("property_code", "")).upper() == prop:
                return s["output"]
    return None
