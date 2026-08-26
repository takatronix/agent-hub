from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .recipes import Orchestrator
from . import league
from .store import Store
from .util import load_dotenv
from . import ui


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class Hub:
    """Shared state for all request handler threads."""

    def __init__(self, store: Store, token: str | None, read_token: str | None, reaper: bool = True):
        self.store = store
        self.token = token or None
        self.read_token = read_token or None
        self.orch = Orchestrator(store)
        self.subscribers: list[tuple[str | None, queue.Queue]] = []
        self.wakeup = threading.Condition()
        store.listeners.append(self._on_event)
        if reaper:
            threading.Thread(target=self._reaper, daemon=True, name="reaper").start()

    def reap_lost_tasks(self, agent_grace: float = 120.0, offline_after: float = 600.0) -> list[str]:
        """A running task is 'lost' when its agent heartbeats as idle on something else, or has been
        offline for a long time (runner restart, hub restart mid-claim, machine reboot)."""
        lost = []
        now = time.time()
        for task in self.store.list_tasks(status="running", limit=500):
            agent = self.store.get_agent(task["agent"])
            started = task.get("started_at") or ""
            try:
                age = now - datetime.fromisoformat(started.replace("Z", "+00:00")).timestamp()
            except ValueError:
                age = 0
            if age < agent_grace:
                continue
            reason = None
            if agent is None or now - agent["last_seen"] > offline_after:
                reason = "agent offline"
            elif now - agent["last_seen"] < 90 and agent["status"] == "idle" and agent.get("current_task") != task["id"]:
                reason = "agent idle without this task"
            if reason:
                t = self.store.requeue_task(task["id"], reason)
                self.store.add_message(actor="hub", role="system", task_id=task["id"], run_id=task.get("run_id"),
                                       content=f"タスクを回収: {reason} → {t['status']}")
                if t["status"] == "failed":
                    self.orch.on_task_finished(t)
                lost.append(task["id"])
        return lost

    def _reaper(self) -> None:
        while True:
            time.sleep(60)
            try:
                self.reap_lost_tasks()
            except Exception as e:  # noqa: BLE001
                print(f"reaper error: {e}", flush=True)

    def _on_event(self, event: dict[str, Any]) -> None:
        run_id = None
        for key in ("run", "task", "message", "artifact"):
            if key in event:
                run_id = event[key].get("run_id") or (event[key].get("id") if key == "run" else None)
                break
        for want, q in list(self.subscribers):
            if want is None or want == run_id:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    pass
        if event["event"] == "task":
            with self.wakeup:
                self.wakeup.notify_all()


