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
from . import league

SOLVE_PROMPT = """あなたは「{agent}」として、次の課題に独立して取り組みます。他のエージェントも同じ課題に並行して取り組んでいます。

# 課題
{prompt}

# 出力ルール
- 最初の行に `カテゴリ: <algorithm|robotics|debugging|design|docs|math|data|web|infra|other>` と課題の種類を 1 つ書いてください。
- 最後に必ず「## 結論」見出しを置き、あなたの回答・解決策・変更内容・検証結果を自己完結でまとめてください（他のエージェントがこの「結論」だけを読んでレビューします）。
- 不確かな点・リスク・未検証の箇所は正直に書いてください。
"""

REVIEW_PROMPT = """あなたは「{agent}」として、他のエージェントの回答を匿名審査します。元の課題は以下です。
回答者が誰か（どの AI か）は伏せられています。内容だけで公平に評価してください。

# 課題
{prompt}

# あなた自身の回答（参考。採点対象外）
{own}

# 審査対象
{others}

# 出力ルール
各回答について:
- 正しさ: 事実誤認・論理の穴・バグ・見落とし（該当箇所を引用して具体的に）
- あなたの回答との差分: 相手の方が優れている点／劣っている点
- スコア: 1〜10（根拠つき）
コードを実際に動かして検証できるなら、して構いません（作業ディレクトリ内のみ）。
最後に「## 総評」を書き、その直後に必ず次の形式の JSON を 1 つだけ出してください（キーは回答の記号）:
```json
{{"scores": {{{score_keys}}}, "best": "A"}}
```
"""

SYNTH_PROMPT = """あなたは「{agent}」として、複数の匿名回答とその相互レビュー（採点つき）をすべて読み、最終回答を作ります。

# 課題
{prompt}

# 各回答（記号は匿名。誰の回答かは伏せられています）
{solutions}

# 相互レビュー
{reviews}

# 出力ルール
- 「## 最終回答」: レビューで指摘された問題を取り込み、最良の要素を統合した最終的な回答・手順・コード。
- 「## 判断の根拠」: どの回答を採用し、どれを退けたか、なぜか（記号で）。
- 「## 残る不確実性」: 人間が確認すべき点。
- 最後に必ず JSON を 1 つ: ```json {{"adopted": ["A", "C"]}} ```（主に採用した回答の記号。複数可）
"""


PLAN_PROMPT = """あなたは「{agent}」として、複数の AI エージェントで取り組む課題の **配役（担当視点の割り当て）** を決めます。
同じ視点を複数人に重複させず、全員の視点を合わせると課題全体が漏れなく覆われ、かつ各自の個性・実績が活きる割り当てにしてください。

# 課題
{prompt}

# 参加者プロフィール（Hub が把握している個性と実績）
{profiles}

# 出力ルール
- 各参加者に 2〜4 行の「担当視点」を書く（何を深く掘るか、何をしないか）。ファイルを読めない参加者には推論・懐疑・外部知識の役割を。
- 最後に必ず JSON を 1 つだけ: ```json {{"angles": {{"<参加者名>": "<担当視点>", ...}}}} ```
"""


TRAITS = {
    "claude": "Claude Code: 慎重で統合が得意。ファイル読み書き・コマンド実行可",
    "codex": "Codex CLI: 速い実行派。短く要点、コードを動かして確かめる。ファイル読み書き・コマンド実行可",
    "cursor": "Cursor CLI: コードベース探索・横断検索が得意。ファイル読み書き・コマンド実行可",
    "kimi": "Kimi K3: 1M トークンの長コンテキスト。大量のコード/ログを一度に読んで俯瞰できる。ファイル読み書き・コマンド実行可",
    "api": "API 直（Grok 等）: ファイル・コマンドは使えない。別ベンダーの視点・懐疑・外部知識で貢献",
    "command": "CLI: ファイル読み書き・コマンド実行可",
}


