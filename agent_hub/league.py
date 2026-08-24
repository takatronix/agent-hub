"""Anonymous review league: aliasing, score parsing, task categories, leaderboard, casting."""
from __future__ import annotations

import json
import re
import string
from collections import defaultdict
from typing import Any

CATEGORIES = ["algorithm", "robotics", "debugging", "design", "docs", "math", "data", "web", "infra", "other"]
CATEGORY_JA = {"algorithm": "アルゴリズム", "robotics": "ロボット/ROS", "debugging": "デバッグ", "design": "設計",
               "docs": "文書/仕様", "math": "数理", "data": "データ", "web": "Web", "infra": "インフラ", "other": "その他"}
_KEYWORDS = {
    "robotics": ["ros", "launch", "slam", "localization", "lidar", "odom", "tf", "nav2", "ロボット", "自己位置", "点群", "urdf", "can "],
    "debugging": ["バグ", "bug", "error", "crash", "落ち", "失敗", "fail", "原因", "直し", "fix", "panic", "segfault"],
    "algorithm": ["アルゴリズム", "o(n", "計算量", "最適", "ソート", "探索", "dp", "グラフ"],
    "design": ["設計", "アーキテクチャ", "architecture", "design", "構成", "リファクタ", "refactor", "api 設計"],
    "docs": ["仕様", "readme", "ドキュメント", "手順", "説明", "要約", "翻訳"],
    "math": ["数式", "証明", "行列", "確率", "統計", "微分", "積分", "kalman", "カルマン"],
    "data": ["csv", "データ", "pandas", "sql", "集計", "分析", "可視化"],
    "web": ["html", "css", "react", "vue", "web", "ブラウザ", "フロント", "http"],
    "infra": ["docker", "systemd", "deploy", "デプロイ", "ci", "サーバ", "nginx", "tailscale", "ssh"],
}


def guess_category(prompt: str) -> str:
    text = prompt.lower()
    best, score = "other", 0
    for cat, words in _KEYWORDS.items():
        n = sum(text.count(w) for w in words)
        if n > score:
            best, score = cat, n
    return best


def make_aliases(agents: list[str]) -> dict[str, str]:
    """alias letter -> agent name, in a stable (given) order."""
    return {string.ascii_uppercase[i]: a for i, a in enumerate(agents)}


def parse_json_block(text: str, key: str) -> dict[str, Any] | None:
    """Find the last JSON object in text that contains `key` (inside ```json fences or bare)."""
    if not text:
        return None
    candidates = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
    # bare objects: scan balanced braces starting near the key
    for m in re.finditer(r"\{", text):
        i = m.start()
        if f'"{key}"' not in text[i:i + 300]:
            continue
        depth = 0
        for j in range(i, min(len(text), i + 4000)):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[i:j + 1])
                    break
    for cand in reversed(candidates):
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and key in obj:
            return obj
    return None


def parse_scores(text: str) -> dict[str, Any] | None:
    """{"scores": {"A": 7, "B": 4}, "best": "A"} -> normalized."""
    obj = parse_json_block(text, "scores")
    if not obj or not isinstance(obj.get("scores"), dict):
        return None
    scores = {}
    for k, v in obj["scores"].items():
        try:
            scores[str(k).strip().upper()[:1]] = max(1.0, min(10.0, float(v)))
        except (TypeError, ValueError):
            continue
    best = str(obj.get("best") or "").strip().upper()[:1] or (max(scores, key=scores.get) if scores else None)
    return {"scores": scores, "best": best}


def parse_category(text: str) -> str | None:
    m = re.search(r"カテゴリ\s*[:：]\s*([a-zA-Z]+)", text or "")
    if m and m.group(1).lower() in CATEGORIES:
        return m.group(1).lower()
    return None


def parse_adopted(text: str) -> list[str]:
    obj = parse_json_block(text or "", "adopted")
    if not obj:
        return []
    val = obj.get("adopted")
    if isinstance(val, str):
        val = [val]
    return [str(x).strip().upper()[:1] for x in (val or []) if str(x).strip()]


