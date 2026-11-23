"""Admin console: agent settings, health checks, tools, activity, data quality.

Deterministic: it never calls the model for text, so it costs nothing to open during a demo.
To change a setting, edit the file it points to (config/settings.yaml, config/group_rules.yaml,
config/prompts/*.md) and save: settings and group rules apply on the next request, prompts on the
next new conversation, with no restart. The only settings written from the console are the website
theme (themes.py) and demo open access (open_access.py), both on the web admin page.
Secrets (API key, PINs) are never printed, only whether they are set and where from.
"""
from __future__ import annotations

import os
from collections import Counter

from solstice import open_access, runtime_store
from solstice.config import REPO_ROOT, get_settings

BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"
MARK = {"OK": "\033[32mOK  \033[0m", "WARN": "\033[33mWARN\033[0m", "FAIL": "\033[31mFAIL\033[0m"}
AGENTS = ("concierge", "group_sales")
PROMPT_FILES = ("shared_guardrails.md", "concierge.md", "group_sales.md")


def _h(title: str) -> None:
    print(f"\n{BOLD}{title}{RESET}")


def _rel(p) -> str:
    return str(p.relative_to(REPO_ROOT)).replace("\\", "/")


# ---------------- data (used by the web admin page; the show_* functions print for the terminal) ----------------

def settings_summary() -> dict:
    import yaml
    s = get_settings()
    env_model = os.getenv("SOLSTICE_MODEL")
    with open(s.path("group_rules"), encoding="utf-8") as f:
        rules = yaml.safe_load(f)
    return {
        "edit_files": ["config/settings.yaml", "config/group_rules.yaml", "config/prompts/*.md"],
        "models": {a: {"model": s.model_for(a),
                       "source": "per-agent override" if s.raw["model"].get(a)
                       else ("SOLSTICE_MODEL env" if env_model else "default")} for a in AGENTS},
        "max_tokens": s.max_tokens,
        "max_tool_rounds": s.max_tool_rounds,
        "demo_today": s.today.isoformat(),
        "demo_today_pinned": bool(s.raw.get("demo_today")),
        "latency_target_s": s.latency_target_s,
        "group_latency_target_s": s.latency_target_for("group_sales"),
        "access": {"staff_pin": s.pin_source("staff"), "admin_pin": s.pin_source("admin"),
                   "open_access": open_access.status(),
                   "max_failed_verifications": s.max_failed_verifications},
        "group_rules": {
            "global": rules.get("global", {}),
            "seasonal_caps": [{"property": c["property"], "cap_pct": c["cap_pct"], "months": c["months"]}
                              for c in rules.get("seasonal_discount_caps", [])],
            "property_rules": [{"property": r["property"], "type": r["type"]} for r in rules.get("property_rules", [])],
        },
    }


def tools_summary() -> dict:
    from solstice.tools.registry import tools_for
    return {f"{a}/{m}": [{"name": t.name, "description": t.description} for t in tools_for(a, m)]
            for a, m in (("concierge", "guest"), ("concierge", "staff"), ("group_sales", "staff"))}


def data_quality_list() -> list[dict]:
    from solstice.data.store import get_store
    order = ("error", "warning", "info")
    return [{"severity": i.severity, "record_id": i.record_id, "field": i.field, "problem": i.problem,
             "agent_handling": i.agent_handling}
            for i in sorted(get_store().data_issues, key=lambda i: order.index(i.severity))]


# ---------------- 1. settings ----------------

def show_settings() -> None:
    import yaml
    s = get_settings()
    _h("Agent settings  (edit: config/settings.yaml)")
    env_model = os.getenv("SOLSTICE_MODEL")
    for agent in AGENTS:
        override = s.raw["model"].get(agent)
        src = "per-agent override" if override else ("SOLSTICE_MODEL env" if env_model else "default")
        print(f"  {'model (' + agent + '):':<25}{s.model_for(agent)}  {DIM}[{src}]{RESET}")
    print(f"  max_tokens per reply:    {s.max_tokens}")
    print(f"  max tool rounds / turn:  {s.max_tool_rounds}")
    print(f"  demo 'today':            {s.today.isoformat()}  {DIM}[{'pinned' if s.raw.get('demo_today') else 'real date'}]{RESET}")
    print(f"  latency target (p95):    {s.latency_target_s}s")

    _h("Access")
    print(f"  staff PIN:               set  {DIM}[{s.pin_source('staff')}]{RESET}")
    print(f"  admin PIN:               set  {DIM}[{s.pin_source('admin')}]{RESET}")
    print(f"  failed verifications:    lock after {s.max_failed_verifications} per chat")

    _h("Group rules  (edit: config/group_rules.yaml)")
    with open(s.path("group_rules"), encoding="utf-8") as f:
        rules = yaml.safe_load(f)
    for k, v in rules.get("global", {}).items():
        print(f"  {k}: {v}")
    for c in rules.get("seasonal_discount_caps", []):
        print(f"  seasonal cap {c['property']}: {c['cap_pct']}% in months {c['months']}")
    print(f"  property rules: {len(rules.get('property_rules', []))} "
          f"({', '.join(r['property'] + ':' + r['type'] for r in rules.get('property_rules', []))})")


