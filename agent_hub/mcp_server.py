"""Minimal stdio MCP server exposing the hub to an orchestrating Claude Code session."""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Callable

from .client import HubClient
from .util import load_dotenv, truncate

INSTRUCTIONS = (
    "agent-hub lets you delegate work to other AI agents (Claude on other accounts/machines, Codex, Kimi) "
    "and run cross-vendor review panels. Use list_agents to see who is online, dispatch for a single job, "
    "review_panel to have several agents solve + review each other + synthesize. Results are stored on the hub "
    "and visible in the web UI; always report the run URL to the user."
)


def _client() -> HubClient:
    load_dotenv()
    return HubClient()


def _url(path: str) -> str:
    return (os.environ.get("HUB_PUBLIC_URL") or os.environ.get("HUB_URL") or "http://127.0.0.1:8765").rstrip("/") + path


def _wait_run(c: HubClient, run_id: str, timeout: float) -> dict[str, Any]:
    deadline = time.time() + timeout
    while True:
        run = c.get(f"/api/runs/{run_id}")["run"]
        if run["status"] != "running" or time.time() >= deadline:
            return run
        time.sleep(5)


def _run_summary(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": run["id"], "status": run["status"], "recipe": run["recipe"], "title": run["title"],
        "phase": run.get("state", {}).get("phase"), "url": _url(f"/runs/{run['id']}"),
        "tasks": [{"id": t["id"], "step": t["step"], "agent": t["agent"], "status": t["status"],
                   "error": t.get("error")} for t in run.get("tasks", [])],
        "summary": truncate(run.get("summary") or "", 20000),
    }


def t_list_agents(a: dict[str, Any]) -> Any:
    agents = _client().get("/api/agents")["agents"]
    return [{"name": x["name"], "kind": x["kind"], "host": x["host"], "status": x["status"], "online": x["online"]}
            for x in agents if x["online"] or a.get("include_offline")]


def t_dispatch(a: dict[str, Any]) -> Any:
    c = _client()
    run = c.post("/api/runs", {"recipe": "single", "project": a.get("project", "default"), "title": a.get("title") or a["prompt"][:60],
                               "created_by": "claude-code-mcp",
                               "spec": {"prompt": a["prompt"], "agent": a["agent"], "workdir": a.get("workdir"),
                                        "models": {a["agent"]: a["model"]} if a.get("model") else {}}})["run"]
    if a.get("wait", True):
        run = _wait_run(c, run["id"], float(a.get("timeout", 1800)))
        run = c.get(f"/api/runs/{run['id']}")["run"]
    return _run_summary(run)


def t_review_panel(a: dict[str, Any]) -> Any:
    c = _client()
    spec = {"prompt": a["prompt"], "solvers": a["solvers"], "reviewers": a.get("reviewers"),
            "synthesizer": a.get("synthesizer"), "workdir": a.get("workdir"), "models": a.get("models") or {}}
    run = c.post("/api/runs", {"recipe": "review_panel", "project": a.get("project", "default"),
                               "title": a.get("title") or a["prompt"][:60], "created_by": "claude-code-mcp", "spec": spec})["run"]
    if a.get("wait", True):
        run = _wait_run(c, run["id"], float(a.get("timeout", 3600)))
    return _run_summary(c.get(f"/api/runs/{run['id']}")["run"])


def t_parallel(a: dict[str, Any]) -> Any:
    c = _client()
    run = c.post("/api/runs", {"recipe": "parallel", "project": a.get("project", "default"),
                               "title": a.get("title") or a["prompt"][:60], "created_by": "claude-code-mcp",
                               "spec": {"prompt": a["prompt"], "agents": a["agents"], "workdir": a.get("workdir")}})["run"]
    if a.get("wait", True):
        run = _wait_run(c, run["id"], float(a.get("timeout", 1800)))
    return _run_summary(c.get(f"/api/runs/{run['id']}")["run"])


def t_get_run(a: dict[str, Any]) -> Any:
    c = _client()
    run = c.get(f"/api/runs/{a['run_id']}")["run"]
    out = _run_summary(run)
    if a.get("include_results"):
        out["results"] = {f"{t['step']}/{t['agent']}": truncate(t.get("result") or t.get("error") or "", 12000) for t in run["tasks"]}
    return out


def t_wait_run(a: dict[str, Any]) -> Any:
    c = _client()
    run = _wait_run(c, a["run_id"], float(a.get("timeout", 1800)))
    return _run_summary(c.get(f"/api/runs/{run['id']}")["run"])


def t_get_task_transcript(a: dict[str, Any]) -> Any:
    task = _client().get(f"/api/tasks/{a['task_id']}")["task"]
    msgs = task.pop("messages", [])
    lines = [f"[{m['role']}] {truncate(m['content'], 1500)}" for m in msgs if m["role"] in a.get("roles", ["assistant", "tool_use", "result", "stderr"])]
    return {"task": {k: task[k] for k in ("id", "agent", "step", "status", "error")}, "transcript": "\n".join(lines)[-40000:]}


