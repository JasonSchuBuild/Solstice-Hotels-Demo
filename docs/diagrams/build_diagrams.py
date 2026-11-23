"""Builds the architecture diagrams as SVG (works in GitHub, browsers and PowerPoint).

    python docs/diagrams/build_diagrams.py

Writes architecture-future.svg (production design) and architecture-current.svg
(what's deployed for the demo). Edit the text or boxes below and re-run.
"""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).parent
FONT = "Segoe UI, Inter, Helvetica, Arial, sans-serif"
NAVY, AMBER, INK, MUTED = "#14213d", "#f2a541", "#1b1f2a", "#5d6475"

ZONES = {  # fill, stroke
    "users": ("#f6f4ef", "#c9c3b4"),
    "edge": ("#eef3fb", "#9fb3d6"),
    "app": ("#fff7ea", "#e8b86a"),
    "model": ("#f3eefb", "#b39ddb"),
    "integ": ("#edf7f1", "#8cc7a3"),
    "hotel": ("#f3f4f6", "#b5bac4"),
    "ops": ("#eef1f5", "#a7b0bf"),
}


class Svg:
    def __init__(self, w: int, h: int):
        self.w, self.h, self.parts = w, h, []

    def add(self, s: str):
        self.parts.append(s)

    def text(self, x, y, s, size=13, weight=400, color=INK, anchor="start", italic=False):
        style = ' font-style="italic"' if italic else ""
        self.add(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{color}" '
                 f'text-anchor="{anchor}"{style}>{escape(s)}</text>')

    def zone(self, x, y, w, h, label, kind):
        fill, stroke = ZONES[kind]
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
        self.text(x + 16, y + 26, label.upper(), size=12, weight=700, color=MUTED)

    def box(self, x, y, w, h, title, lines=(), kind="app", accent=False, tag=None):
        _, stroke = ZONES[kind]
        sw = 2.5 if accent else 1.5
        sc = AMBER if accent else stroke
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="#ffffff" stroke="{sc}" stroke-width="{sw}"/>')
        self.text(x + 14, y + 24, title, size=15, weight=700, color=NAVY)
        for i, line in enumerate(lines):
            self.text(x + 14, y + 44 + i * 17, line, size=12.5, color=MUTED)
        if tag:
            tw = 9 + 6.6 * len(tag)
            self.add(f'<rect x="{x + w - tw - 10}" y="{y + 10}" width="{tw}" height="20" rx="10" fill="{AMBER}"/>')
            self.text(x + w - tw / 2 - 10, y + 24, tag, size=11, weight=700, color=NAVY, anchor="middle")

    def arrow(self, pts, label=None, style="solid", color=NAVY, label_at=None, label_anchor="middle"):
        dash = {"solid": "", "dashed": ' stroke-dasharray="7 5"', "dotted": ' stroke-dasharray="2 5"'}[style]
        d = "M " + " L ".join(f"{x} {y}" for x, y in pts)
        marker = "arrow-red" if color != NAVY else "arrow"
        self.add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.8"{dash} marker-end="url(#{marker})"/>')
        if label:
            lx, ly = label_at or ((pts[0][0] + pts[-1][0]) / 2, (pts[0][1] + pts[-1][1]) / 2 - 7)
            self.add(f'<text x="{lx}" y="{ly}" font-size="12" fill="{color}" text-anchor="{label_anchor}" '
                     f'paint-order="stroke" stroke="#ffffff" stroke-width="4">{escape(label)}</text>')

    def badge(self, x, y, n, color="#c0392b"):
        self.add(f'<circle cx="{x}" cy="{y}" r="11" fill="{color}"/>')
        self.text(x, y + 4.5, str(n), size=12, weight=700, color="#ffffff", anchor="middle")

    def render(self, title, subtitle) -> str:
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
                f'viewBox="0 0 {self.w} {self.h}" font-family="{FONT}">'
                '<defs>'
                f'<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="{NAVY}"/></marker>'
                '<marker id="arrow-red" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="#c0392b"/></marker>'
                '</defs>'
                f'<rect width="{self.w}" height="{self.h}" fill="#ffffff"/>'
                f'<rect width="{self.w}" height="6" fill="{AMBER}"/>')
        t = (f'<text x="30" y="46" font-size="24" font-weight="700" fill="{NAVY}">{escape(title)}</text>'
             f'<text x="30" y="72" font-size="14" fill="{MUTED}">{escape(subtitle)}</text>')
        return head + t + "".join(self.parts) + "</svg>\n"


