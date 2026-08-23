from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


class HubClient:
    def __init__(self, url: str | None = None, token: str | None = None, timeout: float = 70.0):
        self.url = (url or os.environ.get("HUB_URL") or "http://127.0.0.1:8765").rstrip("/")
        self.token = token or os.environ.get("HUB_TOKEN")
        self.timeout = timeout

    def _req(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                msg = json.loads(raw).get("error")
            except Exception:
                msg = raw.decode("utf-8", "replace")[:300]
            raise RuntimeError(f"hub {e.code} on {method} {path}: {msg}") from None
        return json.loads(raw) if raw else {}

    def get(self, path: str) -> Any:
        return self._req("GET", path)

    def post(self, path: str, body: dict[str, Any]) -> Any:
        return self._req("POST", path, body)
