from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.memory import InMemoryStore

from src.app.graph import build_graph
from src.memory.config import DEFAULT_MEMORY_CONFIG, MemoryConfig
from src.observability import get_logger, sanitize_text

LOCK_RETRY_LIMIT = 3
LOCK_RETRY_DELAY_SECONDS = 0.2
logger = get_logger(__name__)


class GraphRuntime(AbstractAsyncContextManager["GraphRuntime"]):
    """Manage graph compilation resources for checkpointable execution."""

    def __init__(self, config: MemoryConfig = DEFAULT_MEMORY_CONFIG) -> None:
        self._config = config
        self._checkpointer_cm: Any | None = None
        self._checkpointer: Any | None = None
        self._store: Any | None = None
        self._graph: Any | None = None

    async def __aenter__(self) -> GraphRuntime:
        self._prepare_dirs()
        logger.info(
            "graph_runtime.enter checkpoint_db=%s chroma_dir=%s",
            self._config.checkpoint_db_path,
            self._config.chroma_dir,
        )
        self._checkpointer_cm = AsyncSqliteSaver.from_conn_string(
            str(self._config.checkpoint_db_path)
        )
        self._checkpointer = await self._checkpointer_cm.__aenter__()
        self._store = InMemoryStore()
        self._graph = build_graph(checkpointer=self._checkpointer, store=self._store)
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        if self._checkpointer_cm is not None:
            await self._checkpointer_cm.__aexit__(exc_type, exc_value, traceback)
        logger.info("graph_runtime.exit exc_type=%s", getattr(exc_type, "__name__", None))

    async def invoke(
        self,
        *,
        input_state: dict[str, Any] | None,
        thread_id: str,
        checkpoint_id: str | None = None,
        current_event: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._graph is None:
            raise RuntimeError("Graph runtime has not been initialized.")
        config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
        if checkpoint_id:
            config["configurable"]["checkpoint_id"] = checkpoint_id
        effective_input = input_state
        if effective_input is None and current_event is not None:
            effective_input = {"current_event": current_event}
        logger.info(
            "graph_runtime.invoke.start thread_id=%s checkpoint_id=%s has_input=%s event_type=%s",
            thread_id,
            checkpoint_id,
            effective_input is not None,
            (current_event or {}).get("event_type"),
        )
        started = time.perf_counter()
        for attempt in range(LOCK_RETRY_LIMIT + 1):
            try:
                result = await self._graph.ainvoke(effective_input, config=config)
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                logger.info(
                    "graph_runtime.invoke.done thread_id=%s elapsed_ms=%s retries=%s",
                    thread_id,
                    elapsed_ms,
                    attempt,
                )
                return result
            except Exception as e:  # noqa: BLE001
                message = str(e).lower()
                is_db_lock = "database is locked" in message
                is_final_attempt = attempt >= LOCK_RETRY_LIMIT
                logger.warning(
                    "graph_runtime.invoke.error thread_id=%s attempt=%s db_lock=%s error=%s",
                    thread_id,
                    attempt,
                    is_db_lock,
                    sanitize_text(str(e)),
                )
                if not is_db_lock or is_final_attempt:
                    raise
                await asyncio.sleep(LOCK_RETRY_DELAY_SECONDS * (attempt + 1))

    @staticmethod
    def ensure_thread_id(thread_id: str | None = None) -> str:
        return thread_id or f"thread-{uuid.uuid4().hex[:8]}"

    def _prepare_dirs(self) -> None:
        data_dir: Path = self._config.data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
