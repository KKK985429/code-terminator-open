from __future__ import annotations

from services.shared.settings import bool_env


class BugFlags:
    @staticmethod
    def null_vip_level() -> bool:
        return bool_env("BUG_NULL_VIP", False)
