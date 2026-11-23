"""Run the Tier 1 evals against the real model.

    cd backend
    .\\.venv\\Scripts\\python.exe -m solstice.evals run                     # all cases, default model
    .\\.venv\\Scripts\\python.exe -m solstice.evals run --model claude-sonnet-5-5
    .\\.venv\\Scripts\\python.exe -m solstice.evals run --only checkout-time,threat-urgent --reps 3
    .\\.venv\\Scripts\\python.exe -m solstice.evals run --null              # harness self-check, no API calls
    .\\.venv\\Scripts\\python.exe -m solstice.evals run --synthetic 35      # group sales on 35 synthetic inquiries
    .\\.venv\\Scripts\\python.exe -m solstice.evals run --synthetic         # ...or all of them (data/synthetic)
    .\\.venv\\Scripts\\python.exe -m solstice.evals regrade <run folder>     # re-grade saved traces with today's checks

Each run writes data/runtime/evals/<timestamp>_<model>/: results.jsonl (one row per case and rep),
traces/<id>_rep<k>.json (full conversation with tool calls), errors.jsonl, and summary.md.
Tickets, requests and proposals created during the run go into that folder, not data/runtime.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace as NS

import yaml

from solstice import runtime_store
from solstice.agent.runner import AgentSession
from solstice.config import REPO_ROOT, get_settings
from solstice.data.store import get_store
from solstice.evals import synthetic_cases
from solstice.evals.checks import run_checks

CASES = Path(__file__).with_name("cases.yaml")
# $ per million tokens: input, output (cache reads 0.1x input, cache writes 1.25x input)
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.0, 10.0), "claude-opus-5-5": (4.0, 20.0)}
CASE_TIMEOUT_S = 180


class NullClient:
    """Answers every message with the same unhelpful line and never calls a tool.
    A healthy grader should fail almost every case against it."""
    def __init__(self):
        self.messages = self

    def create(self, **kw):
        block = NS(type="text", text="I'm not able to help with that.")
        block.model_dump = lambda: {"type": "text", "text": block.text}
        return NS(content=[block], stop_reason="end_turn", usage=NS(input_tokens=0, output_tokens=0))


def cost_usd(model: str, u: dict) -> float | None:
    p = PRICES.get(model)
    if not p:
        return None
    pin, pout = p
    return (u["input_tokens"] * pin + u["cache_read_input_tokens"] * pin * 0.1
            + u["cache_creation_input_tokens"] * pin * 1.25 + u["output_tokens"] * pout) / 1e6


def run_case(case: dict, model: str | None, null: bool) -> dict:
    sess = AgentSession(case["agent"], case["mode"], model=model, client=NullClient() if null else None)
    steps, replies, trace = [], [], [{"role": "system", "content": f"[{case['agent']} / {case['mode']} system prompt]"}]
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    latencies, truncated = [], False
    for msg in case["turns"]:
        trace.append({"role": "user", "content": msg})
        r = sess.send(msg)
        for st in r.steps:
            s = {"tool": st.tool, "input": st.input, "output": st.output, "ok": st.ok, "ms": st.ms}
            steps.append(s)
            trace.append({"role": "tool_call", "name": st.tool, "content": json.dumps(st.input, indent=2)})
            trace.append({"role": "tool_result", "content": json.dumps(st.output, default=str)})
        trace.append({"role": "assistant", "content": r.text})
        replies.append(r.text)
        latencies.append(r.latency_s)
        truncated |= r.truncated
        usage["input_tokens"] += r.input_tokens
        usage["output_tokens"] += r.output_tokens
        usage["cache_read_input_tokens"] += r.cache_read_tokens
        usage["cache_creation_input_tokens"] += r.cache_write_tokens
    checks = run_checks(case.get("expect", {}), steps, replies)
    passed = all(c["passed"] for c in checks)
    escalated = any(s["tool"] == "escalate_to_staff" and s["ok"] for s in steps)
    return {"checks": checks, "pass": passed, "escalated": escalated, "trace": trace, "usage": usage,
            "latency_s": max(latencies) if latencies else 0.0, "tool_calls": len(steps),
            "status": "truncated" if truncated else "ok", "model": sess.model}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def main():
    ap = argparse.ArgumentParser(prog="python -m solstice.evals")
    ap.add_argument("command", choices=["run", "cases", "regrade"],
                    help="run the evals, write CASES.md for review, or re-grade a saved run")
    ap.add_argument("run_dir", nargs="?", help="regrade only: the run folder under data/runtime/evals")
    ap.add_argument("--model", help="model to evaluate (default: config/settings.yaml)")
    ap.add_argument("--only", help="comma-separated case ids")
    ap.add_argument("--tag", help="only cases with this tag")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--null", action="store_true", help="harness self-check with a do-nothing model (no API calls)")
    ap.add_argument("--synthetic", type=int, nargs="?", const=0, metavar="N",
                    help="run group sales on the synthetic 10x data instead of cases.yaml: N cases spread across "
                         "scenarios, or all labeled inquiries if N is left out")
    a = ap.parse_args()

    if a.command == "regrade":
        if not a.run_dir:
            ap.error("regrade needs the run folder")
        return print(regrade(Path(a.run_dir)))

    if a.synthetic is not None:
        os.environ["SOLSTICE_DATA_DIR"] = synthetic_cases.DATA_DIR   # every tool and check now reads the synthetic CSVs
        get_store.cache_clear()
        cases = synthetic_cases.build_cases(a.synthetic)
    else:
        cases = yaml.safe_load(CASES.read_text(encoding="utf-8"))
    if a.command == "cases":
        return write_case_list(cases, "CASES_SYNTHETIC.md" if a.synthetic is not None else "CASES.md")
    if a.only:
        want = set(a.only.split(","))
        cases = [c for c in cases if c["id"] in want]
    if a.tag:
        cases = [c for c in cases if a.tag in c.get("tags", [])]
    model = a.model or get_settings().model_for("concierge")
    label = ("null-model" if a.null else model) + ("_synthetic" if a.synthetic is not None else "")
    out = REPO_ROOT / "data" / "runtime" / "evals" / f"{datetime.now():%Y%m%d-%H%M%S}_{label}"
    (out / "traces").mkdir(parents=True, exist_ok=True)
    (out / "runtime").mkdir(exist_ok=True)
    runtime_store._dir = lambda: out / "runtime"     # keep eval tickets/proposals out of data/runtime

    jobs = [(c, k) for c in cases for k in range(a.reps)]
    print(f"Running {len(cases)} cases x {a.reps} rep(s) on {label} -> {out}")
    t0 = time.perf_counter()
    rows, errors = [], []
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures = {pool.submit(run_case, c, a.model, a.null): (c, k) for c, k in jobs}
        for fut, (c, k) in futures.items():
            try:
                r = fut.result(timeout=CASE_TIMEOUT_S)
            except FutureTimeout:
                errors.append({"case": c["id"], "rep": k, "failure": "timeout"})
                continue
            except Exception as e:  # harness or API failure: not a model failure, keep it out of the score
                errors.append({"case": c["id"], "rep": k, "failure": "error", "error": f"{type(e).__name__}: {e}"})
                continue
            (out / "traces" / f"{c['id']}_rep{k}.json").write_text(json.dumps(r["trace"], indent=2), encoding="utf-8")
            row = {"prompt_id": c["id"], "rep": k, "prompt": " / ".join(c["turns"]), "tags": c.get("tags", []),
                   "status": r["status"], "grade": {"pass": 1.0 if r["pass"] else 0.0},
                   "checks": r["checks"], "escalated": r["escalated"], "resolves_alone": bool(c.get("resolves_alone")),
                   "agent": c["agent"], "mode": c["mode"], "model": r["model"], "usage": r["usage"],
                   "cost_usd": None if a.null else cost_usd(r["model"], r["usage"]),
                   "latency_s": r["latency_s"], "tool_calls": r["tool_calls"]}
            rows.append(row)
            with open(out / "results.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
            mark = "PASS" if r["pass"] else "FAIL"
            failed = [x["check"] for x in r["checks"] if not x["passed"]]
            print(f"  {mark}  {c['id']:<34} {r['latency_s']:>5.1f}s  {'' if r['pass'] else failed}")
    for e in errors:
        with open(out / "errors.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(e) + "\n")

    summary = summarize(rows, errors, label, a.reps, time.perf_counter() - t0, a.null)
    (out / "summary.md").write_text(summary, encoding="utf-8")
    print("\n" + summary)
    print(f"Results: {out}")


def steps_from_trace(trace: list[dict]) -> tuple[list[dict], list[str]]:
    """Rebuild the tool steps and replies a saved trace recorded, in the shape run_checks expects.
    A tool result that is only {"error": ...} was a refusal or failure (ok=False), as in the runner."""
    steps, replies, pending = [], [], None
    for m in trace:
        if m["role"] == "tool_call":
            pending = {"tool": m["name"], "input": json.loads(m["content"])}
        elif m["role"] == "tool_result" and pending:
            out = json.loads(m["content"])
            steps.append({**pending, "output": out, "ok": not (isinstance(out, dict) and set(out) == {"error"})})
            pending = None
        elif m["role"] == "assistant":
            replies.append(m["content"])
    return steps, replies


def regrade(run_dir: Path) -> str:
    """Re-grade a saved run with today's checks: no API calls, the model's answers stay exactly as recorded.
    Used after a grader fix, so a run's numbers can be updated without paying for (or changing) the run.
    Writes results-regraded.jsonl and a new summary.md that names every changed verdict;
    the first original summary is kept as summary-original.md."""
    run_dir = run_dir.resolve()
    synthetic = run_dir.name.endswith("_synthetic")
    if synthetic:
        os.environ["SOLSTICE_DATA_DIR"] = synthetic_cases.DATA_DIR
        get_store.cache_clear()
        cases = {c["id"]: c for c in synthetic_cases.build_cases(0)}
    else:
        cases = {c["id"]: c for c in yaml.safe_load(CASES.read_text(encoding="utf-8"))}
    rows = [json.loads(line) for line in (run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    errors_file = run_dir / "errors.jsonl"
    errors = [json.loads(line) for line in errors_file.read_text(encoding="utf-8").splitlines() if line.strip()] \
        if errors_file.exists() else []
    changed = []
    for row in rows:
        trace = json.loads((run_dir / "traces" / f"{row['prompt_id']}_rep{row['rep']}.json").read_text(encoding="utf-8"))
        steps, replies = steps_from_trace(trace)
        checks = run_checks(cases[row["prompt_id"]].get("expect", {}), steps, replies)
        passed = all(c["passed"] for c in checks)
        if passed != (row["grade"]["pass"] == 1.0):
            changed.append(f"{row['prompt_id']} (rep {row['rep']}): {'FAIL → PASS' if passed else 'PASS → FAIL'}")
        row.update(checks=checks, grade={"pass": 1.0 if passed else 0.0},
                   escalated=any(s["tool"] == "escalate_to_staff" and s["ok"] for s in steps))
    (run_dir / "results-regraded.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    original = run_dir / "summary-original.md"
    if not original.exists():
        (run_dir / "summary.md").rename(original)
    wall = re.search(r"(\d+)s wall clock", original.read_text(encoding="utf-8"))
    label = run_dir.name.split("_", 1)[1]
    reps = max(r["rep"] for r in rows) + 1
    summary = summarize(rows, errors, label, reps, float(wall.group(1)) if wall else 0.0, label.startswith("null-model"))
    note = (f"> Re-graded offline on {datetime.now():%Y-%m-%d} with the current checks (no new API calls; answers "
            f"unchanged). Original summary: `summary-original.md`. Changed verdicts: "
            + ("; ".join(changed) if changed else "none") + ".\n\n")
    title, rest = summary.split("\n", 1)
    (run_dir / "summary.md").write_text(f"{title}\n\n{note}{rest.lstrip()}", encoding="utf-8")
    return f"{run_dir.name}: {len(changed)} verdict(s) changed" + (": " + "; ".join(changed) if changed else "")


def write_case_list(cases, name: str = "CASES.md") -> None:
    """A readable table of every case and what it takes to pass, for review."""
    def fmt(v):
        if v is True:
            return ""
        if isinstance(v, list):
            return "=" + ", ".join(f"{x['tool']}.{x['field']}={x.get('equals', x.get('in'))}" if isinstance(x, dict) else str(x) for x in v)
        return f"={v}"
    lines = ["# Eval cases", "", f"Generated from `{'cases.yaml' if name == 'CASES.md' else 'data/synthetic/labels'}` ({len(cases)} cases). "
             "★ = routine case counted toward 'resolved without a human' (A8).", "",
             "| # | Case | Category | Agent / mode | Message(s) | Passes only if |", "|---|---|---|---|---|---|"]
    for i, c in enumerate(cases, 1):
        req = "<br>".join(f"{k}{fmt(v)}" for k, v in c.get("expect", {}).items())
        msgs = " ⟶ ".join(c["turns"]).replace("|", "\\|")
        lines.append(f"| {i} | `{c['id']}`{' ★' if c.get('resolves_alone') else ''} | {c['tags'][0]} | "
                     f"{c['agent']} / {c['mode']} | {msgs} | {req.replace('|', chr(92) + '|')} |")
    path = CASES.with_name(name)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote", path)


def summarize(rows, errors, label, reps, wall_s, null) -> str:
    ok = [r for r in rows if r["status"] == "ok"]
    n, k = len(ok), sum(r["grade"]["pass"] == 1.0 for r in ok)
    lo, hi = wilson(k, n)
    lines = [f"# Eval results: {label}", "",
             f"**{k}/{n} passed ({100 * k / n if n else 0:.0f}%)**, 95% interval {100 * lo:.0f}–{100 * hi:.0f}% · "
             f"{reps} rep(s) · {len(errors)} harness errors · {sum(r['status'] == 'truncated' for r in rows)} truncated · "
             f"{wall_s:.0f}s wall clock", ""]
    routine = [r for r in ok if r["resolves_alone"]]
    if routine:
        alone = sum(r["grade"]["pass"] == 1.0 and not r["escalated"] for r in routine)
        lines += [f"**Resolved without a human (A8):** {alone}/{len(routine)} routine cases "
                  f"({100 * alone / len(routine):.0f}%) were handled correctly with no escalation.", ""]
    lines += ["| Category | Passed | Cases |", "|---|---|---|"]
    cats = {}
    for r in ok:
        cats.setdefault(r["tags"][0] if r["tags"] else "other", []).append(r)
    for cat, rs in cats.items():
        lines.append(f"| {cat} | {sum(x['grade']['pass'] == 1.0 for x in rs)} | {len(rs)} |")
    if not null:
        for agent in ("concierge", "group_sales"):
            lat = sorted(r["latency_s"] for r in ok if r["agent"] == agent)
            if lat:
                p95 = lat[max(0, round(0.95 * len(lat)) - 1)]
                lines.append(f"\n**{agent} latency (slowest turn per case):** median {lat[len(lat) // 2]:.1f}s, p95 {p95:.1f}s "
                             f"(target {get_settings().latency_target_for(agent):.0f}s)")
        costs = [r["cost_usd"] for r in rows if r["cost_usd"] is not None]
        tok = sum(r["usage"]["input_tokens"] + r["usage"]["output_tokens"] + r["usage"]["cache_read_input_tokens"]
                  + r["usage"]["cache_creation_input_tokens"] for r in rows)
        lines.append(f"\n**Tokens:** {tok:,} · **Cost:** ${sum(costs):.3f}" + ("" if len(costs) == len(rows) else " (some models unpriced)"))
    fails = [r for r in ok if r["grade"]["pass"] != 1.0]
    if fails:
        lines += ["", "## Failures", ""]
        for r in fails:
            bad = "; ".join(f"{c['check']} ({c['detail']})" if c["detail"] else c["check"] for c in r["checks"] if not c["passed"])
            lines.append(f"- **{r['prompt_id']}** (rep {r['rep']}): {bad}")
    if errors:
        lines += ["", "## Harness errors (not scored)", ""] + [f"- {e['case']} rep {e['rep']}: {e.get('error', e['failure'])}" for e in errors]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