def _profiles(store: Store, agents: list[str], spec: dict[str, Any]) -> str:
    board = league.leaderboard(store.list_runs(limit=1000))
    lines = []
    for a in agents:
        ag = store.get_agent(a) or {}
        kind = ag.get("kind") or ("api" if a.startswith(("grok", "qwen")) else a.split("-")[0])
        model = (spec.get("models") or {}).get(a) or (ag.get("meta") or {}).get("model") or ""
        stats = board.get(a, {})
        st = stats.get("all")
        rec = ""
        if st and st.get("n"):
            cats = ", ".join(f"{league.CATEGORY_JA.get(c, c)} {d['avg']}" for c, d in stats.items() if c != "all" and d.get("avg") is not None)
            rec = f" | 実績: 平均 {st['avg']} 点/{st['n']} 件, 最良 {st['best']} 回, 採用 {st['adopted']} 回" + (f" ({cats})" if cats else "")
        lines.append(f"- {a} [{kind}{(' / ' + model) if model else ''}] @{ag.get('host', '?')}: {TRAITS.get(kind, kind)}{rec}")
    return "\n".join(lines)


def _meta(spec: dict[str, Any], agent: str, **extra: Any) -> dict[str, Any]:
    """Per-task meta: model override from spec.models[agent] (+ anything else)."""
    meta = dict(extra)
    model = (spec.get("models") or {}).get(agent)
    if model:
        meta["model"] = model
    return meta


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
                               step="run", workdir=spec.get("workdir"), meta=_meta(spec, spec["agent"], label=spec.get("label")))
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
                                   step="run", workdir=spec.get("workdir"), meta=_meta(spec, agent))
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
        aliases = league.make_aliases(solvers)
        state = {"phase": "solve", "aliases": aliases, "category": spec.get("category") or league.guess_category(spec["prompt"])}
        if spec.get("auto_angles") and not spec.get("angles"):
            state["phase"] = "plan"
            run = self.store.create_run(project, title, "review_panel", spec, created_by, state=state)
            planner = spec.get("planner") or spec["synthesizer"]
            self.store.add_message(actor="hub", role="system", run_id=run["id"],
                                   content=f"配役フェーズ: {planner} が参加者プロフィールから担当視点を割り当てます。")
            prompt = PLAN_PROMPT.format(agent=planner, prompt=spec["prompt"], profiles=_profiles(self.store, solvers, spec))
            self.store.create_task(project, f"配役 [{planner}]", prompt, planner, run_id=run["id"], step="plan",
                                   workdir=spec.get("workdir"), meta=_meta(spec, planner))
            return run
        run = self.store.create_run(project, title, "review_panel", spec, created_by, state=state)
        self._start_solve(run, spec, solvers, aliases)
        return run

    def _start_solve(self, run, spec, solvers, aliases):
        state = run["state"]
        self.store.add_message(actor="hub", role="system", run_id=run["id"],
                               content=f"匿名審査を開始: solvers={solvers} reviewers={spec['reviewers']} synthesizer={spec['synthesizer']} "
                                       f"category={state['category']} (記号: {', '.join(f'{k}={v}' for k, v in aliases.items())})")
        project = run["project"]
        angles = spec.get("angles") or state.get("angles") or {}
        for agent in solvers:
            prompt = SOLVE_PROMPT.format(agent=agent, prompt=spec["prompt"])
            if angles.get(agent):
                prompt += ("\n# あなたの担当視点（他の参加者は別の視点を担当しています。ここを深く掘ってください）\n"
                           f"{angles[agent]}\n")
            self.store.create_task(project, f"解く [{agent}]", prompt, agent, run_id=run["id"], step="solve",
                                   workdir=spec.get("workdir"), meta=_meta(spec, agent, angle=angles.get(agent)))

    def _advance_review_panel(self, run, tasks):
        spec, state = run["spec"], run["state"]
        phase = state.get("phase")
        by_step: dict[str, list[dict[str, Any]]] = {}
        for t in tasks:
            by_step.setdefault(t["step"], []).append(t)

        if phase == "plan":
            t = (by_step.get("plan") or [None])[0]
            angles = {}
            if t and t["status"] == "done":
                obj = league.parse_json_block(t.get("result") or "", "angles") or {}
                angles = {k: str(v) for k, v in (obj.get("angles") or {}).items() if k in spec["solvers"]}
            state = {**state, "phase": "solve", "angles": angles}
            self.store.update_run(run["id"], state=state)
            self.store.add_message(actor="hub", role="system", run_id=run["id"],
                                   content=("配役完了: " + "; ".join(f"{k}: {v.splitlines()[0][:60]}" for k, v in angles.items())) if angles
                                   else "配役の JSON が取れなかったため、視点なしで開始します。")
            self._start_solve({**run, "state": state}, spec, spec["solvers"], state.get("aliases") or league.make_aliases(spec["solvers"]))
            return

        if phase == "solve":
            solved = [t for t in by_step.get("solve", []) if t["status"] == "done"]
            if len(solved) < 2:
                self._fail(run, "2つ以上の回答が得られなかったためレビューを中止")
                return
            votes = [c for c in (league.parse_category(t.get("result") or "") for t in solved) if c]
            category = max(set(votes), key=votes.count) if votes else state.get("category", "other")
            state = {**state, "phase": "review", "category": category}
            self.store.update_run(run["id"], state=state)
            self.store.add_message(actor="hub", role="system", run_id=run["id"],
                                   content=f"解答フェーズ完了 ({len(solved)}/{len(by_step['solve'])} 成功)。カテゴリ={category}。匿名で相互レビューを開始。")
            aliases = state.get("aliases") or league.make_aliases([t["agent"] for t in solved])
            letter_of = {v: k for k, v in aliases.items()}
            own_by_agent = {t["agent"]: t for t in by_step["solve"]}
            for reviewer in spec["reviewers"]:
                own = own_by_agent.get(reviewer)
                others = [t for t in solved if t["agent"] != reviewer]
                if not others:
                    continue
                keys = ", ".join(f'"{letter_of.get(t["agent"], "?")}": <1-10>' for t in others)
                prompt = REVIEW_PROMPT.format(
                    agent=reviewer, prompt=spec["prompt"], score_keys=keys,
                    own=_result(own) if own else "(あなたは解答フェーズに参加していません)",
                    others="\n\n".join(f"## 回答 {letter_of.get(t['agent'], '?')}\n{_result(t)}" for t in others),
                )
                self.store.create_task(run["project"], f"レビュー [{reviewer}]", prompt, reviewer,
                                       run_id=run["id"], step="review", workdir=spec.get("workdir"), meta=_meta(spec, reviewer))
            return

        if phase == "review":
            solved = [t for t in by_step.get("solve", []) if t["status"] == "done"]
            reviews = [t for t in by_step.get("review", []) if t["status"] == "done"]
            aliases = state.get("aliases") or {}
            letter_of = {v: k for k, v in aliases.items()}
            for t in reviews:
                parsed = league.parse_scores(t.get("result") or "")
                if parsed:
                    self.store.finish_task(t["id"], "done", result=t["result"], meta_update={"review": parsed})
            scored = sum(1 for t in reviews if league.parse_scores(t.get("result") or ""))
            self.store.update_run(run["id"], state={**state, "phase": "synthesize"})
            self.store.add_message(actor="hub", role="system", run_id=run["id"],
                                   content=f"レビューフェーズ完了 ({len(reviews)} 件、採点 JSON 取得 {scored} 件)。{spec['synthesizer']} が統合します。")
            prompt = SYNTH_PROMPT.format(
                agent=spec["synthesizer"], prompt=spec["prompt"],
                solutions="\n\n".join(f"## 回答 {letter_of.get(t['agent'], '?')}\n{_result(t, 16000)}" for t in solved),
                reviews="\n\n".join(f"## レビュー {i + 1}（審査員も匿名）\n{_result(t, 12000)}" for i, t in enumerate(reviews))
                or "(レビューなし)",
            )
            self.store.create_task(run["project"], f"統合 [{spec['synthesizer']}]", prompt, spec["synthesizer"],
                                   run_id=run["id"], step="synthesize", workdir=spec.get("workdir"), meta=_meta(spec, spec["synthesizer"]))
            return

        if phase == "synthesize":
            synth = by_step.get("synthesize", [])
            t = synth[0] if synth else None
            if t and t["status"] == "done":
                results = league.tally({**run, "state": state}, tasks)
                self.store.update_run(run["id"], status="done", summary=t["result"] or "",
                                      state={**state, "phase": "finished", "results": results})
                board = ", ".join(f"{a}: {d['avg'] if d['avg'] is not None else '-'}点/{d['n']}件"
                                  f"{' ★最良' + str(d['best']) if d['best'] else ''}{' ✔採用' if d['adopted'] else ''}"
                                  for a, d in results.items())
                self.store.add_message(actor="hub", role="system", run_id=run["id"], content=f"匿名審査 完了。成績: {board}")
            else:
                self._fail(run, f"統合に失敗: {t.get('error') if t else 'no task'}")

    def _fail(self, run, reason: str) -> None:
        self.store.add_message(actor="hub", role="system", run_id=run["id"], content=reason)
        self.store.update_run(run["id"], status="failed", summary=reason, state={**run["state"], "phase": "finished"})
