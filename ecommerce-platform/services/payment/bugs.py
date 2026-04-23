from __future__ import annotations

from services.shared.settings import bool_env


class BugFlags:
    @staticmethod
    def float_precision_error() -> bool:
        return bool_env("BUG_FLOAT_PRECISION", False)
