"""Chat with an agent from the terminal.

    python -m solstice.cli                        # menu: pick guest, front desk, or group sales
    python -m solstice.cli concierge              # as a guest
    python -m solstice.cli concierge --staff      # as a front-desk associate (PIN required)
    python -m solstice.cli group_sales            # group sales assistant (PIN required)
    python -m solstice.cli admin                  # admin console: settings, health, activity (admin PIN)
    python -m solstice.cli concierge --model claude-sonnet-5-5

Staff modes ask for the staff PIN, admin for the admin PIN (config/settings.yaml -> access).
"""
from __future__ import annotations

import argparse
import getpass
import hmac
import json
import sys

from solstice.agent.runner import AgentSession
from solstice import runtime_store
from solstice.config import get_settings

DIM, RESET, BOLD = "\033[2m", "\033[0m", "\033[1m"

# Menu choice -> (agent, mode)
MENU = {
    "1": ("concierge", "guest", "Guest: chat with the concierge"),
    "2": ("concierge", "staff", "Front desk staff: concierge with staff tools (PIN)"),
    "3": ("group_sales", "staff", "Group sales: work up group proposals (PIN)"),
    "4": ("admin", "admin", "Admin: agent settings, health, activity (admin PIN)"),
}
MAX_PIN_ATTEMPTS = 3

# App commands, handled here and never sent to the agent.
CHAT_HELP = (f"\n{BOLD}Commands{RESET}\n"
             "  menu     back to the main mode choices (also: back)\n"
             "  help     this list, plus what the agent can help with\n"
             "  ?        this list only\n"
             "  Ctrl+C   quit\n"
             "Anything else you type goes to the agent.\n")


def choose_from_menu() -> tuple[str, str] | None:
    """Returns (agent, mode), or None if the user quits."""
    print(f"{BOLD}Solstice Hotel Group — choose a mode{RESET}")
    for key, (_, _, label) in MENU.items():
        print(f"  {key}. {label}")
    print("  q. Quit")
    while True:
        choice = input("mode> ").strip().lstrip("﻿").lower()  # PowerShell pipes add a BOM
        if choice in ("q", "quit", "exit"):
            return None
        if choice in MENU:
            agent, mode, _ = MENU[choice]
            return agent, mode
        print(f"Enter {', '.join(MENU)} or q.")


def pin_ok(role: str) -> bool:
    """role: staff | admin. Hidden input, 3 attempts, every attempt audited (never the PIN itself)."""
    expected = get_settings().pin_for(role)
    for attempt in range(1, MAX_PIN_ATTEMPTS + 1):
        entered = getpass.getpass(f"{role.capitalize()} PIN: ")
        ok = hmac.compare_digest(entered.strip(), expected)
        runtime_store.append("audit", {"event": "pin", "role": role, "ok": ok, "attempt": attempt})
        if ok:
            return True
        left = MAX_PIN_ATTEMPTS - attempt
        print(f"Incorrect PIN.{f' {left} attempt(s) left.' if left else ''}")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("agent", nargs="?", choices=["concierge", "group_sales", "admin"],
                    help="skip the menu and start this agent directly")
    ap.add_argument("--staff", action="store_true", help="staff mode (concierge only)")
    ap.add_argument("--model", help="override model, e.g. claude-sonnet-5-5")
    ap.add_argument("--trace", action="store_true", help="print full tool inputs/outputs")
    a = ap.parse_args()

    first = True
    while True:
        try:
            if first and a.agent:
                agent = a.agent
                mode = "admin" if agent == "admin" else ("staff" if (a.staff or agent == "group_sales") else "guest")
            else:
                picked = choose_from_menu()
                if picked is None:
                    return
                agent, mode = picked
            first = False
            # Mode is fixed for the whole session; tools are filtered by it in code
            # (tools/registry.py), so nothing typed in the chat can unlock staff tools.
            if mode in ("staff", "admin") and not pin_ok(mode):
                print(f"{mode.capitalize()} access denied.\n")
                continue
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(1)

        if mode == "admin":
            from solstice import admin
            admin.run()
        elif chat(agent, mode, a) == "quit":
            return
        print()


def chat(agent: str, mode: str, a) -> str:
    """One chat session. Returns "menu" (user typed menu) or "quit" (Ctrl+C / end of input).
    A new session starts fresh: switching modes never carries over verification or history."""
    sess = AgentSession(agent, mode, model=a.model)
    print(f"\n{BOLD}Solstice {agent} ({mode}) — model {sess.model}{RESET}  "
          f"{DIM}(type 'help' for commands, 'menu' to switch modes){RESET}")
    if mode == "staff":
        from solstice.data.store import get_store
        issues = get_store().data_issues
        errs = sum(1 for i in issues if i.severity == "error")
        print(f"{DIM}  ⚠ {len(issues)} data quality issues loaded ({errs} errors). Ask: \"any data issues?\"{RESET}")
    print()
    while True:
        try:
            msg = input(f"{BOLD}you>{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return "quit"
        if not msg:
            continue
        cmd = msg.lower().lstrip("/")
        if cmd in ("menu", "back"):
            return "menu"
        if cmd in ("help", "?", "commands"):
            # Show the app's own commands, then let the agent answer too: it describes what it can do
            # in this mode (guest / staff / group sales), so the list never drifts from its tools.
            print(CHAT_HELP)
            if cmd != "help":
                continue
        r = sess.send(msg)
        for st in r.steps:
            status = "ok" if st.ok else "ERROR"
            print(f"{DIM}  ↳ {st.tool}({json.dumps(st.input)}) {status} {st.ms}ms{RESET}")
            if a.trace:
                print(f"{DIM}    {json.dumps(st.output, default=str)[:800]}{RESET}")
        flag = "" if r.within_latency_target else "  ⚠ over latency target"
        print(f"\n{BOLD}agent>{RESET} {r.text}\n{DIM}  [{r.latency_s}s · {r.input_tokens}+{r.output_tokens} tokens]{flag}{RESET}\n")


if __name__ == "__main__":
    main()
