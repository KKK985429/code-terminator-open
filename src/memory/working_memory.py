from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.memory.config import DEFAULT_MEMORY_CONFIG, MemoryConfig
from src.memory.summarizer import summarize_records
from src.observability import get_logger, sanitize_text

logger = get_logger(__name__)


@dataclass
class WorkingMemory:
    """Sliding-window short-term memory with compression trigger."""

    role: str
    core_memory: dict[str, Any]
    config: MemoryConfig = DEFAULT_MEMORY_CONFIG
    records: deque[str] = field(default_factory=deque)

    def push(self, record: str) -> None:
        logger.info(
            "working_memory.push role=%s record=%s pre_size=%s",
            self.role,
            sanitize_text(record),
            len(self.records),
        )
        self.records.append(record)
        while len(self.records) > self.config.working_window_size:
            self.records.popleft()
        logger.info("working_memory.push.done role=%s size=%s", self.role, len(self.records))

    def maybe_summarize(self) -> str | None:
        total_chars = sum(len(item) for item in self.records)
        logger.info(
            "working_memory.maybe_summarize role=%s total_chars=%s trigger=%s",
            self.role,
            total_chars,
            self.config.working_summary_trigger_chars,
        )
        if total_chars < self.config.working_summary_trigger_chars:
            return None
        summary = summarize_records(self.records, limit=self.config.retrieval_limit)
        self._enqueue_longterm_summary(summary)
        self.records.clear()
        logger.info(
            "working_memory.maybe_summarize.done role=%s summary=%s",
            self.role,
            sanitize_text(summary),
        )
        return summary

    def _enqueue_longterm_summary(self, summary: str) -> None:
        queue = self.core_memory.setdefault("longterm_queue", [])
        if not isinstance(queue, list):
            queue = []
            self.core_memory["longterm_queue"] = queue
        queue.append(
            {
                "role": self.role,
                "summary": summary,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        logger.info("working_memory.enqueue role=%s queue_size=%s", self.role, len(queue))
