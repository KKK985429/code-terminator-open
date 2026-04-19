"""Long-term memory backed by ChromaDB.

This module previously suffered from an embedding-dimension drift bug:
the collection was created without binding an embedding function while
the surrounding code fed hand-computed vectors into ``upsert`` /
``query``. Chroma persists the first vector's dimension into the
collection metadata, so any later run using a different embedding model
(for example switching from an offline 16-dim hash to OpenAI's 1536-dim
``text-embedding-3-small``) crashed with
``Collection expecting embedding with dimension of X, got Y``.

We now:

1. Probe the active embedding backend at construction time to learn the
   true dimension. The backend mode (``openai`` vs ``offline``) and the
   probed dimension are folded into the physical collection name so
   different configurations never share storage.
2. Persist the expected dimension in the collection metadata and auto
   heal (delete + recreate) if a stale collection with a mismatching
   dimension is discovered on disk.
3. Swallow transient long-term errors into warnings so memory writes
   never bring down the rest of the agent pipeline.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import chromadb
from openai import OpenAI

from src.memory.config import DEFAULT_MEMORY_CONFIG, MemoryConfig
from src.memory.types import ArchivalRecord
from src.observability import get_logger, sanitize_text

logger = get_logger(__name__)

PROBE_TEXT = "code-terminator-dimension-probe"


class SimpleEmbeddingFunction:
    """Offline deterministic embedding to avoid runtime model downloads."""

    DIM = 16

    def __call__(self, input: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in input:
            vector = [0.0] * self.DIM
            for index, char in enumerate(text):
                vector[index % self.DIM] += (ord(char) % 127) / 127.0
            norm = sum(abs(item) for item in vector) or 1.0
            vectors.append([item / norm for item in vector])
        return vectors

    def embed_documents(self, input: list[str]) -> list[list[float]]:
        return self.__call__(input)

    def embed_query(self, input: list[str]) -> list[list[float]]:
        return self.__call__(input)

    @staticmethod
    def default_space() -> str:
        return "cosine"

    @staticmethod
    def supported_spaces() -> list[str]:
        return ["cosine"]

    def get_config(self) -> dict[str, Any]:
        return {"name": self.name(), "space": self.default_space()}

    @staticmethod
    def name() -> str:
        return "simple-offline"

    def is_legacy(self) -> bool:
        return False

    @classmethod
    def build_from_config(cls, config: dict[str, Any]) -> "SimpleEmbeddingFunction":
        _ = config
        return cls()


@dataclass
class LongTermChromaMemory:
    """Persistent ChromaDB storage for archival memory."""

    config: MemoryConfig = DEFAULT_MEMORY_CONFIG
    collection_name: str = "agent_memory_offline"
    _base_name: str = field(default="", init=False, repr=False)
    _mode: str = field(default="offline", init=False, repr=False)
    _dim: int = field(default=SimpleEmbeddingFunction.DIM, init=False, repr=False)
    _embedding_model_label: str = field(default="offline", init=False, repr=False)

    def __post_init__(self) -> None:
        started = time.perf_counter()
        self.config.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(self.config.chroma_dir))
        self.openai_client: OpenAI | None = None
        if self.config.openai_api_key:
            try:
                self.openai_client = OpenAI(
                    api_key=self.config.openai_api_key,
                    base_url=self.config.openai_base_url,
                )
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "longterm.openai_client.disabled reason=init_failed error=%s",
                    sanitize_text(str(exc)),
                )
                self.openai_client = None

        self._base_name = self.collection_name
        self._mode = "openai" if self.openai_client is not None else "offline"
        self._dim, self._embedding_model_label = self._probe_embedding_dim()
        physical_name = self._physical_collection_name()
        self.collection_name = physical_name
        self.collection = self._open_or_reset_collection(physical_name)

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "longterm.init collection=%s mode=%s dim=%s model=%s chroma_dir=%s elapsed_ms=%s",
            self.collection_name,
            self._mode,
            self._dim,
            self._embedding_model_label,
            self.config.chroma_dir,
            elapsed_ms,
        )

    # ------------------------------------------------------------------ #
    # Collection lifecycle
    # ------------------------------------------------------------------ #

    def _physical_collection_name(self) -> str:
        return f"{self._base_name}__{self._mode}_d{self._dim}"

    def _expected_metadata(self) -> dict[str, Any]:
        return {
            "embedding_mode": self._mode,
            "embedding_dim": self._dim,
            "embedding_model": self._embedding_model_label,
        }

    def _open_or_reset_collection(self, name: str) -> Any:
        metadata = self._expected_metadata()
        try:
            collection = self.client.get_or_create_collection(name=name, metadata=metadata)
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "longterm.collection.get_or_create_failed name=%s error=%s; recreating",
                name,
                sanitize_text(str(exc)),
            )
            try:
                self.client.delete_collection(name)
            except Exception:  # noqa: BLE001
                pass
            collection = self.client.create_collection(name=name, metadata=metadata)

        existing_meta = getattr(collection, "metadata", {}) or {}
        stored_dim = existing_meta.get("embedding_dim")
        if stored_dim is not None and int(stored_dim) != int(self._dim):
            logger.warning(
                "longterm.collection.dim_mismatch name=%s stored_dim=%s expected_dim=%s; recreating",
                name,
                stored_dim,
                self._dim,
            )
            try:
                self.client.delete_collection(name)
            except Exception:  # noqa: BLE001
                pass
            collection = self.client.create_collection(name=name, metadata=metadata)

        return collection

    # ------------------------------------------------------------------ #
    # Embedding helpers
    # ------------------------------------------------------------------ #

    def _probe_embedding_dim(self) -> tuple[int, str]:
        """Return (dim, model_label) for the currently-active embedding backend."""
        if self.openai_client is None:
            return SimpleEmbeddingFunction.DIM, "offline"
        try:
            response = self.openai_client.embeddings.create(
                model=self.config.embedding_model,
                input=[PROBE_TEXT],
            )
            vector = list(response.data[0].embedding)
            if vector:
                return len(vector), self.config.embedding_model
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "longterm.probe_embedding_failed model=%s error=%s; falling back to offline",
                self.config.embedding_model,
                sanitize_text(str(exc)),
            )
            self.openai_client = None
            self._mode = "offline"
        return SimpleEmbeddingFunction.DIM, "offline"

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        logger.info("longterm.embed.start text_count=%s", len(texts))
        started = time.perf_counter()
        if self.openai_client is None:
            vectors = SimpleEmbeddingFunction().embed_documents(texts)
            logger.info(
                "longterm.embed.done mode=offline elapsed_ms=%s",
                int((time.perf_counter() - started) * 1000),
            )
            return vectors
        response = self.openai_client.embeddings.create(
            model=self.config.embedding_model,
            input=texts,
        )
        vectors = [list(item.embedding) for item in response.data]
        logger.info(
            "longterm.embed.done mode=openai model=%s elapsed_ms=%s",
            self.config.embedding_model,
            int((time.perf_counter() - started) * 1000),
        )
        return vectors

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def upsert_records(self, records: list[ArchivalRecord]) -> None:
        if not records:
            return
        logger.info("longterm.upsert.start record_count=%s", len(records))
        started = time.perf_counter()
        ids = [f"{item.role}:{item.timestamp}:{idx}" for idx, item in enumerate(records)]
        docs = [item.summary for item in records]
        metadatas = [{"role": item.role, "timestamp": item.timestamp} for item in records]
        try:
            vectors = self._embed_texts(docs)
            if vectors and len(vectors[0]) != self._dim:
                logger.warning(
                    "longterm.upsert.dim_drift got=%s expected=%s; rebuilding collection",
                    len(vectors[0]),
                    self._dim,
                )
                self._dim = len(vectors[0])
                self.collection_name = self._physical_collection_name()
                self.collection = self._open_or_reset_collection(self.collection_name)
            self.collection.upsert(
                ids=ids, documents=docs, metadatas=metadatas, embeddings=vectors
            )
        except Exception as exc:
            logger.warning(
                "longterm.upsert.failed error=%s; skipping persistence", sanitize_text(str(exc))
            )
            return
        logger.info(
            "longterm.upsert.done record_count=%s elapsed_ms=%s sample=%s",
            len(records),
            int((time.perf_counter() - started) * 1000),
            sanitize_text(docs[0] if docs else ""),
        )

    def query(self, text: str, *, role: str | None = None, limit: int | None = None) -> list[str]:
        if not text.strip():
            return []
        logger.info(
            "longterm.query.start role=%s limit=%s text=%s",
            role,
            limit,
            sanitize_text(text),
        )
        started = time.perf_counter()
        k = limit or self.config.retrieval_limit
        try:
            query_vector = self._embed_texts([text])
            kwargs: dict[str, Any] = {"query_embeddings": query_vector, "n_results": k}
            if role:
                kwargs["where"] = {"role": role}
            result = self.collection.query(**kwargs)
        except Exception as exc:
            logger.warning(
                "longterm.query.failed error=%s; returning empty hits",
                sanitize_text(str(exc)),
            )
            return []
        documents = result.get("documents", [])
        if not documents:
            logger.info(
                "longterm.query.done role=%s hit_count=0 elapsed_ms=%s",
                role,
                int((time.perf_counter() - started) * 1000),
            )
            return []
        hits = [str(item) for item in documents[0] if item]
        logger.info(
            "longterm.query.done role=%s hit_count=%s elapsed_ms=%s",
            role,
            len(hits),
            int((time.perf_counter() - started) * 1000),
        )
        return hits
