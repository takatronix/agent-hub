"""Deterministic orchestration recipes.

A recipe is a small state machine stored in run.state. The hub advances it whenever a
task of that run finishes (see Orchestrator.on_task_finished). No AI is involved in the
control flow itself — the orchestrating intelligence lives in the prompts and in the
Claude Code session that calls the MCP tools.
"""
from __future__ import annotations

from typing import Any

from .store import Store
from .util import truncate

SOLVE_PROMPT = """あなたは「{agent}」として、次の課題に独立して取り組みます。他のエージェントも同じ課題に並行して取り組んでいます。

# 課題
{prompt}

# 出力ルール
- 最後に必ず「## 結論」見出しを置き、あなたの回答・解決策・変更内容・検証結果を自己完結でまとめてください（他のエージェントがこの「結論」だけを読んでレビューします）。
- 不確かな点・リスク・未検証の箇所は正直に書いてください。
"""

REVIEW_PROMPT = """あなたは「{agent}」として、他のエージェントの回答をレビューします。元の課題は以下です。

# 課題
{prompt}

# あなた自身の回答（参考）
{own}

# レビュー対象
{others}

# 出力ルール
各回答について、以下を書いてください:
- 正しさ: 事実誤認・論理の穴・バグ・見落とし（具体的に、該当箇所を引用して）
- 自分の回答との差分: 相手の方が優れている点／劣っている点
- スコア: 1〜10（根拠つき）
最後に「## 総評」として、どの回答を採用・統合すべきかの推奨を書いてください。
コードを実際に動かして検証できるなら、して構いません（作業ディレクトリ内のみ）。
"""

SYNTH_PROMPT = """あなたは「{agent}」として、複数エージェントの回答とその相互レビューをすべて読み、最終回答を作ります。

# 課題
{prompt}

# 各エージェントの回答
{solutions}

# 相互レビュー
{reviews}

# 出力ルール
- 「## 最終回答」: レビューで指摘された問題を取り込み、最良の要素を統合した最終的な回答・手順・コード。
- 「## 判断の根拠」: どの意見を採用し、どれを退けたか、なぜか。
- 「## 残る不確実性」: 人間が確認すべき点。
"""


def _label(task: dict[str, Any]) -> str:
    return task["meta"].get("label") or task["agent"]


def _result(task: dict[str, Any], limit: int = 24000) -> str:
    if task["status"] != "done":
        return f"(このエージェントは失敗しました: {task.get('error') or task['status']})"
    return truncate(task.get("result") or "(空の回答)", limit)


