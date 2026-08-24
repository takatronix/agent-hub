#!/usr/bin/env bash
# Usage (on the target machine, via ssh):  bash install-runner.sh <hub-url> <token>
set -euo pipefail
HUB_URL="${1:?hub url}"; TOKEN="${2:?token}"
cd "$(dirname "$0")/.."
mkdir -p ~/.agent-hub
HOST=$(hostname -s)
if [ ! -f ~/.agent-hub/runner.json ]; then
  agents='[]'
  add(){ agents=$(python3 -c "import json,sys;a=json.loads(sys.argv[1]);a.append(json.loads(sys.argv[2]));print(json.dumps(a))" "$agents" "$1"); }
  command -v claude >/dev/null 2>&1 || [ -x ~/.local/bin/claude ] && add "{\"name\":\"claude-$HOST\",\"kind\":\"claude\",\"model\":\"sonnet\"}"
  command -v codex  >/dev/null 2>&1 || [ -x ~/.local/bin/codex  ] && add "{\"name\":\"codex-$HOST\",\"kind\":\"codex\"}"
  command -v kimi   >/dev/null 2>&1 || [ -x ~/.local/bin/kimi   ] && add "{\"name\":\"kimi-$HOST\",\"kind\":\"command\",\"command\":[\"kimi\",\"--print\",\"--output-format\",\"stream-json\",\"-p\",\"{prompt}\"],\"jsonl\":true}"
  add "{\"name\":\"fake-$HOST\",\"kind\":\"fake\"}"
  python3 - "$HUB_URL" "$TOKEN" "$HOST" "$agents" <<'PY'
import json,sys,os
hub,token,host,agents=sys.argv[1:]
cfg={"hub":hub,"token":token,"host":host,"workdir_root":"~","agents":json.loads(agents)}
open(os.path.expanduser("~/.agent-hub/runner.json"),"w").write(json.dumps(cfg,indent=2,ensure_ascii=False))
print("wrote ~/.agent-hub/runner.json:", [a["name"] for a in cfg["agents"]])
PY
else
  echo "~/.agent-hub/runner.json exists, keeping it"
fi
if command -v systemctl >/dev/null 2>&1 && [ -d /etc/systemd/system ]; then
  sudo -n true 2>/dev/null && {
    sudo cp deploy/agent-hub-runner.service /etc/systemd/system/agent-hub-runner@.service
    sudo systemctl daemon-reload
    sudo systemctl enable --now "agent-hub-runner@$USER"
    sudo systemctl restart "agent-hub-runner@$USER"
    echo "systemd: agent-hub-runner@$USER started"
  } || echo "no passwordless sudo; start manually: bin/hub-runner -c ~/.agent-hub/runner.json"
fi
