from __future__ import annotations

from typing import Any


def navigate_create_path(root: dict[str, Any], dotted_path: str) -> tuple[dict[str, Any], str]:
    keys = [key for key in dotted_path.split(".") if key]
    if not keys:
        raise ValueError("path must be a non-empty dot separated string")
    node = root
    for key in keys[:-1]:
        current = node.get(key)
        if not isinstance(current, dict):
            current = {}
            node[key] = current
        node = current
    return node, keys[-1]
