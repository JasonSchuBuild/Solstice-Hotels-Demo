"""Writes docs/TOOLS.md from the tool registry, so the tool definitions doc can't drift from the code.

    cd backend
    .\\.venv\\Scripts\\python.exe ..\\docs\\build_tools_doc.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from solstice.tools.registry import TOOLS, tools_for  # noqa: E402

tools_for("concierge", "guest")  # imports every tool module so the registry is complete

VIEWS = [("concierge", "guest", "Guest"), ("concierge", "staff", "Front desk"), ("group_sales", "staff", "Group sales")]
SOURCES = {
    "concierge_tools": "backend/solstice/tools/concierge_tools.py",
    "group_tools": "backend/solstice/tools/group_tools.py",
    "escalation": "backend/solstice/tools/escalation.py",
    "data_quality_tools": "backend/solstice/tools/data_quality_tools.py",
}


def main():
    lines = ["# Tool definitions", "",
             "Generated from the code by `docs/build_tools_doc.py`; don't edit by hand.", "",
             "Each tool is a JSON schema the model sees plus a Python handler that does the work. "
             "Which tools a session gets is decided in code by agent and mode (`tools_for` in "
             "`backend/solstice/tools/registry.py`), so nothing typed in a chat can unlock a tool.", "",
             "## Access by mode", "",
             "| Tool | " + " | ".join(v[2] for v in VIEWS) + " |",
             "|---|" + "---|" * len(VIEWS)]
    for name in sorted(TOOLS):
        marks = ["✅" if name in {t.name for t in tools_for(a, m)} else "" for a, m, _ in VIEWS]
        lines.append(f"| `{name}` | " + " | ".join(marks) + " |")
    lines += ["", "## Definitions", ""]
    for name in sorted(TOOLS):
        t = TOOLS[name]
        src = SOURCES.get(t.handler.__module__.rsplit(".", 1)[-1], t.handler.__module__)
        lines += [f"### `{name}`", "", t.description, "",
                  f"**Agents:** {', '.join(t.agents)} · **Modes:** {', '.join(t.modes)} · **Code:** `{src}`", ""]
        props, req = t.input_schema.get("properties", {}), set(t.input_schema.get("required", []))
        if props:
            lines += ["| Parameter | Type | Required | Description |", "|---|---|---|---|"]
            for p, spec in props.items():
                typ = spec.get("type", "")
                if "enum" in spec:
                    typ += " (one of: " + ", ".join(spec["enum"]) + ")"
                if typ == "array" and "items" in spec:
                    typ = f"array of {spec['items'].get('type', '')}"
                lines.append(f"| `{p}` | {typ} | {'yes' if p in req else ''} | {spec.get('description', '')} |")
            lines.append("")
        else:
            lines += ["No parameters.", ""]
    out = ROOT / "docs" / "TOOLS.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("wrote", out, f"({len(TOOLS)} tools)")


if __name__ == "__main__":
    main()