class Handler(BaseHTTPRequestHandler):
    hub: Hub  # injected via server
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.environ.get("HUB_LOG"):
            super().log_message(fmt, *args)

    # -- plumbing -----------------------------------------------------------
    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        url = urlsplit(self.path)
        path, query = url.path, parse_qs(url.query)
        try:
            if not self._authorized(method, path, query):
                raise ApiError(401, "unauthorized")
            if path.startswith("/api/"):
                self._api(method, path, query)
            elif method == "GET":
                self._html(path, query)
            else:
                raise ApiError(404, "not found")
        except ApiError as e:
            self._json({"error": e.message}, e.status)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # noqa: BLE001
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def _authorized(self, method: str, path: str, query: dict) -> bool:
        hub = self.hub
        if path in ("/api/health",):
            return True
        presented = None
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            presented = auth[7:].strip()
        presented = presented or self.headers.get("X-Hub-Token") or (query.get("token") or [None])[0]
        is_read = method == "GET" or path == "/api/stream"
        if hub.token is None:
            return True
        if presented == hub.token:
            return True
        if is_read and hub.read_token and presented == hub.read_token:
            return True
        return False

    def _body(self) -> dict[str, Any]:
        n = int(self.headers.get("Content-Length") or 0)
        if n == 0:
            return {}
        raw = self.rfile.read(n)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as e:
            raise ApiError(400, f"invalid json: {e}")
        if not isinstance(data, dict):
            raise ApiError(400, "body must be an object")
        return data

    def _json(self, value: Any, status: int = 200) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _raw(self, body: bytes, ctype: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # -- HTML ---------------------------------------------------------------
    def _html(self, path: str, query: dict) -> None:
        if path == "/" or path.startswith("/runs/") or path.startswith("/projects/"):
            self._raw(ui.INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
        else:
            raise ApiError(404, "not found")

    # -- API ----------------------------------------------------------------
    def _api(self, method: str, path: str, query: dict) -> None:
        st = self.hub.store
        q1 = lambda k, d=None: (query.get(k) or [d])[0]  # noqa: E731
        m = lambda pat: re.fullmatch(pat, path)  # noqa: E731

        if path == "/api/health":
            return self._json({"ok": True, "time": time.time()})
        if path == "/api/projects" and method == "GET":
            return self._json({"projects": st.list_projects()})
        if path == "/api/projects" and method == "POST":
            b = self._body()
            return self._json({"project": st.ensure_project(b["name"], b.get("title"), b.get("description", ""))})
        if path == "/api/agents" and method == "GET":
            return self._json({"agents": st.list_agents()})
        if path == "/api/agents/heartbeat" and method == "POST":
            b = self._body()
            return self._json({"agent": st.heartbeat(b["name"], b.get("kind", "unknown"), b.get("host", ""),
                                                     b.get("status", "idle"), b.get("current_task"), b.get("meta"))})

        if (mm := m(r"/api/agents/([^/]+)/delete")) and method == "POST":
            from urllib.parse import unquote
            ok = st.delete_agent(unquote(mm.group(1)))
            st.emit("agent", {"agent": {"name": unquote(mm.group(1)), "deleted": True}})
            return self._json({"deleted": ok})

        if path == "/api/leaderboard" and method == "GET":
            runs = st.list_runs(limit=1000)
            return self._json({"leaderboard": league.leaderboard(runs), "categories": league.CATEGORIES,
                               "categories_ja": league.CATEGORY_JA})
        if path == "/api/recommend" and method in ("GET", "POST"):
            b = self._body() if method == "POST" else {}
            prompt = b.get("prompt") or q1("prompt", "") or ""
            category = b.get("category") or q1("category") or league.guess_category(prompt)
            k = int(b.get("k") or q1("k", 3))
            online = [a for a in st.list_agents() if a["online"] and a["kind"] != "fake"]
            board = league.leaderboard(st.list_runs(limit=1000))
            return self._json({"recommend": league.recommend(board, category, online, k)})

        if path == "/api/runs" and method == "POST":
            b = self._body()
            for k in ("recipe", "title", "spec"):
                if k not in b:
                    raise ApiError(400, f"missing {k}")
            try:
                run = self.hub.orch.start(b["recipe"], b.get("project") or "default", b["title"], b["spec"],
                                          b.get("created_by", ""))
            except (ValueError, KeyError) as e:
                raise ApiError(400, str(e))
            return self._json({"run": run}, 201)
        if path == "/api/runs" and method == "GET":
            runs = st.list_runs(q1("project"), int(q1("limit", 50)))
            if q1("parent"):
                runs = [r for r in runs if r["spec"].get("parent_run") == q1("parent")]
            return self._json({"runs": runs})
        if (mm := m(r"/api/runs/([^/]+)")) and method == "GET":
            run = st.run_detail(mm.group(1))
            if not run:
                raise ApiError(404, "run not found")
            return self._json({"run": run})
        if (mm := m(r"/api/runs/([^/]+)/messages")) and method == "GET":
            return self._json({"messages": st.list_messages(run_id=mm.group(1), after_id=int(q1("after", 0)),
                                                            limit=int(q1("limit", 5000)))})
        if (mm := m(r"/api/runs/([^/]+)/cancel")) and method == "POST":
            return self._json({"run": self.hub.orch.cancel(mm.group(1))})

        if path == "/api/tasks" and method == "POST":
            b = self._body()
            task = st.create_task(b.get("project") or "default", b.get("title") or b["prompt"][:60], b["prompt"],
                                  b["agent"], workdir=b.get("workdir"), meta=b.get("meta"))
            return self._json({"task": task}, 201)
        if path == "/api/tasks" and method == "GET":
            return self._json({"tasks": st.list_tasks(run_id=q1("run_id"), status=q1("status"), agent=q1("agent"),
                                                      project=q1("project"), limit=int(q1("limit", 100)))})
        if path == "/api/tasks/claim" and method == "POST":
            b = self._body()
            agents, who = list(b.get("agents") or []), b.get("claimed_by", "runner")
            deadline = time.time() + min(float(b.get("wait", 0)), 55.0)
            while True:
                task = st.claim_next(agents, who)
                if task or time.time() >= deadline:
                    return self._json({"task": task})
                with self.hub.wakeup:
                    self.hub.wakeup.wait(timeout=max(0.05, min(5.0, deadline - time.time())))
        if (mm := m(r"/api/tasks/([^/]+)")) and method == "GET":
            task = st.get_task(mm.group(1))
            if not task:
                raise ApiError(404, "task not found")
            task["messages"] = st.list_messages(task_id=task["id"])
            return self._json({"task": task})
        if (mm := m(r"/api/tasks/([^/]+)/finish")) and method == "POST":
            b = self._body()
            try:
                task = st.finish_task(mm.group(1), b.get("status", "done"), b.get("result"), b.get("error"), b.get("meta"))
            except KeyError:
                raise ApiError(404, "task not found")
            self.hub.orch.on_task_finished(task)
            return self._json({"task": task})

        if path == "/api/messages" and method == "POST":
            b = self._body()
            items = b.get("items") or [b]
            out = [st.add_message(task_id=it.get("task_id"), run_id=it.get("run_id"), actor=it.get("actor", "?"),
                                  role=it.get("role", "assistant"), content=it.get("content", ""), data=it.get("data"),
                                  ts=it.get("ts")) for it in items]
            return self._json({"count": len(out), "last_id": out[-1]["id"] if out else None}, 201)

        if path == "/api/artifacts" and method == "POST":
            b = self._body()
            art = st.add_artifact(kind=b.get("kind", "file"), name=b.get("name", "artifact"), content=b.get("content", ""),
                                  summary=b.get("summary", ""), task_id=b.get("task_id"), run_id=b.get("run_id"))
            return self._json({"artifact": art}, 201)
        if (mm := m(r"/api/artifacts/([^/]+)/content")) and method == "GET":
            art = st.get_artifact(mm.group(1))
            if not art:
                raise ApiError(404, "artifact not found")
            return self._raw(Path(art["path"]).read_bytes(), "text/plain; charset=utf-8")

        if path == "/api/stream" and method == "GET":
            return self._sse(q1("run_id"))
        raise ApiError(404, f"no route {method} {path}")

    # -- SSE ----------------------------------------------------------------
    def _sse(self, run_id: str | None) -> None:
        q: queue.Queue = queue.Queue(maxsize=1000)
        self.hub.subscribers.append((run_id, q))
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    ev = q.get(timeout=15)
                    payload = json.dumps(ev, ensure_ascii=False)
                    self.wfile.write(f"event: {ev['event']}\ndata: {payload}\n\n".encode("utf-8"))
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            try:
                self.hub.subscribers.remove((run_id, q))
            except ValueError:
                pass


def make_server(host: str, port: int, hub: Hub) -> ThreadingHTTPServer:
    handler = type("HubHandler", (Handler,), {"hub": hub})
    srv = ThreadingHTTPServer((host, port), handler)
    srv.daemon_threads = True
    return srv


def main() -> None:
    load_dotenv()
    host = os.environ.get("HUB_HOST", "127.0.0.1")
    port = int(os.environ.get("PORT") or os.environ.get("HUB_PORT") or 8765)
    data_dir = Path(os.environ.get("HUB_DATA_DIR") or Path.home() / ".agent-hub")
    store = Store(data_dir / "hub.sqlite3", data_dir / "artifacts")
    hub = Hub(store, os.environ.get("HUB_TOKEN"), os.environ.get("HUB_READ_TOKEN"))
    srv = make_server(host, port, hub)
    print(f"agent-hub listening on http://{host}:{port}  (data: {data_dir}, auth: {'token' if hub.token else 'OPEN'})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
