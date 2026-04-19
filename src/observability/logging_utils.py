from __future__ import annotations

import contextvars
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path

_run_tag_var: contextvars.ContextVar[str] = contextvars.ContextVar("run_tag", default="-")
_is_configured = False
_llm_logger: logging.Logger | None = None
_SECRET_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9_-]{8,})"),
    re.compile(r"(ark-[A-Za-z0-9_-]{8,})"),
]


class _RunTagFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_tag = _run_tag_var.get()
        return True


def set_run_tag(run_tag: str | None) -> None:
    _run_tag_var.set(run_tag or "-")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def get_llm_logger() -> logging.Logger:
    global _llm_logger
    if _llm_logger is not None:
        return _llm_logger

    logs_dir = Path("artifacts/logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("llm_responses")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.handlers.clear()

    handler = logging.FileHandler(logs_dir / "llm_responses.log", encoding="utf-8")
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    _llm_logger = logger
    return logger


def sanitize_text(text: str, *, max_len: int = 240) -> str:
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("***REDACTED***", redacted)
    if len(redacted) <= max_len:
        return redacted
    return f"{redacted[:max_len]}...(truncated)"


def setup_logging(
    *,
    run_tag: str | None = None,
    level: str | None = None,
    file_logging: bool = True,
) -> None:
    global _is_configured

    set_run_tag(run_tag)
    log_level = (level or os.getenv("APP_LOG_LEVEL", "INFO")).upper()
    numeric_level = getattr(logging, log_level, logging.INFO)

    if _is_configured:
        root = logging.getLogger()
        root.setLevel(numeric_level)
        for handler in root.handlers:
            handler.setLevel(numeric_level)
        return

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(numeric_level)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | run_tag=%(run_tag)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run_tag_filter = _RunTagFilter()

    console = logging.StreamHandler()
    console.setLevel(numeric_level)
    console.setFormatter(formatter)
    console.addFilter(run_tag_filter)
    root.addHandler(console)

    if file_logging and os.getenv("APP_LOG_FILE", "1") != "0":
        logs_dir = Path("artifacts/logs")
        logs_dir.mkdir(parents=True, exist_ok=True)
        tag = run_tag or datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        safe_tag = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in tag)
        logfile = logs_dir / f"{safe_tag}.log"
        file_handler = logging.FileHandler(logfile, encoding="utf-8")
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(run_tag_filter)
        root.addHandler(file_handler)

    _is_configured = True
