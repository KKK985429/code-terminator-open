from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class MemoryConfig:
    """Centralized configuration for memory components."""

    data_dir: Path = Path(".memory")
    checkpoint_db_name: str = "checkpoints.sqlite"
    chroma_dir_name: str = "chroma"
    working_window_size: int = 8
    working_summary_trigger_chars: int = 2_400
    retrieval_limit: int = 4
    openai_base_url: str | None = None
    openai_api_key: str | None = None
    chat_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"

    @property
    def checkpoint_db_path(self) -> Path:
        return self.data_dir / self.checkpoint_db_name

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / self.chroma_dir_name


def _load_default_memory_config() -> MemoryConfig:
    data_dir = Path(os.getenv("MEMORY_DATA_DIR", ".memory"))
    checkpoint_name = os.getenv("CHECKPOINT_DB_NAME", "checkpoints.sqlite")
    chroma_dir_name = os.getenv("CHROMA_DIR_NAME", "chroma")
    openai_base_url = os.getenv("OPENAI_BASE_URL") or None
    openai_api_key = os.getenv("OPENAI_API_KEY") or None
    chat_model = os.getenv("DEFAULT_MODEL", "gpt-4o-mini")
    embedding_model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    return MemoryConfig(
        data_dir=data_dir,
        checkpoint_db_name=checkpoint_name,
        chroma_dir_name=chroma_dir_name,
        openai_base_url=openai_base_url,
        openai_api_key=openai_api_key,
        chat_model=chat_model,
        embedding_model=embedding_model,
    )


DEFAULT_MEMORY_CONFIG = _load_default_memory_config()
