"""Durable hook event bus.

Hook events are persisted to disk so background worker threads can hand off
results safely to the API runtime. API startup now clears old hook state,
so these files are only durable within the current backend lifetime.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


class HookEventBus:
    """Thread-safe durable FIFO queue keyed by ``thread_id``."""

    _lock: threading.Lock = threading.Lock()

    @classmethod
    def push(cls, thread_id: str, event: dict[str, Any]) -> None:
        payload = dict(event)
        payload.setdefault("event_id", f"hook-{uuid4().hex[:12]}")
        payload.setdefault("created_at", datetime.now(UTC).isoformat(timespec="seconds"))
        payload.setdefault("thread_id", thread_id)
        with cls._lock:
            path = cls._pending_dir(thread_id) / f"{payload['event_id']}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    @classmethod
    def pop_all(cls, thread_id: str) -> list[dict[str, Any]]:
        with cls._lock:
            cls._recover_stale_locked(thread_id=thread_id)
            events: list[dict[str, Any]] = []
            pending_dir = cls._pending_dir(thread_id)
            processing_dir = cls._processing_dir(thread_id)
            for path in sorted(pending_dir.glob("*.json")):
                claimed = processing_dir / path.name
                claimed.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.replace(path, claimed)
                except FileNotFoundError:
                    continue
                payload = cls._read_json_file(claimed)
                if not isinstance(payload, dict):
                    claimed.unlink(missing_ok=True)
                    continue
                payload["_hook_receipt_path"] = str(claimed)
                events.append(payload)
            return events

    @classmethod
    def ack(cls, event: dict[str, Any]) -> None:
        receipt = str(event.get("_hook_receipt_path", "")).strip()
        if not receipt:
            return
        with cls._lock:
            Path(receipt).unlink(missing_ok=True)

    @classmethod
    def requeue(cls, event: dict[str, Any]) -> None:
        receipt = str(event.get("_hook_receipt_path", "")).strip()
        if not receipt:
            return
        source = Path(receipt)
        with cls._lock:
            if not source.exists():
                return
            thread_id = str(event.get("thread_id", "")).strip()
            if not thread_id:
                payload = cls._read_json_file(source)
                if isinstance(payload, dict):
                    thread_id = str(payload.get("thread_id", "")).strip()
            if not thread_id:
                return
            target = cls._pending_dir(thread_id) / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)

    @classmethod
    def peek_count(cls, thread_id: str) -> int:
        with cls._lock:
            cls._recover_stale_locked(thread_id=thread_id)
            return len(list(cls._pending_dir(thread_id).glob("*.json")))

    @classmethod
    def pending_thread_ids(cls) -> list[str]:
        with cls._lock:
            cls._recover_stale_locked()
            pending_root = cls._root() / "pending"
            if not pending_root.exists():
                return []
            thread_ids: list[str] = []
            for path in sorted(pending_root.iterdir()):
                if not path.is_dir():
                    continue
                if any(path.glob("*.json")):
                    thread_ids.append(path.name)
            return thread_ids

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            shutil.rmtree(cls._root(), ignore_errors=True)

    @classmethod
    def recover_stale(cls) -> None:
        with cls._lock:
            cls._recover_stale_locked()

    @classmethod
    def _recover_stale_locked(cls, *, thread_id: str | None = None) -> None:
        processing_root = cls._root() / "processing"
        if not processing_root.exists():
            return
        stale_seconds = cls._stale_seconds()
        now_ts = datetime.now(UTC).timestamp()
        thread_dirs: list[Path]
        if thread_id:
            thread_dirs = [processing_root / thread_id]
        else:
            thread_dirs = [path for path in processing_root.iterdir() if path.is_dir()]
        for directory in thread_dirs:
            if not directory.exists():
                continue
            for path in sorted(directory.glob("*.json")):
                try:
                    modified_ts = path.stat().st_mtime
                except FileNotFoundError:
                    continue
                if now_ts - modified_ts < stale_seconds:
                    continue
                target = cls._pending_dir(directory.name) / path.name
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.replace(path, target)
                except FileNotFoundError:
                    continue

    @staticmethod
    def _read_json_file(path: Path) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    @staticmethod
    def _stale_seconds() -> float:
        raw = os.getenv("CODE_TERMINATOR_HOOK_STALE_SECONDS", "").strip() or "30"
        try:
            return max(float(raw), 5.0)
        except ValueError:
            return 30.0

    @staticmethod
    def _root() -> Path:
        configured = os.getenv("CODE_TERMINATOR_HOOK_ROOT", "").strip()
        if configured:
            root = Path(configured).expanduser()
            if not root.is_absolute():
                root = (Path.cwd() / root).resolve()
            return root
        return (Path.cwd() / ".code-terminator" / "hook-events").resolve()

    @classmethod
    def _pending_dir(cls, thread_id: str) -> Path:
        return cls._root() / "pending" / thread_id

    @classmethod
    def _processing_dir(cls, thread_id: str) -> Path:
        return cls._root() / "processing" / thread_id


hook_event_bus = HookEventBus
