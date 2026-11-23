"""The agent loop. About 100 lines, on purpose. No framework to explain.

    user message
       -> model (with system prompt + tools)
       -> if the model asks for tools: run them, send results back, repeat
       -> final text to user

Every tool call is timed and recorded in a trace, which the UI shows in its
"under the hood" panel and which is appended to data/runtime/traces.jsonl.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field

from solstice.agent.prompts import build_system_prompt
from solstice.config import get_settings
from solstice import runtime_store
from solstice.tools.registry import ToolContext, ToolError, tools_for


@dataclass
class TraceStep:
    tool: str
    input: dict
    output: dict
    ok: bool
    ms: int


@dataclass
class TurnResult:
    text: str
    steps: list[TraceStep] = field(default_factory=list)
    model: str = ""
    latency_s: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    within_latency_target: bool = True
    truncated: bool = False          # reply hit max_tokens
    cache_read_tokens: int = 0       # prompt tokens served from cache (billed at ~10%)
    cache_write_tokens: int = 0      # prompt tokens written to cache (billed at ~125%)


class AgentSession:
    def __init__(self, agent: str, mode: str = "guest", client=None, model: str | None = None):
        s = get_settings()
        self.agent, self.mode = agent, mode
        self.model = model or s.model_for(agent)
        self.ctx = ToolContext(agent=agent, mode=mode, session_id=uuid.uuid4().hex[:8])
        self.tools = {t.name: t for t in tools_for(agent, mode)}
        self.system = build_system_prompt(agent, mode)
        self.messages: list[dict] = []
        self._client = client
        # One turn at a time per conversation. Two overlapping turns (a resend while the first is still
        # running) would interleave their messages and break the history for every later turn.
        self.lock = threading.Lock()

    @property
    def client(self):
        if self._client is not None:
            return self._client
        from solstice.agent.llm import get_client
        return get_client()          # shared app-wide, so connections stay warm

    def _run_tool(self, name: str, args: dict) -> TraceStep:
        t0 = time.perf_counter()
        try:
            if name not in self.tools:
                raise ToolError(f"Tool '{name}' is not available in {self.agent}/{self.mode}.")
            out, ok = self.tools[name].handler(self.ctx, **args), True
        except ToolError as e:
            out, ok = {"error": str(e)}, False
        except Exception as e:  # unexpected bug: fail soft, the model can escalate
            out, ok = {"error": f"Tool failed unexpectedly ({type(e).__name__}). Do not guess; offer to escalate."}, False
        # Audit: who (session + mode) touched which records with which tool. Only record IDs are
        # logged, never free text such as names, so the audit log holds no guest PII.
        runtime_store.append("audit", {
            "event": "tool_call", "session_id": self.ctx.session_id, "agent": self.agent, "mode": self.mode,
            "tool": name, "ok": ok,
            "records": {k: v for k, v in args.items() if k.endswith("_id") or k == "property_code"},
        })
        return TraceStep(name, args, out, ok, int((time.perf_counter() - t0) * 1000))

    def _trim_history(self, max_turns: int) -> None:
        """Keep only the last `max_turns` user messages and everything after them, so a long chat
        doesn't get more expensive every turn. Cuts only at a user's own message, so tool calls
        and their results always stay paired. Verification state lives in ctx, so it survives."""
        starts = [i for i, m in enumerate(self.messages) if m["role"] == "user" and isinstance(m["content"], str)]
        if len(starts) > max_turns:
            self.messages = self.messages[starts[-max_turns]:]

    def _handoff_ticket(self, reason: str) -> str | None:
        """Open a staff ticket with the transcript when the loop can't finish a reply. Never raises."""
        from solstice.tools.escalation import escalate_to_staff
        try:
            t = escalate_to_staff(self.ctx, category="other",
                                  summary="The assistant couldn't finish its reply, so this conversation was handed to staff automatically.",
                                  recommended_next_step="Read the transcript and follow up with the user.",
                                  what_agent_already_did=reason)
            return t["ticket_id"]
        except Exception:  # a failed handoff must not turn into a crash for the user
            return None

    def _handoff_text(self, reason: str) -> str:
        ticket = self._handoff_ticket(reason)
        return ("I'm sorry, I wasn't able to finish that. I've passed this conversation to a team member"
                + (f" (reference {ticket})" if ticket else "") + ", and they'll follow up with you.")

    def send(self, user_text: str) -> TurnResult:
        """Run one user turn. If the model call fails, the history is rolled back to how it was before
        this turn, so the conversation stays usable: the next message works instead of failing forever.
        The staff-facing transcript keeps the message, so the handoff ticket shows what the user asked."""
        snapshot = list(self.messages)
        try:
            return self._send(user_text)
        except Exception:
            self.messages = snapshot
            raise

    def _send(self, user_text: str) -> TurnResult:
        s = get_settings()
        t0 = time.perf_counter()
        deadline = t0 + s.turn_deadline_for(self.agent)
        self.messages.append({"role": "user", "content": user_text})
        self.ctx.transcript.append({"role": "user", "text": user_text})
        self._trim_history(s.max_history_turns)
        result = TurnResult(text="", model=self.model)

        for _ in range(s.max_tool_rounds):
            remaining = deadline - time.perf_counter()
            if remaining < 3:   # not enough time left for a useful model call: hand off now, don't hang
                result.text = self._handoff_text(f"Reply took longer than {s.turn_deadline_for(self.agent):.0f} s.")
                break
            # The SDK retries (max_retries) within this timeout budget each time, so split what's left.
            call_timeout = min(s.request_timeout_s, remaining / (s.max_retries + 1))
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=s.max_tokens,
                system=[{"type": "text", "text": self.system, "cache_control": {"type": "ephemeral"}}],
                tools=[t.spec() for t in self.tools.values()],
                messages=self.messages,
                timeout=call_timeout,
            )
            result.input_tokens += resp.usage.input_tokens
            result.output_tokens += resp.usage.output_tokens
            result.cache_read_tokens += getattr(resp.usage, "cache_read_input_tokens", 0) or 0
            result.cache_write_tokens += getattr(resp.usage, "cache_creation_input_tokens", 0) or 0
            self.messages.append({"role": "assistant", "content": [b.model_dump() for b in resp.content]})

            tool_uses = [b for b in resp.content if b.type == "tool_use"]
            if resp.stop_reason != "tool_use" and tool_uses:
                # Cut off mid tool call (max_tokens): a tool_use with no tool_result would make every
                # later request in this chat fail, so keep only the text part in the history.
                kept = [b.model_dump() for b in resp.content if b.type != "tool_use"]
                self.messages[-1]["content"] = kept or [{"type": "text", "text": "(reply cut short)"}]
            if resp.stop_reason != "tool_use" or not tool_uses:
                result.text = "".join(b.text for b in resp.content if b.type == "text").strip()
                if resp.stop_reason == "max_tokens":   # hit the reply cap: say so instead of ending mid-sentence
                    result.truncated = True
                    result.text += "\n\n(My reply was cut short. Ask me to continue and I'll finish it.)"
                break

            tool_results = []
            for b in tool_uses:
                step = self._run_tool(b.name, dict(b.input))
                result.steps.append(step)
                tool_results.append({"type": "tool_result", "tool_use_id": b.id,
                                     "content": json.dumps(step.output, default=str), "is_error": not step.ok})
            self.messages.append({"role": "user", "content": tool_results})
        else:
            # Out of tool rounds: hand off for real, so the promise to follow up is kept.
            result.text = self._handoff_text(f"Ran out of tool rounds ({s.max_tool_rounds}) before finishing a reply.")
        if result.text and self.messages[-1]["role"] == "user" and not isinstance(self.messages[-1]["content"], str):
            # Stopped right after tool results (deadline or round cap): close the turn so the next one is valid.
            self.messages.append({"role": "assistant", "content": [{"type": "text", "text": result.text}]})

        result.latency_s = round(time.perf_counter() - t0, 2)
        result.within_latency_target = result.latency_s <= s.latency_target_for(self.agent)
        self.ctx.transcript.append({"role": "assistant", "text": result.text})
        runtime_store.append("traces", {
            "session_id": self.ctx.session_id, "agent": self.agent, "mode": self.mode, "model": self.model,
            "latency_s": result.latency_s, "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
            "truncated": result.truncated,
            "tools": [{"tool": st.tool, "ok": st.ok, "ms": st.ms} for st in result.steps],
        })
        return result