# ---------------------------------------------------------------- future state

def future() -> str:
    s = Svg(1760, 1060)

    # Users
    s.zone(30, 100, 210, 640, "Users", "users")
    s.box(45, 140, 180, 95, "Guests", ["Hotel website / app", "Mobile, any device"], "users")
    s.box(45, 265, 180, 95, "Front desk", ["Lookups, requests,", "comps, escalations"], "users")
    s.box(45, 390, 180, 95, "Group sales", ["Inquiries, proposals,", "approvals"], "users")
    s.box(45, 515, 180, 95, "IT / Admins", ["Health, settings,", "cost, audit"], "users")

    # Edge + identity
    s.zone(265, 100, 225, 640, "Edge & identity", "edge")
    s.box(280, 160, 195, 150, "Azure Front Door", ["+ Web Application", "Firewall", "TLS, rate limits,", "bot protection"], "edge")
    s.box(280, 400, 195, 170, "Microsoft Entra ID", ["Staff: SSO + MFA", "Roles: front desk,", "sales, GM, admin", "Guests: app / loyalty", "login or chat check"], "edge")

    # App
    s.zone(515, 100, 440, 640, "Azure Container Apps · 2 regions", "app")
    s.box(530, 140, 410, 75, "Web app", ["Guest chat · Staff console · Admin dashboard"], "app")
    s.box(530, 230, 410, 95, "Agent service", ["Agent loop · tools filtered by role", "Prompts & rules from versioned config"], "app", accent=True)
    s.box(530, 340, 200, 120, "Rules engine", ["Pricing, approvals,", "policy date math", "Deterministic code,", "not the model"], "app")
    s.box(740, 340, 200, 120, "PII masking", ["Card data never", "leaves the source", "Names masked in", "logs & tickets"], "app")
    s.box(530, 475, 410, 80, "Guardrails", ["Scope & injection rules · verification lockout", "Rate limits · daily token budget · history cap"], "app")
    s.box(530, 570, 200, 95, "Session store", ["Azure Cache for", "Redis (shared state)"], "app")
    s.box(740, 570, 200, 95, "Event log", ["Tickets, proposals,", "audit (database)"], "app")
    s.text(530, 700, "Scales out on demand; any replica can serve any session.", size=12, color=MUTED, italic=True)

    # Models
    s.zone(980, 100, 330, 340, "AI model (graceful fallback)", "model")
    s.box(995, 140, 300, 95, "Claude in Microsoft Foundry", ["Primary · Haiku 5.5, hosted on Azure", "US data zone · Entra ID auth, no key"], "model", tag="PRIMARY")
    s.box(995, 265, 300, 70, "Anthropic API", ["Fallback · same API, key in Key Vault"], "model")
    s.box(995, 360, 300, 65, "Staff handoff", ["Last resort: ticket with full transcript"], "model")
    s.arrow([(1145, 235), (1145, 263)], style="dashed", color="#c0392b")
    s.arrow([(1145, 335), (1145, 358)], style="dashed", color="#c0392b")
    s.badge(1170, 250, 1)
    s.badge(1170, 347, 2)

    # Integration
    s.zone(980, 460, 330, 280, "Integration layer", "integ")
    s.box(995, 500, 300, 95, "Azure API Management", ["One contract per hotel system", "Read-only first · throttling · auth"], "integ")
    s.box(995, 615, 300, 105, "Read cache", ["Last-known rates & availability", "Stale data marked 'to confirm'", "if a system is down"], "integ")
    s.badge(1280, 630, 3)

    # Hotel systems
    s.zone(1335, 100, 395, 640, "Hotel systems (sources of truth)", "hotel")
    s.box(1350, 140, 365, 95, "PMS · property management", ["Reservations, rooms, folios, check-out", "Late checkout & request fulfilment"], "hotel")
    s.box(1350, 250, 365, 95, "CRS · central reservations", ["Rates, inventory, group blocks", "Availability across 140 properties"], "hotel")
    s.box(1350, 360, 365, 95, "Loyalty / CRM", ["Tier, points, preferences", "Guest identity for app login"], "hotel")
    s.box(1350, 470, 365, 95, "Service desk / Microsoft Teams", ["Escalation tickets routed by policy", "Manager on duty, GM, security"], "hotel")
    s.box(1350, 580, 365, 95, "Policy & property content", ["Policies, fact sheets, amenities", "SharePoint / Blob, versioned"], "hotel")

    # Request path: everyone (guests and staff) comes in through Front Door
    for y in (175, 300, 425, 550):
        s.add(f'<path d="M 225 {y} L 250 {y}" fill="none" stroke="{NAVY}" stroke-width="1.8"/>')
    s.add(f'<path d="M 250 175 L 250 550" fill="none" stroke="{NAVY}" stroke-width="1.8"/>')
    s.arrow([(250, 235), (278, 235)])
    # Every staff role signs in with Entra ID (SSO + MFA); guests don't
    s.arrow([(225, 335), (278, 440)])
    s.arrow([(225, 460), (278, 485)])
    s.arrow([(225, 585), (278, 530)])
    s.text(290, 392, "staff sign-in (SSO + MFA)", size=12, color=NAVY)
    s.arrow([(475, 235), (528, 177)], label="HTTPS", label_at=(498, 196))
    s.arrow([(475, 485), (500, 485), (500, 268), (528, 268)], label="role claims", label_at=(494, 345), label_anchor="end")
    s.arrow([(940, 260), (993, 190)], label="model calls", label_at=(962, 210))
    s.arrow([(940, 400), (965, 400), (965, 548), (993, 548)], label="tool calls", label_at=(972, 453), label_anchor="start")
    s.arrow([(1295, 548), (1348, 300)])
    s.arrow([(1295, 548), (1348, 410)])
    s.arrow([(1295, 548), (1348, 518)], label="read / write", label_at=(1322, 590))
    s.arrow([(1295, 548), (1348, 628)])

    # Operations band
    s.zone(30, 775, 1700, 200, "Operations · security · monitoring", "ops")
    ops = [
        ("Application Insights", ["Traces, latency vs 6 s p95,", "errors, tokens per turn"]),
        ("Azure Monitor alerts", ["Errors, latency, fallback", "rate, escalation spikes"]),
        ("Key Vault + identity", ["Managed identity everywhere", "No secrets in code or images"]),
        ("Cost Management", ["Budgets & alerts, model", "cost by usage type"]),
        ("Data quality alerts", ["Bad source data flagged to", "the data owner, not guests"]),
        ("CI/CD (Bicep)", ["Tests + evals on every", "change; reviewed releases"]),
    ]
    for i, (t, lines) in enumerate(ops):
        s.box(45 + i * 280, 820, 265, 120, t, lines, "ops")
    s.arrow([(735, 740), (735, 815)], label="telemetry from every component", style="dotted", label_at=(745, 765), label_anchor="start")

    # Legend
    y = 1012
    s.add(f'<path d="M 30 {y} L 70 {y}" stroke="{NAVY}" stroke-width="1.8" marker-end="url(#arrow)"/>')
    s.text(78, y + 4, "request path", size=12, color=MUTED)
    s.add(f'<path d="M 190 {y} L 230 {y}" stroke="#c0392b" stroke-width="1.8" stroke-dasharray="7 5" marker-end="url(#arrow-red)"/>')
    s.text(238, y + 4, "fallback", size=12, color=MUTED)
    s.add(f'<path d="M 320 {y} L 360 {y}" stroke="{NAVY}" stroke-width="1.8" stroke-dasharray="2 5" marker-end="url(#arrow)"/>')
    s.text(368, y + 4, "telemetry", size=12, color=MUTED)
    s.badge(470, y, 1)
    s.text(488, y + 4, "Foundry down: Anthropic API", size=12, color=MUTED)
    s.badge(700, y, 2)
    s.text(718, y + 4, "No model: staff ticket, never a dead end", size=12, color=MUTED)
    s.badge(1000, y, 3)
    s.text(1018, y + 4, "Hotel system down: cached data marked 'to confirm', rules engine still works", size=12, color=MUTED)

    return s.render("Solstice AI Concierge & Group Sales · Production architecture",
                    "Future state: where data comes from, where the agent runs, how it's monitored, and how it degrades")


