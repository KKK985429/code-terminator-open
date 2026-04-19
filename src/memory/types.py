from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArchivalRecord:
    """Long-term archival record structure."""

    role: str
    summary: str
    timestamp: str
