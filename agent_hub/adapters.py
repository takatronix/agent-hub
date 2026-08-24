"""Subprocess adapters that turn a prompt into a stream of normalized messages.

Each adapter yields dicts: {"role": ..., "content": ..., "data": {...}} and finally
returns the final answer text via the `final` attribute of the generator wrapper.

roles: assistant | thinking | tool_use | tool_result | system | stderr | result
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import urllib.error
from pathlib import Path
from typing import Any, Iterator


class AdapterResult:
    def __init__(self) -> None:
        self.final: str = ""
        self.exit_code: int | None = None
        self.session_id: str | None = None
        self.usage: dict[str, Any] = {}


def _env(extra: dict[str, str] | None) -> dict[str, str]:
    env = dict(os.environ)
    for k, v in (extra or {}).items():
        env[k] = os.path.expanduser(os.path.expandvars(v))
    return env


def _spawn(cmd: list[str], workdir: str | None, env: dict[str, str], stdin_text: str | None = None) -> subprocess.Popen:
    return subprocess.Popen(
        cmd, cwd=workdir or None, env=env, text=True, encoding="utf-8", errors="replace",
        stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1,
    )


def _pump_stderr(proc: subprocess.Popen, sink: list[str]) -> None:
    import threading

    def run():
        assert proc.stderr
        for line in proc.stderr:
            sink.append(line.rstrip("\n"))
            if len(sink) > 500:
                del sink[:-500]

    threading.Thread(target=run, daemon=True).start()


# ---------------------------------------------------------------------------
# claude -p --output-format stream-json
# ---------------------------------------------------------------------------
def run_claude(prompt: str, workdir: str | None, cfg: dict[str, Any], res: AdapterResult) -> Iterator[dict[str, Any]]:
    cmd = [cfg.get("bin", "claude"), "-p", "--verbose", "--output-format", "stream-json"]
    if cfg.get("model"):
        cmd += ["--model", cfg["model"]]
    if cfg.get("permission_mode"):
        cmd += ["--permission-mode", cfg["permission_mode"]]
    if cfg.get("skip_permissions", True):
        cmd += ["--dangerously-skip-permissions"]
    cmd += list(cfg.get("args") or [])
    env = _env(cfg.get("env"))
    env.pop("CLAUDECODE", None)  # allow nesting when the runner itself was started from Claude Code
    proc = _spawn(cmd, workdir, env, stdin_text=prompt)
    assert proc.stdin and proc.stdout
    proc.stdin.write(prompt)
    proc.stdin.close()
    errs: list[str] = []
    _pump_stderr(proc, errs)
    yield {"role": "system", "content": f"$ {shlex.join(cmd)}", "data": {"cwd": workdir}}
    last_text = ""
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            yield {"role": "stderr", "content": line, "data": {}}
            continue
        t = ev.get("type")
        if t == "system":
            res.session_id = ev.get("session_id") or res.session_id
            if ev.get("subtype") == "init":  # other system events (hooks, status) are noise for the transcript
                yield {"role": "system", "content": f"session {ev.get('session_id','')} model={ev.get('model','')}",
                       "data": {k: ev.get(k) for k in ("model", "cwd", "permissionMode") if k in ev}}
        elif t == "assistant":
            for block in (ev.get("message") or {}).get("content") or []:
                bt = block.get("type")
                if bt == "text" and block.get("text"):
                    last_text = block["text"]
                    yield {"role": "assistant", "content": block["text"], "data": {}}
                elif bt == "thinking" and block.get("thinking"):
                    yield {"role": "thinking", "content": block["thinking"], "data": {}}
                elif bt == "tool_use":
                    yield {"role": "tool_use", "content": _tool_summary(block.get("name"), block.get("input")),
                           "data": {"name": block.get("name"), "input": block.get("input"), "id": block.get("id")}}
        elif t == "user":
            for block in (ev.get("message") or {}).get("content") or []:
                if block.get("type") == "tool_result":
                    content = block.get("content")
                    if isinstance(content, list):
                        content = "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
                    yield {"role": "tool_result", "content": str(content or ""),
                           "data": {"tool_use_id": block.get("tool_use_id"), "is_error": block.get("is_error", False)}}
        elif t == "result":
            res.final = ev.get("result") or res.final
            res.usage = {k: ev.get(k) for k in ("total_cost_usd", "duration_ms", "num_turns", "usage") if k in ev}
            res.session_id = ev.get("session_id") or res.session_id
            data = {**res.usage, "is_error": ev.get("is_error", False), "subtype": ev.get("subtype")}
            # the final text was already shown as the last assistant message; don't repeat it
            yield {"role": "result", "content": "" if res.final == last_text else res.final, "data": data}
    res.exit_code = proc.wait()
    if errs:
        yield {"role": "stderr", "content": "\n".join(errs[-60:]), "data": {}}


# ---------------------------------------------------------------------------
# codex exec --json
# ---------------------------------------------------------------------------
def run_codex(prompt: str, workdir: str | None, cfg: dict[str, Any], res: AdapterResult) -> Iterator[dict[str, Any]]:
    cmd = [cfg.get("bin", "codex"), "exec", "--json", "--skip-git-repo-check"]
    if cfg.get("model"):
        cmd += ["--model", cfg["model"]]
    if cfg.get("sandbox", "workspace-write"):
        cmd += ["--sandbox", cfg.get("sandbox", "workspace-write")]
    if cfg.get("bypass_sandbox"):
        cmd += ["--dangerously-bypass-approvals-and-sandbox"]
    cmd += list(cfg.get("args") or [])
    # no positional prompt: codex exec reads the instructions from stdin
    env = _env(cfg.get("env"))
    proc = _spawn(cmd, workdir, env, stdin_text=prompt)
    assert proc.stdin and proc.stdout
    proc.stdin.write(prompt)
    proc.stdin.close()
    errs: list[str] = []
    _pump_stderr(proc, errs)
    yield {"role": "system", "content": f"$ {shlex.join(cmd)}", "data": {"cwd": workdir}}
    last_agent_text = ""
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            yield {"role": "stderr", "content": line, "data": {}}
            continue
        t = ev.get("type", "")
        item = ev.get("item") or {}
        it = item.get("type", "")
        if t == "thread.started":
            res.session_id = ev.get("thread_id")
            yield {"role": "system", "content": f"thread {res.session_id}", "data": {}}
        elif t == "item.completed" or t == "item.started":
            if it == "agent_message" and t == "item.completed":
                last_agent_text = item.get("text") or ""
                yield {"role": "assistant", "content": last_agent_text, "data": {}}
            elif it == "reasoning" and t == "item.completed":
                yield {"role": "thinking", "content": item.get("text") or "", "data": {}}
            elif it == "command_execution":
                if t == "item.started":
                    yield {"role": "tool_use", "content": f"Bash: {item.get('command','')}", "data": {"name": "Bash", "input": {"command": item.get("command")}}}
                else:
                    yield {"role": "tool_result", "content": (item.get("aggregated_output") or "")[-8000:],
                           "data": {"exit_code": item.get("exit_code"), "is_error": bool(item.get("exit_code"))}}
            elif it in ("file_change", "patch_apply", "mcp_tool_call", "web_search") and t == "item.completed":
                yield {"role": "tool_use", "content": f"{it}: {json.dumps(item, ensure_ascii=False)[:2000]}", "data": {"name": it, "input": item}}
            elif it == "error":
                yield {"role": "stderr", "content": item.get("message") or json.dumps(item), "data": {}}
        elif t == "turn.completed":
            res.usage = ev.get("usage") or {}
            res.final = last_agent_text
            yield {"role": "result", "content": "", "data": {"usage": res.usage}}
        elif t in ("turn.failed", "error"):
            yield {"role": "stderr", "content": json.dumps(ev, ensure_ascii=False)[:4000], "data": {}}
        # legacy (pre-0.40) event format: {"msg": {"type": "agent_message", "message": ...}}
        elif "msg" in ev:
            msg = ev["msg"]
            mt = msg.get("type")
            if mt == "agent_message":
                last_agent_text = msg.get("message") or ""
                yield {"role": "assistant", "content": last_agent_text, "data": {}}
            elif mt == "task_complete":
                res.final = msg.get("last_agent_message") or last_agent_text
                yield {"role": "result", "content": res.final, "data": {}}
    res.exit_code = proc.wait()
    if not res.final:
        res.final = last_agent_text
    if errs:
        yield {"role": "stderr", "content": "\n".join(errs[-60:]), "data": {}}


# ---------------------------------------------------------------------------
# generic command template (kimi, gemini, anything): prints plain text or JSONL
# ---------------------------------------------------------------------------
def run_command(prompt: str, workdir: str | None, cfg: dict[str, Any], res: AdapterResult) -> Iterator[dict[str, Any]]:
    """cfg.command: list of argv; "{prompt}" is replaced, or prompt goes to stdin if cfg.stdin (default true).

    cfg.jsonl: if true, each stdout line is parsed as JSON and text-ish fields are surfaced;
    otherwise stdout is streamed as assistant text and the whole stdout is the final answer.
    """
    template = cfg.get("command")
    if not template:
        raise ValueError("command adapter needs cfg.command")
    use_stdin = cfg.get("stdin", True) and not any("{prompt}" in a for a in template)
    cmd = [a.replace("{prompt}", prompt) for a in template]
    env = _env(cfg.get("env"))
    proc = _spawn(cmd, workdir, env, stdin_text=prompt if use_stdin else None)
    if use_stdin:
        assert proc.stdin
        proc.stdin.write(prompt)
        proc.stdin.close()
    assert proc.stdout
    errs: list[str] = []
    _pump_stderr(proc, errs)
    shown = [a if "{prompt}" not in a else "<prompt>" for a in template]
    yield {"role": "system", "content": f"$ {shlex.join(shown)}", "data": {"cwd": workdir}}
    chunks: list[str] = []
    for line in proc.stdout:
        raw = line.rstrip("\n")
        if cfg.get("jsonl"):
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                chunks.append(raw)
                yield {"role": "assistant", "content": raw, "data": {}}
                continue
            text = _extract_text(ev)
            role = "assistant"
            if isinstance(ev, dict):
                t = str(ev.get("type") or ev.get("role") or "")
                if "tool" in t:
                    role = "tool_use"
                elif "result" in t or "final" in t:
                    role = "result"
                    res.final = text or res.final
                elif "thinking" in t or "reasoning" in t:
                    role = "thinking"
            if text:
                if role in ("assistant", "result"):
                    chunks.append(text)
                yield {"role": role, "content": text, "data": {"raw": ev} if role != "assistant" else {}}
        else:
            chunks.append(raw)
            yield {"role": "assistant", "content": raw, "data": {}}
    res.exit_code = proc.wait()
    if not res.final:
        res.final = "\n".join(chunks).strip()
    if errs:
        yield {"role": "stderr", "content": "\n".join(errs[-60:]), "data": {}}


def _extract_text(ev: Any) -> str:
    if isinstance(ev, str):
        return ev
    if not isinstance(ev, dict):
        return ""
    for key in ("text", "content", "message", "result", "output", "delta"):
        v = ev.get(key)
        if isinstance(v, str) and v:
            return v
        if isinstance(v, dict):
            inner = _extract_text(v)
            if inner:
                return inner
        if isinstance(v, list):
            parts = [_extract_text(x) for x in v]
            joined = "\n".join(p for p in parts if p)
            if joined:
                return joined
    return ""


# ---------------------------------------------------------------------------
# fake adapter for tests / demos
# ---------------------------------------------------------------------------
def run_fake(prompt: str, workdir: str | None, cfg: dict[str, Any], res: AdapterResult) -> Iterator[dict[str, Any]]:
    import time
    name = cfg.get("name", "fake")
    delay = float(cfg.get("delay", 0.05))
    yield {"role": "system", "content": f"fake agent {name} starting", "data": {}}
    time.sleep(delay)
    yield {"role": "thinking", "content": f"{name} が課題を読んでいます ({len(prompt)} chars)", "data": {}}
    yield {"role": "tool_use", "content": "Bash: echo hello", "data": {"name": "Bash", "input": {"command": "echo hello"}}}
    yield {"role": "tool_result", "content": "hello", "data": {"is_error": False}}
    time.sleep(delay)
    head = prompt.strip().splitlines()[0][:80] if prompt.strip() else ""
    if "最終回答" in prompt:
        body = f"## 最終回答\n{name} による統合結果。\n\n## 判断の根拠\n全員の意見を採用。\n\n## 残る不確実性\nなし。"
    elif "レビュー" in prompt[:200] or "review" in prompt[:200].lower():
        body = f"## レビュー by {name}\n- 正しさ: 概ね妥当。\n- スコア: 7/10\n\n## 総評\n{name} としては統合を推奨。"
    else:
        body = f"{name} の回答です。({head})\n\n## 結論\n{name}: 42 です。"
    res.final = body
    yield {"role": "result", "content": body, "data": {}}
    res.exit_code = 0


# ---------------------------------------------------------------------------
# OpenAI-compatible chat API (Grok / Kimi / Gemini / DeepSeek ...): no tools, text only.
# cfg: base_url, model, api_key or api_key_env, system (optional), temperature, max_tokens
# ---------------------------------------------------------------------------
def run_api(prompt: str, workdir: str | None, cfg: dict[str, Any], res: AdapterResult) -> Iterator[dict[str, Any]]:
    import urllib.request

    base = (cfg.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    key = cfg.get("api_key") or os.environ.get(cfg.get("api_key_env") or "OPENAI_API_KEY", "")
    if not key:
        raise ValueError(f"api adapter: no API key (set api_key or {cfg.get('api_key_env') or 'OPENAI_API_KEY'})")
    model = cfg.get("model") or "gpt-4o"
    messages = []
    system = cfg.get("system") or (
        "You are an expert software engineer participating in a multi-agent review panel. "
        "You cannot run code or read files; reason carefully from the text you are given and say so when "
        "something would need to be verified by execution. Answer in the language of the prompt."
    )
    messages.append({"role": "system", "content": system})
    if workdir:
        prompt = f"(Note: the working directory on the runner is {workdir}, but you have no file access.)\n\n" + prompt
    messages.append({"role": "user", "content": prompt})
    body = {"model": model, "messages": messages, "stream": True, "stream_options": {"include_usage": True}}
    if cfg.get("temperature") is not None:
        body["temperature"] = cfg["temperature"]
    if cfg.get("max_tokens"):
        body["max_tokens"] = cfg["max_tokens"]
    for k, v in (cfg.get("extra_body") or {}).items():
        body[k] = v
    yield {"role": "system", "content": f"POST {base}/chat/completions model={model}", "data": {}}
    req = urllib.request.Request(f"{base}/chat/completions", data=json.dumps(body).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {key}")
    chunks: list[str] = []
    reasoning: list[str] = []
    buf = ""
    last_emit = 0
    try:
        with urllib.request.urlopen(req, timeout=float(cfg.get("timeout", 600))) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    ev = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                for choice in ev.get("choices") or []:
                    delta = choice.get("delta") or {}
                    if delta.get("reasoning_content"):
                        reasoning.append(delta["reasoning_content"])
                    if delta.get("content"):
                        chunks.append(delta["content"])
                        buf += delta["content"]
                        # stream to the hub in paragraph-ish pieces so the UI shows progress
                        if len(buf) - last_emit > 800 and buf.endswith("\n"):
                            yield {"role": "assistant", "content": buf[last_emit:], "data": {"partial": True}}
                            last_emit = len(buf)
                if ev.get("usage"):
                    res.usage = ev["usage"]
    except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
        err = e.read().decode("utf-8", "replace")[:2000]
        yield {"role": "stderr", "content": f"HTTP {e.code}: {err}", "data": {}}
        res.exit_code = 1
        return
    if reasoning:
        yield {"role": "thinking", "content": "".join(reasoning), "data": {}}
    # real money: price_in / price_out are USD per 1M tokens (set per agent in runner.json)
    if res.usage and (cfg.get("price_in") or cfg.get("price_out")):
        pin, pout = float(cfg.get("price_in") or 0), float(cfg.get("price_out") or 0)
        cost = res.usage.get("prompt_tokens", 0) * pin / 1e6 + res.usage.get("completion_tokens", 0) * pout / 1e6
        res.usage = {**res.usage, "total_cost_usd": round(cost, 6), "billing": "api"}
    res.final = "".join(chunks).strip()
    if buf[last_emit:].strip():
        yield {"role": "assistant", "content": buf[last_emit:], "data": {}}
    yield {"role": "result", "content": "", "data": {"usage": res.usage}}
    res.exit_code = 0


ADAPTERS = {"claude": run_claude, "codex": run_codex, "command": run_command, "api": run_api, "fake": run_fake}


def _tool_summary(name: Any, inp: Any) -> str:
    if not isinstance(inp, dict):
        return f"{name}"
    for key in ("command", "file_path", "pattern", "path", "description", "prompt", "query", "url"):
        if key in inp:
            return f"{name}: {str(inp[key])[:300]}"
    return f"{name}: {json.dumps(inp, ensure_ascii=False)[:300]}"