# ---------------- 2. health ----------------

def _check_api(models: set[str]) -> list[tuple[str, str, str]]:
    """Free check: looks up each configured model (no tokens used)."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return [("FAIL", "API key", "ANTHROPIC_API_KEY not set (add it to .env)")]
    import anthropic
    out = [("OK", "API key", "set (value hidden)")]
    try:
        client = anthropic.Anthropic(max_retries=0, timeout=10.0)
        for m in sorted(models):
            try:
                client.models.retrieve(m)
                out.append(("OK", f"model {m}", "reachable"))
            except anthropic.NotFoundError:
                out.append(("FAIL", f"model {m}", "not found: check the model ID"))
    except anthropic.AuthenticationError:
        out.append(("FAIL", "API", "key rejected (401)"))
    except anthropic.PermissionDeniedError:
        out.append(("FAIL", "API", "key lacks permission (403)"))
    except anthropic.APIConnectionError:
        out.append(("FAIL", "API", "cannot reach api.anthropic.com (network)"))
    except anthropic.APIStatusError as e:
        out.append(("WARN", "API", f"HTTP {e.status_code}"))
    return out


def health_checks(check_api: bool = True) -> list[tuple[str, str, str]]:
    s = get_settings()
    checks: list[tuple[str, str, str]] = []

    if check_api:
        checks += _check_api({s.model_for(a) for a in AGENTS})

    # Data files load and parse
    try:
        from solstice.data.store import get_store
        st = get_store()
        checks.append(("OK", "data", f"{len(st.properties)} properties, {len(st.reservations)} reservations, "
                                     f"{len(st.inquiries)} inquiries"))
        sev = Counter(i.severity for i in st.data_issues)
        status = "WARN" if sev.get("error") else "OK"
        checks.append((status, "data quality", f"{sev.get('error', 0)} errors, {sev.get('warning', 0)} warnings, "
                                               f"{sev.get('info', 0)} info (agent works around them)"))
    except Exception as e:  # noqa: BLE001 - show any load failure to the admin
        checks.append(("FAIL", "data", f"failed to load: {type(e).__name__}: {e}"))

    # Prompts and policy present
    pdir = s.path("prompts_dir")
    missing = [f for f in PROMPT_FILES if not (pdir / f).is_file()]
    checks.append(("FAIL", "prompts", f"missing {missing}") if missing else ("OK", "prompts", f"{len(PROMPT_FILES)} files in {_rel(pdir)}"))
    pol = s.path("policy_doc")
    checks.append(("OK", "policy doc", _rel(pol)) if pol.is_file() else ("FAIL", "policy doc", f"missing {_rel(pol)}"))

    # Runtime folder writable
    try:
        d = s.path("runtime_dir")
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        checks.append(("OK", "runtime folder", f"{_rel(d)} writable"))
    except OSError as e:
        checks.append(("FAIL", "runtime folder", str(e)))

    # Tools registered for every agent/mode
    from solstice.tools.registry import tools_for
    for agent, mode in (("concierge", "guest"), ("concierge", "staff"), ("group_sales", "staff")):
        n = len(tools_for(agent, mode))
        checks.append(("OK" if n else "FAIL", f"tools {agent}/{mode}", f"{n} tools"))

    # Demo PINs are fine for the demo, never for real use
    for role in ("staff", "admin"):
        if not os.getenv(f"SOLSTICE_{role.upper()}_PIN"):
            checks.append(("WARN", f"{role} PIN", "demo value from settings.yaml (see docs/ACCESS_CONTROL.md)"))
    return checks


def show_health() -> None:
    _h("Health checks")
    print(f"{DIM}  (API check looks up the configured models; it uses no tokens){RESET}")
    for status, name, detail in health_checks():
        print(f"  {MARK[status]}  {name:<24} {detail}")


# ---------------- 3. tools ----------------

def show_tools() -> None:
    from solstice.tools.registry import tools_for
    for agent, mode in (("concierge", "guest"), ("concierge", "staff"), ("group_sales", "staff")):
        _h(f"Tools: {agent} / {mode}")
        for t in tools_for(agent, mode):
            print(f"  {t.name:<36} {DIM}{t.description[:70]}{RESET}")


# ---------------- 4. activity ----------------

def _p95(xs: list[float]) -> float:
    xs = sorted(xs)
    return xs[max(0, int(round(0.95 * len(xs))) - 1)] if xs else 0.0


def activity_summary() -> dict:
    s = get_settings()
    traces = runtime_store.read_all("traces")
    audit = runtime_store.read_all("audit")
    # Latency is judged per target: live chat (concierge) vs. back-office group sales.
    lat = [t["latency_s"] for t in traces if t.get("agent") != "group_sales"]
    lat_g = [t["latency_s"] for t in traces if t.get("agent") == "group_sales"]
    target_g = s.latency_target_for("group_sales")
    tool_calls = [tc for t in traces for tc in t.get("tools", [])]
    pins = [e for e in audit if e["event"] == "pin"]
    return {
        "turns": len(traces),
        "by_agent_mode": dict(Counter(f"{t['agent']}/{t['mode']}" for t in traces)),
        "avg_latency_s": round(sum(lat) / len(lat), 2) if lat else 0.0,
        "p95_latency_s": _p95(lat),
        "within_target_pct": round(100 * sum(x <= s.latency_target_s for x in lat) / len(lat)) if lat else 100,
        "group_turns": len(lat_g),
        "group_p95_latency_s": _p95(lat_g),
        "group_latency_target_s": target_g,
        "group_within_target_pct": round(100 * sum(x <= target_g for x in lat_g) / len(lat_g)) if lat_g else 100,
        "tokens_in": sum(t.get("input_tokens", 0) for t in traces),
        "tokens_out": sum(t.get("output_tokens", 0) for t in traces),
        "tool_calls": len(tool_calls),
        "tool_errors": sum(not tc["ok"] for tc in tool_calls),
        "escalations": len(runtime_store.read_all("tickets")),
        "service_requests": len(runtime_store.read_all("requests")),
        "proposals": len(runtime_store.read_all("proposals")),
        "failed_verifications": sum(e["event"] == "verification_failed" for e in audit),
        "pin_failures": dict(Counter(e.get("role", "staff") for e in pins if not e["ok"])),
        "limit_hits": dict(Counter(e["kind"] for e in audit if e["event"] == "limit_hit")),
        "model_unavailable": sum(e["event"] == "model_unavailable" for e in audit),
    }


def show_activity() -> None:
    a = activity_summary()
    s = get_settings()
    _h("Activity  (from data/runtime/*.jsonl)")
    print(f"  conversation turns:      {a['turns']}  {DIM}{a['by_agent_mode']}{RESET}")
    print(f"  chat latency avg / p95:  {a['avg_latency_s']}s / {a['p95_latency_s']}s  "
          f"(target {s.latency_target_s}s, {a['within_target_pct']}% within)")
    print(f"  group sales p95:         {a['group_p95_latency_s']}s  "
          f"(target {a['group_latency_target_s']}s, {a['group_within_target_pct']}% within, {a['group_turns']} turns)")
    print(f"  tokens in / out:         {a['tokens_in']:,} / {a['tokens_out']:,}")
    print(f"  tool calls (errors):     {a['tool_calls']} ({a['tool_errors']})")
    print(f"  escalations to staff:    {a['escalations']}")
    print(f"  service requests:        {a['service_requests']}")
    print(f"  group proposals:         {a['proposals']}")
    print(f"  failed verifications:    {a['failed_verifications']}")
    print(f"  failed PIN attempts:     {a['pin_failures'] or 0}")


# ---------------- 5. data quality ----------------

def show_data_quality() -> None:
    from solstice.data.store import get_store
    issues = get_store().data_issues
    _h(f"Data quality issues ({len(issues)})  (rules: backend/solstice/data/quality.py)")
    for i in sorted(issues, key=lambda i: ("error", "warning", "info").index(i.severity)):
        print(f"  {i.severity:<7} {i.record_id:<10} {i.field:<20} {DIM}{i.problem[:70]}{RESET}")


MENU = {
    "1": ("Agent settings and config", show_settings),
    "2": ("Health checks", show_health),
    "3": ("Tools by agent and mode", show_tools),
    "4": ("Activity (latency, tokens, escalations)", show_activity),
    "5": ("Data quality issues", show_data_quality),
}


def run() -> None:
    print(f"\n{BOLD}Solstice admin console{RESET}  {DIM}(read-only; edit the YAML files to change settings){RESET}")
    while True:
        print()
        for k, (label, _) in MENU.items():
            print(f"  {k}. {label}")
        print("  q. Back to main menu")
        try:
            choice = input("admin> ").strip().lstrip("﻿").lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if choice in ("q", "quit", "exit", "menu", "back"):
            return
        if choice in MENU:
            MENU[choice][1]()
        else:
            print("Enter 1-5 or q.")
