# agent-hub

複数ベンダーの AI コーディングエージェント（Claude Code / Codex / Kimi …）を、複数マシン・複数アカウントにまたがって協調させるための小さなハブ。
AI 同士が何をやりとりしたかを全部記録し、Web UI で横並び／時系列で見られる。

```
あなたの Claude Code セッション（オーケストレーター、頭脳）
   │  MCP: review_panel / dispatch / parallel
   ▼
[Hub]  1 台に常駐（Tailscale 内）: SQLite 台帳 + HTTP API + SSE + Web UI + レシピ
   ▲  long-poll            ▲ transcript を逐次 POST
   │                       │
[Runner] 各マシンに常駐 ── claude -p / codex exec / kimi --print を起動して流す
   aspa1: claude-aspa1, codex-aspa1, kimi-aspa1
   aspa2: claude-aspa2, codex-aspa2
   mac:   claude-acctA, claude-acctB   ← CLAUDE_CONFIG_DIR でアカウント切替
```

依存ゼロ（Python 3.9+ 標準ライブラリ + SQLite）。Jetson/ARM でもそのまま動く。

## なぜ Claude Code 内蔵のサブエージェントではなく、これか

- **別ベンダーの視点**: Codex / Kimi を Claude Code 内蔵機能からは呼べない
- **別マシン・別アカウント**: 内蔵機能は 1 セッション 1 アカウント 1 マシンの中
- **やりとりの永続化**: 内蔵のサブエージェント会話はセッションが消えたら見えない

制御の賢さは Claude Code に任せ、hub は「手足（Runner）」と「記憶（台帳 + UI）」だけを持つ。
オーケストレーション（誰に何を投げ、どう突き合わせるか）は決定論的な **レシピ** として hub に置く。

## レシピ

| recipe | 動き |
|---|---|
| `review_panel` | solvers 全員が独立に解く → 各自が他者の回答をレビュー → synthesizer が統合して最終回答 |
| `parallel` | 同じプロンプトを複数エージェントに投げて全回答を並べる |
| `single` | 1 エージェントに 1 タスク |

`review_panel` が「SLAM のときに効いた型」（分散→三者評価→統合）の再現。

## セットアップ

### Hub（1 台、例: macstudio）

```bash
git clone <this repo> ~/projects/agent-hub && cd ~/projects/agent-hub
cp .env.example .env     # HUB_TOKEN / HUB_READ_TOKEN を決める
bin/hub                  # http://0.0.0.0:8765
```

Linux で常駐させるなら `deploy/agent-hub.service` を `/etc/systemd/system/agent-hub@.service` に置いて `systemctl enable --now agent-hub@<user>`。
Mac なら `launchctl` か `screen` で十分。

### Runner（各マシン）

```bash
# 対象マシンで
git clone <this repo> ~/agent-hub && cd ~/agent-hub
deploy/install-runner.sh http://<hub-tailscale-ip>:8765 <HUB_TOKEN>
# → ~/.agent-hub/runner.json を自動生成（claude/codex/kimi を検出）、systemd があれば常駐化
```

手動起動: `bin/hub-runner -c ~/.agent-hub/runner.json`

`runner.json` の例は [examples/runner.json](examples/runner.json)。エージェント定義:

```jsonc
{"name": "claude-a", "kind": "claude", "env": {"CLAUDE_CONFIG_DIR": "~/.claude-a"}, "model": "opus"}
{"name": "codex",    "kind": "codex",  "sandbox": "workspace-write"}
{"name": "kimi",     "kind": "command", "command": ["kimi", "--print", "--output-format", "stream-json", "-p", "{prompt}"], "jsonl": true}
{"name": "fake",     "kind": "fake"}   // 配線確認用
```

