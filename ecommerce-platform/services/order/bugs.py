from __future__ import annotations

from services.shared.settings import bool_env


class BugFlags:
    @staticmethod
    def index_error() -> bool:
        return bool_env("BUG_INDEX_ERROR", False)

    @staticmethod
    def coupon_lookup_key_error() -> bool:
        return bool_env("BUG_ORDER_COUPON_KEY", False)