# ---------------------------------------------------------------- current demo

def current() -> str:
    s = Svg(1440, 835)

    s.zone(30, 100, 200, 630, "Users", "users")
    s.box(45, 150, 170, 90, "Guest", ["Browser", "/  (no login)"], "users")
    s.box(45, 270, 170, 90, "Staff", ["/staff", "demo PIN"], "users")
    s.box(45, 390, 170, 90, "Admin", ["/admin", "demo PIN"], "users")

    s.zone(260, 100, 840, 630, "Azure · resource group rg-solstice-demo · East US 2", "edge")
    s.zone(280, 140, 500, 570, "Container App · FastAPI · 0–1 replicas", "app")
    s.box(295, 185, 470, 60, "Web pages", ["Guest chat · Staff console with tool trace · Admin dashboard · 3 themes"], "app")
    s.box(295, 260, 230, 95, "Agent loop + tools", ["Tools filtered by mode", "Prompts from config/*.md"], "app", accent=True)
    s.box(535, 260, 230, 95, "Rules engine", ["Pricing, approvals,", "policy dates (Python)"], "app")
    s.box(295, 370, 230, 95, "PII masking", ["Cards never leave", "the data store"], "app")
    s.box(535, 370, 230, 95, "Guardrails", ["Rate limits, token budget,", "history cap, lockouts"], "app")
    s.box(295, 480, 230, 100, "Sample data", ["CSV + policy .md", "in the image,", "validated at start"], "app")
    s.box(535, 480, 230, 100, "Runtime logs", ["Tickets, traces, audit", "(JSONL, reset on", "restart)"], "app")
    s.box(295, 595, 470, 95, "Scale rules", ["Scale to zero when idle; one replica (sessions in memory)", "Cron warm windows 6am–6pm ET for demo season"], "app")

    s.box(810, 150, 270, 85, "Key Vault", ["anthropic-api-key", "read by managed identity"], "edge")
    s.box(810, 255, 270, 85, "Managed identity", ["Pulls image, reads secret,", "writes settings; no keys in code"], "edge")
    s.box(810, 360, 270, 85, "Container Registry", ["solstice-web image", "built in Azure (az acr build)"], "edge")
    s.box(810, 465, 270, 110, "Log Analytics", ["Container logs, probes,", "/healthz liveness; App", "Insights ready (next step)"], "edge")
    s.box(810, 590, 270, 100, "Blob Storage", ["Admin settings: theme,", "demo open access", "Managed identity, no keys"], "edge")

    s.zone(1130, 100, 280, 630, "Outside Azure", "model")
    s.box(1145, 150, 250, 115, "Anthropic API", ["Claude Haiku 5.5", "Demo workspace with a", "monthly spend limit"], "model", tag="MODEL")
    s.box(1145, 300, 250, 100, "If the model fails", ["(or runs out of steps): user", "told it's passed on; staff", "ticket with the transcript"], "model")
    s.box(1145, 435, 250, 140, "Cost guardrails", ["Anthropic workspace limit", "Azure budget: $25/month", "with email alerts", "In-app daily token budget"], "model")

    s.arrow([(215, 195), (293, 215)], label="HTTPS", label_at=(255, 196))
    s.arrow([(215, 315), (250, 315), (250, 230), (293, 230)])
    s.arrow([(215, 435), (250, 435), (250, 230)])
    s.arrow([(765, 300), (790, 300), (790, 128), (1112, 128), (1112, 200), (1143, 200)],
            label="model calls (HTTPS, key from Key Vault)", label_at=(950, 121))
    s.arrow([(945, 255), (945, 237)], style="dotted")
    s.arrow([(808, 402), (780, 402)], label="image", label_at=(795, 395))
    s.arrow([(780, 540), (808, 540)], label="logs", style="dotted", label_at=(795, 532))
    s.arrow([(1270, 265), (1270, 298)], style="dashed", color="#c0392b")
    s.arrow([(780, 640), (808, 640)], label="settings", label_at=(795, 632))

    y = 790
    s.text(30, y, "Production adds (see future-state diagram): Entra ID sign-in instead of PINs · Claude in Microsoft Foundry with API fallback · "
                  "live PMS / CRS / loyalty feeds", size=13, color=MUTED)
    s.text(30, y + 22, "through API Management · shared session store and database · Front Door rate limiting · alerts and dashboards.",
           size=13, color=MUTED)

    return s.render("Solstice AI Concierge & Group Sales · Demo as deployed",
                    "Running today on Azure Container Apps; every box below exists and can be opened in the Azure portal")


if __name__ == "__main__":
    (OUT / "architecture-future.svg").write_text(future(), encoding="utf-8")
    (OUT / "architecture-current.svg").write_text(current(), encoding="utf-8")
    print("wrote", OUT / "architecture-future.svg")
    print("wrote", OUT / "architecture-current.svg")
