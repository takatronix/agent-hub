"""Runner daemon: lives on each machine, pulls tasks for its agents, streams transcripts to the hub.

Config (JSON), e.g. runner.json:
{
  "hub": "http://100.67.35.127:8765",
  "token": "...",
  "host": "aspa1",
  "agents": [
    {"name": "claude-a", "kind": "claude", "env": {"CLAUDE_CONFIG_DIR": "~/.claude-a"}},
    {"name": "claude-b", "kind": "claude", "env": {"CLAUDE_CONFIG_DIR": "~/.claude-b"}, "model": "opus"},
    {"name": "codex",    "kind": "codex"},
    {"name": "kimi",     "kind": "command", "command": ["kimi", "--print", "--output-format", "stream-json"], "jsonl": true},
    {"name": "fake-1",   "kind": "fake"}
  ],
  "workdir_root": "~/work",
  "flush_interval": 1.0
}
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from .adapters import ADAPTERS, AdapterResult
from .client import HubClient
from .util import load_dotenv, now_iso


def log(*a: Any) -> None:
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


class AgentWorker(threading.Thread):
    def __init__(self, client: HubClient, host: str, cfg: dict[str, Any], flush_interval: float, workdir_root: str | None):
        super().__init__(daemon=True, name=f"agent:{cfg['name']}")
        self.client, self.host, self.cfg = client, host, cfg
        self.name_ = cfg["name"]
        self.kind = cfg.get("kind", "command")
        self.flush_interval = flush_interval
        self.workdir_root = workdir_root
        self.stop = threading.Event()
        self.current: str | None = None

    def heartbeat(self, status: str) -> None:
        try:
            self.client.post("/api/agents/heartbeat", {
                "name": self.name_, "kind": self.kind, "host": self.host, "status": status,
                "current_task": self.current,
                "meta": {k: v for k, v in self.cfg.items() if k in ("model", "command", "description")},
            })
        except Exception as e:  # noqa: BLE001
            log(f"[{self.name_}] heartbeat failed: {e}")

    def run(self) -> None:
        self.heartbeat("idle")
        last_hb = time.time()
        while not self.stop.is_set():
            try:
                task = self.client.post("/api/tasks/claim", {"agents": [self.name_], "claimed_by": f"{self.name_}@{self.host}", "wait": 30})["task"]
            except Exception as e:  # noqa: BLE001
                log(f"[{self.name_}] claim failed: {e}; retrying in 5s")
                time.sleep(5)
                continue
            if task:
                self.current = task["id"]
                self.heartbeat("busy")
                try:
                    self.execute(task)
                except Exception as e:  # noqa: BLE001
                    log(f"[{self.name_}] task {task['id']} crashed: {e}")
                    traceback.print_exc()
                    self._finish(task["id"], "failed", error=f"runner crash: {e}")
                self.current = None
                self.heartbeat("idle")
                last_hb = time.time()
            elif time.time() - last_hb > 30:
                self.heartbeat("idle")
                last_hb = time.time()

    def _finish(self, task_id: str, status: str, result: str | None = None, error: str | None = None, meta: dict | None = None) -> None:
        for attempt in range(60):  # ~10 minutes: the hub may be restarting
            try:
                self.client.post(f"/api/tasks/{task_id}/finish", {"status": status, "result": result, "error": error, "meta": meta or {}})
                return
            except Exception as e:  # noqa: BLE001
                log(f"[{self.name_}] finish failed ({attempt}): {e}")
                time.sleep(min(10, 2 * (attempt + 1)))

    def execute(self, task: dict[str, Any]) -> None:
        adapter = ADAPTERS[self.kind]
        workdir = task.get("workdir")
        if workdir:
            workdir = os.path.expanduser(workdir)
            if not os.path.isabs(workdir) and self.workdir_root:
                workdir = os.path.join(os.path.expanduser(self.workdir_root), workdir)
            if not os.path.isdir(workdir):
                log(f"[{self.name_}] workdir missing, using home: {workdir}")
                workdir = None
        log(f"[{self.name_}] task {task['id']} '{task['title']}' cwd={workdir or '-'}")
        res = AdapterResult()
        buf: list[dict[str, Any]] = []
        last_flush = time.time()
        started = time.time()

        def flush() -> None:
            nonlocal last_flush
            if not buf:
                return
            items = [{"task_id": task["id"], "actor": self.name_, **m, "ts": m.get("ts") or now_iso()} for m in buf]
            buf.clear()
            try:
                self.client.post("/api/messages", {"items": items})
            except Exception as e:  # noqa: BLE001
                log(f"[{self.name_}] message flush failed: {e}")
            last_flush = time.time()

        cfg = {**self.cfg, "name": self.name_}
        if task["meta"].get("model"):
            cfg["model"] = task["meta"]["model"]
        stop_watch = threading.Event()

        def watch_cancel() -> None:
            while not stop_watch.wait(10):
                try:
                    st = self.client.get(f"/api/tasks/{task['id']}")["task"]["status"]
                except Exception:  # noqa: BLE001
                    continue
                if st != "running":
                    res.cancelled = True
                    log(f"[{self.name_}] task {task['id']} is {st} on hub -> killing subprocess")
                    if res.proc is not None:
                        try:
                            res.proc.kill()
                        except Exception:  # noqa: BLE001
                            pass
                    return

        threading.Thread(target=watch_cancel, daemon=True).start()
        try:
            for msg in adapter(task["prompt"], workdir, cfg, res):
                msg.setdefault("ts", now_iso())
                buf.append(msg)
                if len(buf) >= 20 or time.time() - last_flush >= self.flush_interval:
                    flush()
        finally:
            stop_watch.set()
            flush()
        if res.cancelled:
            log(f"[{self.name_}] task {task['id']} cancelled")
            return
        meta = {"exit_code": res.exit_code, "session_id": res.session_id, "usage": res.usage,
                "duration_s": round(time.time() - started, 1), "host": self.host, "kind": self.kind}
        if res.exit_code not in (0, None) and not res.final:
            self._finish(task["id"], "failed", error=f"exit code {res.exit_code}", meta=meta)
        elif not res.final:
            self._finish(task["id"], "failed", error="agent produced no final answer", meta=meta)
        else:
            self._finish(task["id"], "done", result=res.final, meta=meta)
        log(f"[{self.name_}] task {task['id']} finished exit={res.exit_code} in {meta['duration_s']}s")


def load_config(path: str | None) -> dict[str, Any]:
    load_dotenv()
    load_dotenv(Path.home() / ".agent-hub" / "runner.env")
    cfg: dict[str, Any] = {}
    if path:
        cfg = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    else:
        for cand in (Path.cwd() / "runner.json", Path.home() / ".agent-hub" / "runner.json"):
            if cand.is_file():
                cfg = json.loads(cand.read_text(encoding="utf-8"))
                break
    cfg.setdefault("hub", os.environ.get("HUB_URL", "http://127.0.0.1:8765"))
    cfg.setdefault("token", os.environ.get("HUB_TOKEN"))
    cfg.setdefault("host", socket.gethostname().split(".")[0])
    cfg.setdefault("agents", [])
    return cfg


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="agent-hub runner")
    ap.add_argument("-c", "--config", help="runner.json path")
    ap.add_argument("--agent", action="append", help="ad-hoc agent spec NAME=KIND (e.g. claude-main=claude)")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    for spec in args.agent or []:
        name, _, kind = spec.partition("=")
        cfg["agents"].append({"name": name, "kind": kind or "claude"})
    if not cfg["agents"]:
        ap.error("no agents configured (runner.json 'agents' or --agent NAME=KIND)")
    client = HubClient(cfg["hub"], cfg.get("token"))
    client.get("/api/health")
    workers = [AgentWorker(client, cfg["host"], a, float(cfg.get("flush_interval", 1.0)), cfg.get("workdir_root")) for a in cfg["agents"]]
    log(f"runner on {cfg['host']} -> {cfg['hub']} agents={[w.name_ for w in workers]}")
    for w in workers:
        w.start()
    try:
        while any(w.is_alive() for w in workers):
            time.sleep(1)
    except KeyboardInterrupt:
        log("stopping")


if __name__ == "__main__":
    main()
