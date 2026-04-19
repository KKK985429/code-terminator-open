from __future__ import annotations

import re
from urllib.parse import urlsplit

_REMOTE_SCHEMES = {"http", "https", "ssh", "git"}
_SCP_LIKE_GIT_PATTERN = re.compile(r"^[^\s@]+@[^\s:]+:[^\s]+$")


def normalize_remote_collaboration_target(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        return ""

    lowered = candidate.lower()
    if lowered.startswith("file://"):
        return ""
    if candidate.startswith(("/", "./", "../", "~/")):
        return ""
    if re.match(r"^[A-Za-z]:[\\/]", candidate):
        return ""

    if "://" in candidate:
        parsed = urlsplit(candidate)
        if parsed.scheme.lower() not in _REMOTE_SCHEMES:
            return ""
        if not parsed.netloc:
            return ""
        return candidate

    if _SCP_LIKE_GIT_PATTERN.match(candidate):
        return candidate

    return ""


def is_remote_collaboration_target(value: str) -> bool:
    return bool(normalize_remote_collaboration_target(value))