class Orchestrator:
    def __init__(self, store: Store):
        self.store = store

    # ---- public entry points --------------------------------------------------
    def start(self, recipe: str, project: str, title: str, spec: dict[str, Any], created_by: str = "") -> dict[str, Any]:
        if recipe == "review_panel":
            return self._start_review_panel(project, title, spec, created_by)
        if recipe == "single":
            return self._start_single(project, title, spec, created_by)
        if recipe == "parallel":
            return self._start_parallel(project, title, spec, created_by)
        raise ValueError(f"unknown recipe: {recipe}")

    def on_task_finished(self, task: dict[str, Any]) -> None:
        run_id = task.get("run_id")
        if not run_id:
            return
        # Hold the store lock for the whole check-and-advance so two task finishes that land
        # at the same moment cannot both advance the phase (= duplicate review/synth tasks).
        with self.store.lock:
            run = self.store.get_run(run_id)
            if not run or run["status"] != "running":
                return
            tasks = self.store.list_tasks(run_id=run_id, limit=500)
            if any(t["status"] in ("queued", "running") for t in tasks):
                return  # wait for the rest of the current phase
            handler = getattr(self, f"_advance_{run['recipe']}", None)
            if handler:
                handler(run, tasks)

    def cancel(self, run_id: str) -> dict[str, Any]:
        self.store.cancel_queued(run_id)
        return self.store.update_run(run_id, status="cancelled")

    # ---- single ---------------------------------------------------------------
    def _start_single(self, project, title, spec, created_by):
        run = self.store.create_run(project, title, "single", spec, created_by, state={"phase": "run"})
        self.store.create_task(project, title, spec["prompt"], spec["agent"], run_id=run["id"],
                               step="run", workdir=spec.get("workdir"), meta={"label": spec.get("label")})
        return run

    def _advance_single(self, run, tasks):
        t = tasks[0]
        status = "done" if t["status"] == "done" else "failed"
        self.store.update_run(run["id"], status=status, summary=_result(t, 8000), state={"phase": "finished"})

    # ---- parallel (same prompt to N agents, no review) --------------------------
    def _start_parallel(self, project, title, spec, created_by):
        run = self.store.create_run(project, title, "parallel", spec, created_by, state={"phase": "run"})
        for agent in spec["agents"]:
            self.store.create_task(project, f"{title} [{agent}]", spec["prompt"], agent, run_id=run["id"],
                                   step="run", workdir=spec.get("workdir"))
        return run

    def _advance_parallel(self, run, tasks):
        ok = [t for t in tasks if t["status"] == "done"]
        summary = "\n\n".join(f"### {_label(t)}\n{_result(t, 6000)}" for t in tasks)
        self.store.update_run(run["id"], status="done" if ok else "failed", summary=summary, state={"phase": "finished"})

    # ---- review_panel (solve -> cross review -> synthesize) ----------------------
    def _start_review_panel(self, project, title, spec, created_by):
        solvers = list(spec["solvers"])
        if len(solvers) < 2:
            raise ValueError("review_panel needs at least 2 solvers")
        spec = {
            **spec,
            "solvers": solvers,
            "reviewers": list(spec.get("reviewers") or solvers),
            "synthesizer": spec.get("synthesizer") or solvers[0],
        }
        run = self.store.create_run(project, title, "review_panel", spec, created_by, state={"phase": "solve"})
        self.store.add_message(actor="hub", role="system", run_id=run["id"],
                               content=f"三者評価を開始: solvers={solvers} reviewers={spec['reviewers']} synthesizer={spec['synthesizer']}")
        for agent in solvers:
            self.store.create_task(project, f"解く [{agent}]", SOLVE_PROMPT.format(agent=agent, prompt=spec["prompt"]),
                                   agent, run_id=run["id"], step="solve", workdir=spec.get("workdir"))
        return run

    def _advance_review_panel(self, run, tasks):
        spec, state = run["spec"], run["state"]
        phase = state.get("phase")
        by_step: dict[str, list[dict[str, Any]]] = {}
        for t in tasks:
            by_step.setdefault(t["step"], []).append(t)

        if phase == "solve":
            solved = [t for t in by_step.get("solve", []) if t["status"] == "done"]
            if len(solved) < 2:
                self._fail(run, "2つ以上の回答が得られなかったためレビューを中止")
                return
            self.store.update_run(run["id"], state={**state, "phase": "review"})
            self.store.add_message(actor="hub", role="system", run_id=run["id"],
                                   content=f"解答フェーズ完了 ({len(solved)}/{len(by_step['solve'])} 成功)。相互レビューを開始。")
            own_by_agent = {t["agent"]: t for t in by_step["solve"]}
            for reviewer in spec["reviewers"]:
                own = own_by_agent.get(reviewer)
                others = [t for t in solved if t["agent"] != reviewer]
                if not others:
                    continue
                prompt = REVIEW_PROMPT.format(
                    agent=reviewer, prompt=spec["prompt"],
                    own=_result(own) if own else "(あなたは解答フェーズに参加していません)",
                    others="\n\n".join(f"## 回答 by {_label(t)}\n{_result(t)}" for t in others),
                )
                self.store.create_task(run["project"], f"レビュー [{reviewer}]", prompt, reviewer,
                                       run_id=run["id"], step="review", workdir=spec.get("workdir"))
            return

        if phase == "review":
            solved = [t for t in by_step.get("solve", []) if t["status"] == "done"]
            reviews = [t for t in by_step.get("review", []) if t["status"] == "done"]
            self.store.update_run(run["id"], state={**state, "phase": "synthesize"})
            self.store.add_message(actor="hub", role="system", run_id=run["id"],
                                   content=f"レビューフェーズ完了 ({len(reviews)} 件)。{spec['synthesizer']} が統合します。")
            prompt = SYNTH_PROMPT.format(
                agent=spec["synthesizer"], prompt=spec["prompt"],
                solutions="\n\n".join(f"## 回答 by {_label(t)}\n{_result(t, 16000)}" for t in solved),
                reviews="\n\n".join(f"## レビュー by {_label(t)}\n{_result(t, 12000)}" for t in reviews)
                or "(レビューなし)",
            )
            self.store.create_task(run["project"], f"統合 [{spec['synthesizer']}]", prompt, spec["synthesizer"],
                                   run_id=run["id"], step="synthesize", workdir=spec.get("workdir"))
            return

        if phase == "synthesize":
            synth = by_step.get("synthesize", [])
            t = synth[0] if synth else None
            if t and t["status"] == "done":
                self.store.update_run(run["id"], status="done", summary=t["result"] or "", state={**state, "phase": "finished"})
                self.store.add_message(actor="hub", role="system", run_id=run["id"], content="三者評価 完了。")
            else:
                self._fail(run, f"統合に失敗: {t.get('error') if t else 'no task'}")

    def _fail(self, run, reason: str) -> None:
        self.store.add_message(actor="hub", role="system", run_id=run["id"], content=reason)
        self.store.update_run(run["id"], status="failed", summary=reason, state={**run["state"], "phase": "finished"})