def tally(run: dict[str, Any], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate a finished review_panel run into per-agent results (called by the recipe)."""
    state = run["state"]
    aliases: dict[str, str] = state.get("aliases") or {}
    per_agent: dict[str, dict[str, Any]] = {a: {"scores": [], "best": 0, "adopted": False, "reviews": 0} for a in aliases.values()}
    for t in tasks:
        if t["step"] == "review" and t["status"] == "done":
            parsed = t["meta"].get("review") or parse_scores(t.get("result") or "")
            if not parsed:
                continue
            for letter, sc in parsed["scores"].items():
                a = aliases.get(letter)
                if a and a != t["agent"]:
                    per_agent[a]["scores"].append(sc)
                    per_agent[a]["reviews"] += 1
            if parsed.get("best") and aliases.get(parsed["best"]) and aliases[parsed["best"]] != t["agent"]:
                per_agent[aliases[parsed["best"]]]["best"] += 1
        if t["step"] == "synthesize" and t["status"] == "done":
            for letter in parse_adopted(t.get("result") or ""):
                if aliases.get(letter):
                    per_agent[aliases[letter]]["adopted"] = True
    out = {}
    for a, d in per_agent.items():
        out[a] = {"avg": round(sum(d["scores"]) / len(d["scores"]), 2) if d["scores"] else None,
                  "n": len(d["scores"]), "best": d["best"], "adopted": d["adopted"]}
    return out


def leaderboard(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """agent -> category -> {avg, n, best, adopted, runs}; plus 'all' bucket."""
    acc: dict[str, dict[str, dict[str, Any]]] = defaultdict(lambda: defaultdict(lambda: {"sum": 0.0, "n": 0, "best": 0, "adopted": 0, "runs": 0}))
    for r in runs:
        if r["recipe"] != "review_panel" or r["status"] != "done":
            continue
        cat = r["state"].get("category") or "other"
        for agent, d in (r["state"].get("results") or {}).items():
            for bucket in (cat, "all"):
                x = acc[agent][bucket]
                x["runs"] += 1
                if d.get("avg") is not None:
                    x["sum"] += d["avg"] * d["n"]
                    x["n"] += d["n"]
                x["best"] += d.get("best", 0)
                x["adopted"] += 1 if d.get("adopted") else 0
    out: dict[str, Any] = {}
    for agent, cats in acc.items():
        out[agent] = {}
        for cat, x in cats.items():
            out[agent][cat] = {"avg": round(x["sum"] / x["n"], 2) if x["n"] else None, "n": x["n"],
                               "best": x["best"], "adopted": x["adopted"], "runs": x["runs"]}
    return out


def recommend(board: dict[str, Any], category: str, online: list[dict[str, Any]], k: int = 3) -> dict[str, Any]:
    """Pick k solvers for a category from the leaderboard (fallback: vendor diversity), plus a synthesizer."""
    names = [a["name"] for a in online]
    kinds = {a["name"]: a["kind"] for a in online}

    def score(name: str) -> float:
        d = (board.get(name) or {}).get(category) or (board.get(name) or {}).get("all") or {}
        base = d.get("avg") or 5.0
        return base + 0.5 * d.get("best", 0) + 0.7 * d.get("adopted", 0)

    ranked = sorted(names, key=score, reverse=True)
    picked: list[str] = []
    seen_kinds: set[str] = set()
    for n in ranked:  # prefer different vendors/kinds first
        if kinds[n] not in seen_kinds:
            picked.append(n)
            seen_kinds.add(kinds[n])
        if len(picked) >= k:
            break
    for n in ranked:
        if len(picked) >= k:
            break
        if n not in picked:
            picked.append(n)
    synth = next((n for n in picked if kinds[n] in ("claude", "codex", "kimi")), picked[0] if picked else None)
    return {"category": category, "solvers": picked, "synthesizer": synth,
            "reason": {n: round(score(n), 2) for n in picked}}
