from __future__ import annotations

from collections.abc import Iterable


def summarize_records(records: Iterable[str], *, limit: int = 4) -> str:
    """Compress a working-memory window into a compact summary."""
    items = [item.strip().replace("\n", " ") for item in records if item.strip()]
    if not items:
        return "No significant events."
    head = items[:limit]
    return " | ".join(head)
