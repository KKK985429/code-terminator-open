from __future__ import annotations

from services.shared.settings import bool_env, env


class BugFlags:
    @staticmethod
    def race_condition_no_lock() -> bool:
        return bool_env("BUG_RACE_CONDITION", False)

    @staticmethod
    def missing_row_attribute_error() -> bool:
        return bool_env("BUG_INVENTORY_MISSING_ROW", False)

    @staticmethod
    def broken_product_id() -> int:
        return int(env("BUG_INVENTORY_BROKEN_PRODUCT_ID", "7"))
