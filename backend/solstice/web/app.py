"""Web app: the guest chat page, the staff console and the admin dashboard.

    cd backend
    .\\.venv\\Scripts\\python.exe -m uvicorn solstice.web.app:app --port 8000
    open http://localhost:8000          (guest)
         http://localhost:8000/staff    (front desk + group sales, staff PIN)
         http://localhost:8000/admin    (admin PIN)

The browser only ever holds a session token. Which agent, which mode and which
tools a session gets are decided here when the session is created, never by the page.
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from solstice import admin, open_access, runtime_store, themes
from solstice.agent.runner import AgentSession
from solstice.config import get_settings
from solstice.web.limits import LimitExceeded, UsageLimiter
from solstice.web.sessions import VIEWS, SessionStore

log = logging.getLogger("solstice.web")
STATIC = Path(__file__).parent / "static"

def warm_up() -> None:
    """Do the slow first-time work before the first guest arrives: load and check the data, build the
    prompts, open the model client and fetch the managed-identity token for the settings store. Each step is
    best-effort; a failure here only means that step happens on the first request instead."""
    from solstice.agent.prompts import build_system_prompt
    from solstice.data.store import get_store
    steps = [("data", get_store),
             ("prompts", lambda: [build_system_prompt(a, m) for a, m, _ in VIEWS.values() if a]),
             ("settings store", lambda: (themes.current(), open_access.is_on()))]
    try:
        from solstice.agent.llm import get_client
        steps.append(("model client", get_client))
    except Exception:
        pass
    for name, fn in steps:
        try:
            fn()
        except Exception:
            log.warning("warm-up step '%s' failed; it will run on first use", name, exc_info=True)


@asynccontextmanager
async def lifespan(_app):
    # In the background, so the health probe passes (and the replica takes traffic) at once.
    threading.Thread(target=warm_up, name="warm-up", daemon=True).start()
    yield


app = FastAPI(title="Solstice Hotel Group Agent", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
store = SessionStore()
limiter = UsageLimiter()


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"

# Swappable in tests so no real model is called.
agent_factory = lambda agent, mode: AgentSession(agent, mode)  # noqa: E731

DEGRADED_MESSAGE = ("I'm sorry, I can't answer right now because our assistant is temporarily unavailable. "
                    "I've passed your message to the front desk team (reference {ticket}), and they'll follow up with you. "
                    "For anything urgent, please call the front desk directly.")


# ---------------- pages ----------------

_ASSET_REF = re.compile(r'(/static/[\w.-]+\.(?:js|css))(?=")')


@lru_cache(maxsize=64)
def _fingerprint(path: str, mtime: float) -> str:
    return hashlib.sha256((STATIC / path.removeprefix("/static/")).read_bytes()).hexdigest()[:10]


def _versioned(match: re.Match) -> str:
    """/static/common.js -> /static/common.js?v=<content hash>. Static files have no cache headers, so a browser
    may keep an old copy after a deploy (seen 2026-11-23: the demo banner didn't show until a hard refresh).
    A new file means a new URL, so every browser fetches it at once."""
    path = match.group(1)
    f = STATIC / path.removeprefix("/static/")
    return f"{path}?v={_fingerprint(path, f.stat().st_mtime)}" if f.exists() else path


def _page(name: str) -> HTMLResponse:
    """Serve a page with the saved theme already on <html>, so there's no flash of the wrong look.
    no-store: a theme change shows on the next page load."""
    html = _ASSET_REF.sub(_versioned, (STATIC / name).read_text(encoding="utf-8"))
    attr = ' data-open-access="true"' if open_access.is_on() else ""   # sign-in pages relax the PIN field
    html = html.replace('<html lang="en">', f'<html lang="en" data-theme="{themes.current()}"{attr}>', 1)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.get("/", include_in_schema=False)
def guest_page():
    return _page("guest.html")


@app.get("/staff", include_in_schema=False)
def staff_page():
    return _page("staff.html")


@app.get("/admin", include_in_schema=False)
def admin_page():
    return _page("admin.html")


@app.get("/api/theme")
def public_theme():
    """The active theme id. Public on purpose (it's just a look); changing it needs an admin session."""
    return {"theme": themes.current()}


@app.get("/healthz", include_in_schema=False)
def healthz():
    """Liveness probe for Container Apps. Cheap: no model call."""
    return {"status": "ok"}


# ---------------- sessions ----------------

class StartRequest(BaseModel):
    view: str = Field(description="guest | front_desk | group_sales | admin")
    pin: str | None = None


@app.post("/api/sessions")
def start_session(body: StartRequest, request: Request):
    if body.view not in VIEWS:
        raise HTTPException(400, "Unknown view.")
    _, _, pin_role = VIEWS[body.view]
    client = _client(request)
    try:
        limiter.check_new_chat(client)
    except LimitExceeded as e:
        raise HTTPException(e.status, e.message)
    if pin_role:
        if store.pin_locked(client):
            raise HTTPException(429, "Too many incorrect PINs. Try again in a few minutes.")
        if not store.check_pin(pin_role, body.pin or "", client):
            raise HTTPException(401, "Incorrect PIN.")
    token, ws = store.create(body.view, agent_factory)
    out = {"token": token, "view": body.view, "mode": ws.mode}
    if ws.agent_session:
        out.update(agent=ws.agent, model=ws.agent_session.model)
    return out


@app.post("/api/sessions/restart")
def restart_session(request: Request, authorization: str | None = Header(default=None)):
    """New conversation for a signed-in staff session: same workspace, fresh agent memory, no PIN prompt.
    The PIN was already checked when this session was created; the view comes from the session, never the page."""
    old = _token(authorization)
    ws = store.get(old)
    if not ws or ws.mode != "staff":
        raise HTTPException(401, "Session expired. Please sign in again.")
    try:
        limiter.check_new_chat(_client(request))
    except LimitExceeded as e:
        raise HTTPException(e.status, e.message)
    store.end(old)
    token, new = store.create(ws.view, agent_factory)
    return {"token": token, "view": new.view, "mode": new.mode, "agent": new.agent, "model": new.agent_session.model}


@app.delete("/api/sessions")
def end_session(authorization: str | None = Header(default=None)):
    store.end(_token(authorization))
    return {"ended": True}


def _token(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def _require(authorization: str | None, modes: tuple[str, ...]):
    ws = store.get(_token(authorization))
    if not ws:
        raise HTTPException(401, "Session expired. Please start again.")
    if ws.mode not in modes:
        raise HTTPException(403, "Not allowed in this mode.")
    return ws


# ---------------- chat ----------------

class ChatRequest(BaseModel):
    # Hard ceiling only; the friendly per-mode length limit is in settings.yaml -> limits.
    message: str = Field(min_length=1, max_length=20000)


@app.post("/api/chat")
def chat(body: ChatRequest, request: Request, authorization: str | None = Header(default=None)):
    ws = _require(authorization, ("guest", "staff"))
    sess = ws.agent_session
    text = body.message.strip()
    try:
        limiter.check_message(_client(request), ws.mode, text, ws.messages)
    except LimitExceeded as e:
        if e.status == 200:   # daily budget: answer like the assistant would, no model call
            return {"text": e.message, "degraded": True, "limit": e.kind, "steps": [],
                    "latency_s": None, "tokens": None, "within_target": None}
        raise HTTPException(e.status, e.message)
    # One turn at a time per chat. A second message while the first is still running (say the browser gave up
    # and the user sent again) would interleave the two and break the conversation, so it's refused instead.
    if not sess.lock.acquire(blocking=False):
        raise HTTPException(409, "I'm still working on your previous message. Please give me a moment.")
    try:
        ws.messages += 1
        try:
            r = sess.send(text)
        except Exception as e:  # model or network failure: degrade gracefully, never a dead end
            log.exception("agent call failed")
            ticket = _handoff_ticket(sess, type(e).__name__)
            runtime_store.append("audit", {"event": "model_unavailable", "session_id": sess.ctx.session_id,
                                           "agent": ws.agent, "mode": ws.mode, "error": type(e).__name__})
            return {"text": DEGRADED_MESSAGE.format(ticket=ticket), "degraded": True, "steps": [],
                    "latency_s": None, "tokens": None, "within_target": None}
    finally:
        sess.lock.release()

    limiter.record_tokens(r.input_tokens + r.output_tokens)
    out = {"text": r.text, "degraded": False, "latency_s": r.latency_s,
           "within_target": r.within_latency_target, "tokens": {"in": r.input_tokens, "out": r.output_tokens},
           "model": r.model}
    # Staff see what the agent did under the hood; guests only see the answer.
    out["steps"] = ([{"tool": st.tool, "input": st.input, "output": st.output, "ok": st.ok, "ms": st.ms}
                     for st in r.steps] if ws.mode == "staff" else [])
    return out


def _handoff_ticket(sess, error: str) -> str:
    from solstice.tools.escalation import escalate_to_staff
    t = escalate_to_staff(sess.ctx, category="other",
                          summary="The assistant was unavailable, so this conversation was handed to staff automatically.",
                          recommended_next_step="Read the transcript and follow up with the guest.",
                          what_agent_already_did=f"Nothing: model call failed ({error}).")
    return t["ticket_id"]


# ---------------- staff ----------------

@app.get("/api/staff/tickets")
def staff_tickets(authorization: str | None = Header(default=None)):
    _require(authorization, ("staff", "admin"))
    tickets = runtime_store.read_all("tickets")[-25:][::-1]
    return [{k: t.get(k) for k in ("ticket_id", "created_at", "priority", "category", "route_to", "summary",
                                   "recommended_next_step", "property_code", "guest_verified", "source", "transcript")}
            for t in tickets]


# ---------------- admin ----------------
# Everything here is read-only except the website theme and the demo open-access switch below.

@app.get("/api/admin/open-access")
def admin_open_access(authorization: str | None = Header(default=None)):
    _require(authorization, ("admin",))
    return open_access.status()


class OpenAccessRequest(BaseModel):
    enabled: bool


@app.put("/api/admin/open-access")
def set_admin_open_access(body: OpenAccessRequest, authorization: str | None = Header(default=None)):
    _require(authorization, ("admin",))
    try:
        open_access.set_enabled(body.enabled)
    except open_access.NotAllowed:
        raise HTTPException(403, "Open access is disabled for this deployment (access.allow_open_access).")
    except Exception:
        log.exception("could not save the open-access setting")
        raise HTTPException(503, "Couldn't save that right now. Please try again.")
    return open_access.status()


@app.get("/api/admin/theme")
def admin_theme(authorization: str | None = Header(default=None)):
    _require(authorization, ("admin",))
    return themes.status()


class ThemeRequest(BaseModel):
    theme: str = Field(max_length=40)


@app.put("/api/admin/theme")
def set_admin_theme(body: ThemeRequest, authorization: str | None = Header(default=None)):
    _require(authorization, ("admin",))
    try:
        themes.save(body.theme)
    except ValueError:
        raise HTTPException(400, "Unknown theme.")
    except Exception:
        log.exception("could not save the theme")
        raise HTTPException(503, "Couldn't save the theme right now. Please try again.")
    return themes.status()


@app.get("/api/admin/settings")
def admin_settings(authorization: str | None = Header(default=None)):
    _require(authorization, ("admin",))
    return admin.settings_summary()


@app.get("/api/admin/health")
def admin_health(api: bool = False, authorization: str | None = Header(default=None)):
    _require(authorization, ("admin",))
    return [{"status": s, "check": n, "detail": d} for s, n, d in admin.health_checks(check_api=api)]


@app.get("/api/admin/tools")
def admin_tools(authorization: str | None = Header(default=None)):
    _require(authorization, ("admin",))
    return admin.tools_summary()


@app.get("/api/admin/activity")
def admin_activity(authorization: str | None = Header(default=None)):
    _require(authorization, ("admin",))
    return {**admin.activity_summary(), "latency_target_s": get_settings().latency_target_s,
            "limits": limiter.status()}


@app.get("/api/admin/data-quality")
def admin_data_quality(authorization: str | None = Header(default=None)):
    _require(authorization, ("admin",))
    return admin.data_quality_list()