def t_list_runs(a: dict[str, Any]) -> Any:
    runs = _client().get(f"/api/runs?limit={a.get('limit', 20)}" + (f"&project={a['project']}" if a.get("project") else ""))["runs"]
    return [{"id": r["id"], "title": r["title"], "recipe": r["recipe"], "status": r["status"], "created_at": r["created_at"], "url": _url(f"/runs/{r['id']}")} for r in runs]


AGENT_ARR = {"type": "array", "items": {"type": "string"}}
TOOLS: list[tuple[str, str, dict[str, Any], Callable[[dict[str, Any]], Any]]] = [
    ("list_agents", "List agents currently online on the hub (name, kind, host).",
     {"type": "object", "properties": {"include_offline": {"type": "boolean"}}}, t_list_agents),
    ("dispatch", "Send one prompt to one agent and (by default) wait for its final answer.",
     {"type": "object", "required": ["agent", "prompt"], "properties": {
         "agent": {"type": "string"}, "prompt": {"type": "string"}, "workdir": {"type": "string", "description": "absolute path on the runner machine"},
         "model": {"type": "string", "description": "model override for this job, e.g. opus / fable / sonnet"},
         "project": {"type": "string"}, "title": {"type": "string"}, "wait": {"type": "boolean"}, "timeout": {"type": "number"}}}, t_dispatch),
    ("review_panel", "Cross-vendor review: each solver answers independently, reviewers critique each other, synthesizer merges. Returns the synthesized result.",
     {"type": "object", "required": ["prompt", "solvers"], "properties": {
         "prompt": {"type": "string"}, "solvers": AGENT_ARR, "reviewers": AGENT_ARR, "synthesizer": {"type": "string"},
         "models": {"type": "object", "description": "per-agent model override, e.g. {\"claude-aspa1\": \"opus\"}", "additionalProperties": {"type": "string"}},
         "workdir": {"type": "string"}, "project": {"type": "string"}, "title": {"type": "string"},
         "wait": {"type": "boolean"}, "timeout": {"type": "number"}}}, t_review_panel),
    ("parallel", "Same prompt to several agents at once, no review; returns all answers.",
     {"type": "object", "required": ["prompt", "agents"], "properties": {
         "prompt": {"type": "string"}, "agents": AGENT_ARR, "workdir": {"type": "string"}, "project": {"type": "string"},
         "title": {"type": "string"}, "wait": {"type": "boolean"}, "timeout": {"type": "number"}}}, t_parallel),
    ("get_run", "Get status/summary of a run; include_results adds every task's final text.",
     {"type": "object", "required": ["run_id"], "properties": {"run_id": {"type": "string"}, "include_results": {"type": "boolean"}}}, t_get_run),
    ("wait_run", "Block until a run finishes (or timeout seconds).",
     {"type": "object", "required": ["run_id"], "properties": {"run_id": {"type": "string"}, "timeout": {"type": "number"}}}, t_wait_run),
    ("get_task_transcript", "Read the transcript (assistant text, tool calls, result) of one task.",
     {"type": "object", "required": ["task_id"], "properties": {"task_id": {"type": "string"}, "roles": AGENT_ARR}}, t_get_task_transcript),
    ("list_runs", "List recent runs.", {"type": "object", "properties": {"project": {"type": "string"}, "limit": {"type": "integer"}}}, t_list_runs),
]


def _send(msg: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> None:
    by_name = {t[0]: t for t in TOOLS}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid, method, params = req.get("id"), req.get("method"), req.get("params") or {}
        if method == "initialize":
            _send({"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": params.get("protocolVersion", "2024-11-05"),
                   "capabilities": {"tools": {}}, "serverInfo": {"name": "agent-hub", "version": "0.1.0"}, "instructions": INSTRUCTIONS}})
        elif method == "notifications/initialized":
            continue
        elif method == "ping":
            _send({"jsonrpc": "2.0", "id": rid, "result": {}})
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": rid, "result": {"tools": [{"name": n, "description": d, "inputSchema": s} for n, d, s, _ in TOOLS]}})
        elif method == "tools/call":
            name = params.get("name")
            if name not in by_name:
                _send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"unknown tool {name}"}})
                continue
            try:
                out = by_name[name][3](params.get("arguments") or {})
                _send({"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False, indent=1)}]}})
            except Exception as e:  # noqa: BLE001
                _send({"jsonrpc": "2.0", "id": rid, "result": {"isError": True, "content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}]}})
        elif rid is not None:
            _send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"unknown method {method}"}})


if __name__ == "__main__":
    main()
