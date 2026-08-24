from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable

from .util import dumps, loads, new_id, now_iso, now_ts

TASK_STATUSES = ("queued", "running", "done", "failed", "cancelled")
RUN_STATUSES = ("running", "done", "failed", "cancelled")

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  name TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agents (
  name TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  host TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'idle',
  current_task TEXT,
  meta TEXT NOT NULL DEFAULT '{}',
  last_seen REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  project TEXT NOT NULL,
  title TEXT NOT NULL,
  recipe TEXT NOT NULL,
  status TEXT NOT NULL,
  spec TEXT NOT NULL DEFAULT '{}',
  state TEXT NOT NULL DEFAULT '{}',
  summary TEXT NOT NULL DEFAULT '',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  run_id TEXT,
  project TEXT NOT NULL,
  step TEXT NOT NULL DEFAULT 'task',
  title TEXT NOT NULL,
  prompt TEXT NOT NULL,
  agent TEXT NOT NULL,
  workdir TEXT,
  status TEXT NOT NULL,
  claimed_by TEXT,
  result TEXT,
  error TEXT,
  meta TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_status_agent ON tasks(status, agent);
CREATE INDEX IF NOT EXISTS idx_tasks_run ON tasks(run_id);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT,
  run_id TEXT,
  ts TEXT NOT NULL,
  actor TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_messages_run ON messages(run_id, id);
CREATE INDEX IF NOT EXISTS idx_messages_task ON messages(task_id, id);
CREATE TABLE IF NOT EXISTS artifacts (
  id TEXT PRIMARY KEY,
  task_id TEXT,
  run_id TEXT,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  path TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
"""


class _Rows:
    """Materialized query result (safe to use after the connection lock is released)."""

    def __init__(self, rows: list[sqlite3.Row], lastrowid: int | None, rowcount: int):
        self._rows, self.lastrowid, self.rowcount = rows, lastrowid, rowcount

    def fetchone(self) -> sqlite3.Row | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[sqlite3.Row]:
        return self._rows


class _LockedConn:
    """Serializes every statement on one sqlite3 connection (the connection itself is not thread-safe)."""

    def __init__(self, conn: sqlite3.Connection, lock: threading.RLock):
        self._conn, self._lock = conn, lock

    def execute(self, sql: str, args: Any = ()) -> _Rows:
        with self._lock:
            cur = self._conn.execute(sql, args)
            rows = cur.fetchall() if cur.description else []
            return _Rows(rows, cur.lastrowid, cur.rowcount)

    def executescript(self, sql: str) -> None:
        with self._lock:
            self._conn.executescript(sql)


class Store:
    """SQLite-backed ledger. Every statement is serialized by one RLock; multi-statement
    operations (claim, finish, recipe advance) hold the same lock via `self.lock`."""

    def __init__(self, db_path: str | Path, artifact_dir: str | Path | None = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_dir = Path(artifact_dir) if artifact_dir else self.db_path.parent / "artifacts"
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        raw = sqlite3.connect(str(self.db_path), check_same_thread=False, isolation_level=None)
        raw.row_factory = sqlite3.Row
        self._conn = _LockedConn(raw, self._lock)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self.listeners: list[Callable[[dict[str, Any]], None]] = []

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    # -- events (SSE fan-out) -------------------------------------------------
    def emit(self, event: str, payload: dict[str, Any]) -> None:
        for fn in list(self.listeners):
            try:
                fn({"event": event, **payload})
            except Exception:  # pragma: no cover - listener errors must not break writes
                pass

    # -- projects -------------------------------------------------------------
    def ensure_project(self, name: str, title: str | None = None, description: str = "") -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM projects WHERE name=?", (name,)).fetchone()
            if row:
                return dict(row)
            self._conn.execute(
                "INSERT INTO projects(name,title,description,created_at) VALUES(?,?,?,?)",
                (name, title or name, description, now_iso()),
            )
            return dict(self._conn.execute("SELECT * FROM projects WHERE name=?", (name,)).fetchone())

    def list_projects(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT p.*, (SELECT COUNT(*) FROM runs r WHERE r.project=p.name) AS run_count "
            "FROM projects p ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # -- agents ---------------------------------------------------------------
    def heartbeat(self, name: str, kind: str, host: str = "", status: str = "idle",
                  current_task: str | None = None, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            self._conn.execute(
                "INSERT INTO agents(name,kind,host,status,current_task,meta,last_seen) VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET kind=excluded.kind, host=excluded.host, status=excluded.status, "
                "current_task=excluded.current_task, meta=excluded.meta, last_seen=excluded.last_seen",
                (name, kind, host, status, current_task, dumps(meta or {}), now_ts()),
            )
            agent = self.get_agent(name)
        self.emit("agent", {"agent": agent})
        return agent

    def delete_agent(self, name: str) -> bool:
        with self._lock:
            return self._conn.execute("DELETE FROM agents WHERE name=?", (name,)).rowcount > 0

    def get_agent(self, name: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM agents WHERE name=?", (name,)).fetchone()
        return self._agent(row) if row else None

    def list_agents(self, online_within: float = 90.0) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM agents ORDER BY name").fetchall()
        out = []
        for r in rows:
            a = self._agent(r)
            a["online"] = (now_ts() - a["last_seen"]) < online_within
            out.append(a)
        return out

    def _agent(self, row: sqlite3.Row) -> dict[str, Any]:
        a = dict(row)
        a["meta"] = loads(a["meta"], {})
        return a

    # -- runs -----------------------------------------------------------------
    def create_run(self, project: str, title: str, recipe: str, spec: dict[str, Any],
                   created_by: str = "", state: dict[str, Any] | None = None) -> dict[str, Any]:
        self.ensure_project(project)
        rid = new_id("run")
        ts = now_iso()
        with self._lock:
            self._conn.execute(
                "INSERT INTO runs(id,project,title,recipe,status,spec,state,created_by,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (rid, project, title, recipe, "running", dumps(spec), dumps(state or {}), created_by, ts, ts),
            )
        run = self.get_run(rid)
        self.emit("run", {"run": run})
        return run

    def update_run(self, run_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {"status", "state", "summary", "title"}
        sets, vals = [], []
        for k, v in fields.items():
            if k not in allowed:
                raise ValueError(f"cannot update run.{k}")
            sets.append(f"{k}=?")
            vals.append(dumps(v) if k == "state" else v)
        sets.append("updated_at=?")
        vals.append(now_iso())
        vals.append(run_id)
        with self._lock:
            self._conn.execute(f"UPDATE runs SET {', '.join(sets)} WHERE id=?", vals)
        run = self.get_run(run_id)
        self.emit("run", {"run": run})
        return run

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return self._run(row) if row else None

    def list_runs(self, project: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        q = "SELECT * FROM runs"
        args: list[Any] = []
        if project:
            q += " WHERE project=?"
            args.append(project)
        q += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        return [self._run(r) for r in self._conn.execute(q, args).fetchall()]

    def _run(self, row: sqlite3.Row) -> dict[str, Any]:
        r = dict(row)
        r["spec"] = loads(r["spec"], {})
        r["state"] = loads(r["state"], {})
        return r

    # -- tasks ----------------------------------------------------------------
    def create_task(self, project: str, title: str, prompt: str, agent: str, *, run_id: str | None = None,
                    step: str = "task", workdir: str | None = None, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        self.ensure_project(project)
        tid = new_id("task")
        ts = now_iso()
        with self._lock:
            self._conn.execute(
                "INSERT INTO tasks(id,run_id,project,step,title,prompt,agent,workdir,status,meta,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (tid, run_id, project, step, title, prompt, agent, workdir, "queued", dumps(meta or {}), ts, ts),
            )
        task = self.get_task(tid)
        self.emit("task", {"task": task})
        return task

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return self._task(row) if row else None

    def list_tasks(self, *, run_id: str | None = None, status: str | None = None, agent: str | None = None,
                   project: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        q, args = "SELECT * FROM tasks WHERE 1=1", []
        for col, val in (("run_id", run_id), ("status", status), ("agent", agent), ("project", project)):
            if val:
                q += f" AND {col}=?"
                args.append(val)
        q += " ORDER BY created_at ASC LIMIT ?"
        args.append(limit)
        return [self._task(r) for r in self._conn.execute(q, args).fetchall()]

    def claim_next(self, agent_names: list[str], claimed_by: str) -> dict[str, Any] | None:
        """Atomically claim the oldest queued task addressed to any of agent_names."""
        if not agent_names:
            return None
        with self._lock:
            marks = ",".join("?" * len(agent_names))
            row = self._conn.execute(
                f"SELECT id FROM tasks WHERE status='queued' AND agent IN ({marks}) ORDER BY created_at ASC LIMIT 1",
                agent_names,
            ).fetchone()
            if not row:
                return None
            ts = now_iso()
            self._conn.execute(
                "UPDATE tasks SET status='running', claimed_by=?, started_at=?, updated_at=? WHERE id=? AND status='queued'",
                (claimed_by, ts, ts, row["id"]),
            )
            task = self.get_task(row["id"])
        self.emit("task", {"task": task})
        return task

    def finish_task(self, task_id: str, status: str, result: str | None = None, error: str | None = None,
                    meta_update: dict[str, Any] | None = None) -> dict[str, Any]:
        if status not in ("done", "failed", "cancelled"):
            raise ValueError("finish status must be done/failed/cancelled")
        with self._lock:
            task = self.get_task(task_id)
            if not task:
                raise KeyError(task_id)
            if task["status"] == "cancelled":  # cancelled while the runner was still working: keep it cancelled
                return task
            meta = {**task["meta"], **(meta_update or {})}
            ts = now_iso()
            self._conn.execute(
                "UPDATE tasks SET status=?, result=?, error=?, meta=?, finished_at=?, updated_at=? WHERE id=?",
                (status, result, error, dumps(meta), ts, ts, task_id),
            )
            task = self.get_task(task_id)
        self.emit("task", {"task": task})
        return task

    def requeue_task(self, task_id: str, reason: str) -> dict[str, Any]:
        """Put a running task back in the queue (or fail it if it was already retried once)."""
        with self._lock:
            task = self.get_task(task_id)
            if not task or task["status"] != "running":
                return task
            retries = int(task["meta"].get("retries", 0))
            meta = {**task["meta"], "retries": retries + 1, "last_reason": reason}
            ts = now_iso()
            if retries >= 1:
                self._conn.execute("UPDATE tasks SET status='failed', error=?, meta=?, finished_at=?, updated_at=? WHERE id=?",
                                   (f"lost twice: {reason}", dumps(meta), ts, ts, task_id))
            else:
                self._conn.execute("UPDATE tasks SET status='queued', claimed_by=NULL, started_at=NULL, meta=?, updated_at=? WHERE id=?",
                                   (dumps(meta), ts, task_id))
            task = self.get_task(task_id)
        self.emit("task", {"task": task})
        return task

    def cancel_queued(self, run_id: str) -> int:
        """Cancel queued AND running tasks of a run; runners notice and kill their subprocess."""
        with self._lock:
            ids = [r["id"] for r in self._conn.execute(
                "SELECT id FROM tasks WHERE run_id=? AND status IN ('queued','running')", (run_id,)).fetchall()]
            cur = self._conn.execute(
                "UPDATE tasks SET status='cancelled', finished_at=?, updated_at=? WHERE run_id=? AND status IN ('queued','running')",
                (now_iso(), now_iso(), run_id),
            )
        for tid in ids:
            self.emit("task", {"task": self.get_task(tid)})
        return cur.rowcount

    def _task(self, row: sqlite3.Row) -> dict[str, Any]:
        t = dict(row)
        t["meta"] = loads(t["meta"], {})
        return t

    # -- messages -------------------------------------------------------------
    def add_message(self, *, actor: str, role: str, content: str = "", data: dict[str, Any] | None = None,
                    task_id: str | None = None, run_id: str | None = None, ts: str | None = None) -> dict[str, Any]:
        if task_id and not run_id:
            t = self.get_task(task_id)
            run_id = t["run_id"] if t else None
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO messages(task_id,run_id,ts,actor,role,content,data) VALUES(?,?,?,?,?,?,?)",
                (task_id, run_id, ts or now_iso(), actor, role, content, dumps(data or {})),
            )
            msg = self._msg(self._conn.execute("SELECT * FROM messages WHERE id=?", (cur.lastrowid,)).fetchone())
        self.emit("message", {"message": msg})
        return msg

    def add_messages(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.add_message(**it) for it in items]

    def list_messages(self, *, run_id: str | None = None, task_id: str | None = None, after_id: int = 0,
                      limit: int = 2000) -> list[dict[str, Any]]:
        q, args = "SELECT * FROM messages WHERE id>?", [after_id]
        if run_id:
            q += " AND run_id=?"
            args.append(run_id)
        if task_id:
            q += " AND task_id=?"
            args.append(task_id)
        q += " ORDER BY id ASC LIMIT ?"
        args.append(limit)
        return [self._msg(r) for r in self._conn.execute(q, args).fetchall()]

    def _msg(self, row: sqlite3.Row) -> dict[str, Any]:
        m = dict(row)
        m["data"] = loads(m["data"], {})
        return m

    # -- artifacts ------------------------------------------------------------
    def add_artifact(self, *, kind: str, name: str, content: str | bytes, summary: str = "",
                     task_id: str | None = None, run_id: str | None = None) -> dict[str, Any]:
        aid = new_id("art")
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)[:80] or "artifact"
        path = self.artifact_dir / f"{aid}_{safe}"
        if isinstance(content, str):
            path.write_text(content, encoding="utf-8")
        else:
            path.write_bytes(content)
        if task_id and not run_id:
            t = self.get_task(task_id)
            run_id = t["run_id"] if t else None
        with self._lock:
            self._conn.execute(
                "INSERT INTO artifacts(id,task_id,run_id,kind,name,path,summary,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (aid, task_id, run_id, kind, name, str(path), summary, now_iso()),
            )
            art = dict(self._conn.execute("SELECT * FROM artifacts WHERE id=?", (aid,)).fetchone())
        self.emit("artifact", {"artifact": art})
        return art

    def get_artifact(self, art_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM artifacts WHERE id=?", (art_id,)).fetchone()
        return dict(row) if row else None

    def list_artifacts(self, *, run_id: str | None = None, task_id: str | None = None) -> list[dict[str, Any]]:
        q, args = "SELECT * FROM artifacts WHERE 1=1", []
        if run_id:
            q += " AND run_id=?"
            args.append(run_id)
        if task_id:
            q += " AND task_id=?"
            args.append(task_id)
        return [dict(r) for r in self._conn.execute(q + " ORDER BY created_at", args).fetchall()]

    # -- aggregate ------------------------------------------------------------
    def run_detail(self, run_id: str) -> dict[str, Any] | None:
        run = self.get_run(run_id)
        if not run:
            return None
        run["tasks"] = self.list_tasks(run_id=run_id, limit=500)
        run["artifacts"] = self.list_artifacts(run_id=run_id)
        return run
