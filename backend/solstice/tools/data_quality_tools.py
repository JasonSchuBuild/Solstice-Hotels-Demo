"""On-demand data quality report for staff and sales ("any data issues at Providence?")."""
from __future__ import annotations

from solstice import runtime_store
from solstice.data.quality import report
from solstice.data.store import get_store
from solstice.tools.registry import ToolContext, tool


@tool("get_data_quality_report",
      "Staff/Sales only: list known problems in the source data (invalid rates, inconsistent dates, incomplete "
      "inquiries), with severity and how the agent handles each, plus alerts raised when the agent hit bad data.",
      {"property_code": {"type": "string", "description": "Optional, e.g. SOL-PVD. Omit for all properties."}},
      agents=("concierge", "group_sales"), modes=("staff",))
def get_data_quality_report(ctx: ToolContext, property_code: str | None = None) -> dict:
    out = report(get_store().data_issues, property_code)
    alerts = runtime_store.read_all("alerts")
    if property_code:
        ids = {i["issue_id"] for i in out["issues"]}
        alerts = [a for a in alerts if a["issue_id"] in ids]
    out["recent_alerts"] = alerts[-10:]
    return out
