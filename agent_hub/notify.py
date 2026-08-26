"""Fire-and-forget ntfy notifications (zero dependency).

A background daemon thread drains a queue and POSTs to an ntfy topic URL via urllib.
If no ntfy_url is configured the whole thing is a no-op. Every failure is swallowed —
notifications must never break a run.
"""
from __future__ import annotations

import queue
import threading
import urllib.request
from typing import Any


class Notifier:
    def __init__(self, public_url: str | None = None, ntfy_url: str | None = None):
        self.public_url = (public_url or "").rstrip("/")
        self.ntfy_url = ntfy_url or None
        self._q: queue.Queue = queue.Queue(maxsize=1000)
        if self.ntfy_url:
            threading.Thread(target=self._loop, daemon=True, name="notifier").start()

    def emit(self, run: dict[str, Any]) -> None:
        """Non-blocking; drops the notification if the queue is full or ntfy is off."""
        if not self.ntfy_url:
            return
        try:
            self._q.put_nowait(run)
        except queue.Full:  # pragma: no cover - overflow is best-effort
            pass

    def _loop(self) -> None:
        while True:
            run = self._q.get()
            try:
                self._send(run)
            except Exception:  # noqa: BLE001 - fire-and-forget
                pass

    def _send(self, run: dict[str, Any]) -> None:
        status = run.get("status") or ""
        title = run.get("title") or "run"
        body = (run.get("summary") or "")[:200] or f"run {status}"
        headers = {"Title": title, "Tags": "white_check_mark" if status == "done" else "x"}
        if self.public_url and run.get("id"):
            headers["Click"] = f"{self.public_url}/runs/{run['id']}"
        req = urllib.request.Request(self.ntfy_url, data=body.encode("utf-8"), headers=headers, method="POST")
        urllib.request.urlopen(req, timeout=10).close()
