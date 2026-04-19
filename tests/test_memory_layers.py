from pathlib import Path

from src.memory.config import MemoryConfig
from src.memory.longterm_chroma import LongTermChromaMemory
from src.memory.types import ArchivalRecord
from src.memory.working_memory import WorkingMemory


def test_working_memory_summarize_and_queue(tmp_path: Path) -> None:
    core_memory: dict = {}
    config = MemoryConfig(
        data_dir=tmp_path,
        working_window_size=3,
        working_summary_trigger_chars=10,
        retrieval_limit=2,
    )
    working_memory = WorkingMemory(role="worker", core_memory=core_memory, config=config)
    working_memory.push("12345")
    working_memory.push("67890")
    summary = working_memory.maybe_summarize()

    assert summary is not None
    assert isinstance(core_memory.get("longterm_queue"), list)
    assert core_memory["longterm_queue"][0]["role"] == "worker"


def test_longterm_chroma_upsert_and_query(tmp_path: Path) -> None:
    config = MemoryConfig(data_dir=tmp_path)
    storage = LongTermChromaMemory(config=config, collection_name="test_memory_collection")
    storage.upsert_records(
        [
            ArchivalRecord(
                role="worker",
                summary="Implemented API endpoint and added tests",
                timestamp="2026-04-15T00:00:00+00:00",
            )
        ]
    )
    hits = storage.query("API endpoint tests", role="worker", limit=1)
    assert len(hits) >= 1