- `claude`: `claude -p --output-format stream-json`。**既定モデルは `sonnet` にしておくこと**（アカウント既定が Fable だと Max の利用枠を急速に消費する）。run ごとに UI / MCP の `models` で opus / fable に上げられる。Max/Pro ログインなら API 課金は発生せず、UI の `$` 表示は推定値。既定で `--dangerously-skip-permissions`（`"skip_permissions": false` で外せる）。複数アカウントは `CLAUDE_CONFIG_DIR` を変えた agent を複数並べるだけ。
- `codex`: `codex exec --json --sandbox workspace-write`（stdin でプロンプト）。`"bypass_sandbox": true` で sandbox 解除。
- `api`: OpenAI 互換 chat API を直接叩く（Grok = api.x.ai、Kimi = api.moonshot.ai、Gemini、DeepSeek …）。ツール実行はできないが「解く・レビューする」役には十分。キーは `api_key_env` で環境変数から（runner の systemd unit の `Environment=` か `~/.agent-hub/runner.env`）。
- `command`: 任意コマンド（Cursor CLI = `cursor-agent -p --output-format stream-json`、kimi CLI など）。`{prompt}` を引数に埋めるか stdin で渡す。`jsonl: true` なら行 JSON から text を拾う。
- 1 エージェント = 同時 1 タスク。同じ CLI を並列で回したいなら名前を変えて複数定義。

### Claude Code から使う（MCP）

`~/.claude.json` か プロジェクトの `.mcp.json` に [examples/claude-code-mcp.json](examples/claude-code-mcp.json) を追加。
または:

```bash
claude mcp add --scope user agent-hub -e HUB_URL=http://<hub>:8765 -e HUB_TOKEN=<token> -- ~/projects/agent-hub/bin/hub-mcp
```

ツール: `list_agents` / `dispatch` / `review_panel` / `parallel` / `get_run` / `wait_run` / `get_task_transcript` / `list_runs`

例（Claude Code に話しかける）:

> SLAM のループクロージャが失敗する件、`review_panel` で claude-aspa1, codex-aspa1, kimi-aspa1 に解かせて相互レビューさせて。workdir は /home/aspa1/aspa-navigation。

### CLI

```bash
bin/hubctl agents
bin/hubctl panel "課題..." --solvers claude-aspa1,codex-aspa1,kimi-aspa1 --workdir /home/aspa1/aspa-navigation
bin/hubctl dispatch codex-aspa1 "テストを全部走らせて失敗を要約して" --workdir /home/aspa1/aspa-navigation
bin/hubctl runs / run <run_id> --results / transcript <task_id> / cancel <run_id>
```

### Web UI

`http://<hub>:8765/?token=<HUB_READ_TOKEN>`

- Runs 一覧・新規 run フォーム・オンラインのエージェント
- Run 詳細: フェーズ表示 → **エージェント別**（solve / review / synthesize を横並び、ツール呼び出しは折りたたみ）／**時系列**／**結論だけ**。SSE でライブ更新。

## HTTP API

```
GET  /api/health
GET  /api/agents                 POST /api/agents/heartbeat
GET  /api/runs?project=&limit=   POST /api/runs {recipe, project, title, spec}
GET  /api/runs/{id}              GET  /api/runs/{id}/messages?after=   POST /api/runs/{id}/cancel
GET  /api/tasks?status=&agent=   POST /api/tasks {agent, prompt, workdir}   (レシピなしの単発)
POST /api/tasks/claim {agents:[..], claimed_by, wait}      ← Runner の long-poll
GET  /api/tasks/{id}             POST /api/tasks/{id}/finish {status, result, error, meta}
POST /api/messages {items:[{task_id, actor, role, content, data}]}
POST /api/artifacts              GET  /api/artifacts/{id}/content
GET  /api/stream?run_id=         ← SSE (run / task / message / artifact / agent)
```

認証: `Authorization: Bearer <token>` / `X-Hub-Token` / `?token=`。`HUB_TOKEN` が書き込み、`HUB_READ_TOKEN` は GET のみ。

## テスト

```bash
PYTHONPATH=. python3 -m unittest discover -s tests
```

fake アダプタで hub + runner + review_panel を実際に HTTP 越しに通す end-to-end テストを含む。

## 旧 agent-bus との関係

[agent-bus](https://github.com/takatronix/agent-bus) の台帳の考え方（project / task / event / artifact / agent）を引き継ぎ、
使えなかった原因だった「タスクを駆動するものがいない」「AI 同士の会話が残らない」を Runner と messages + SSE で埋めたもの。
