from __future__ import annotations

from services.shared.settings import bool_env


class BugFlags:
    @staticmethod
    def race_condition_no_lock() -> bool:
        return bool_env("BUG_RACE_CONDITION", False)
