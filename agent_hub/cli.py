"""hubctl: small CLI for humans."""
from __future__ import annotations

import argparse
import json
import sys
import time

from .client import HubClient
from .util import load_dotenv


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(prog="hubctl")
    ap.add_argument("--hub", help="hub url (default $HUB_URL)")
    ap.add_argument("--token", help="token (default $HUB_TOKEN)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("agents")
    sub.add_parser("runs").add_argument("--project")
    p = sub.add_parser("run"); p.add_argument("run_id"); p.add_argument("--results", action="store_true")
    p = sub.add_parser("dispatch"); p.add_argument("agent"); p.add_argument("prompt"); p.add_argument("--workdir"); p.add_argument("--project", default="default"); p.add_argument("--no-wait", action="store_true")
    p = sub.add_parser("panel", help="review_panel"); p.add_argument("prompt"); p.add_argument("--solvers", required=True, help="comma separated"); p.add_argument("--reviewers"); p.add_argument("--synthesizer"); p.add_argument("--workdir"); p.add_argument("--project", default="default"); p.add_argument("--title"); p.add_argument("--no-wait", action="store_true")
    p = sub.add_parser("parallel"); p.add_argument("prompt"); p.add_argument("--agents", required=True); p.add_argument("--workdir"); p.add_argument("--project", default="default"); p.add_argument("--no-wait", action="store_true")
    p = sub.add_parser("cancel"); p.add_argument("run_id")
    p = sub.add_parser("transcript"); p.add_argument("task_id")
    a = ap.parse_args(argv)
    c = HubClient(a.hub, a.token)

    def show(v):
        print(json.dumps(v, ensure_ascii=False, indent=1))

    def wait(run):
        print(f"run {run['id']} -> {c.url}/runs/{run['id']}", file=sys.stderr)
        if getattr(a, "no_wait", False):
            return run
        while run["status"] == "running":
            time.sleep(3)
            run = c.get(f"/api/runs/{run['id']}")["run"]
            busy = [f"{t['step']}/{t['agent']}:{t['status']}" for t in run["tasks"] if t["status"] != "done"]
            print(f"  [{run['state'].get('phase')}] {' '.join(busy)}", file=sys.stderr)
        print(f"== {run['status']} ==", file=sys.stderr)
        print(run["summary"])
        return run

    if a.cmd == "agents":
        for x in c.get("/api/agents")["agents"]:
            print(f"{'●' if x['online'] else '○'} {x['name']:<16} {x['kind']:<8} {x['host']:<12} {x['status']}")
    elif a.cmd == "runs":
        for r in c.get("/api/runs" + (f"?project={a.project}" if a.project else ""))["runs"]:
            print(f"{r['id']}  {r['status']:<9} {r['recipe']:<13} {r['created_at'][:19]}  {r['title'][:60]}")
    elif a.cmd == "run":
        run = c.get(f"/api/runs/{a.run_id}")["run"]
        if a.results:
            for t in run["tasks"]:
                print(f"\n##### {t['step']} / {t['agent']} [{t['status']}]\n{t.get('result') or t.get('error') or ''}")
        else:
            show({k: run[k] for k in ("id", "title", "recipe", "status", "state", "created_at")}); print(run["summary"])
    elif a.cmd == "dispatch":
        wait(c.post("/api/runs", {"recipe": "single", "project": a.project, "title": a.prompt[:60], "created_by": "hubctl",
                                  "spec": {"prompt": a.prompt, "agent": a.agent, "workdir": a.workdir}})["run"])
    elif a.cmd == "panel":
        spec = {"prompt": a.prompt, "solvers": a.solvers.split(","), "workdir": a.workdir,
                "reviewers": a.reviewers.split(",") if a.reviewers else None, "synthesizer": a.synthesizer}
        wait(c.post("/api/runs", {"recipe": "review_panel", "project": a.project, "title": a.title or a.prompt[:60], "created_by": "hubctl", "spec": spec})["run"])
    elif a.cmd == "parallel":
        wait(c.post("/api/runs", {"recipe": "parallel", "project": a.project, "title": a.prompt[:60], "created_by": "hubctl",
                                  "spec": {"prompt": a.prompt, "agents": a.agents.split(","), "workdir": a.workdir}})["run"])
    elif a.cmd == "cancel":
        show(c.post(f"/api/runs/{a.run_id}/cancel", {}))
    elif a.cmd == "transcript":
        for m in c.get(f"/api/tasks/{a.task_id}")["task"]["messages"]:
            print(f"--- [{m['role']}] {m['ts']}\n{m['content']}")


if __name__ == "__main__":
    main()
