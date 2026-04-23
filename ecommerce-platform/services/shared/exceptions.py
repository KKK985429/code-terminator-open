from __future__ import annotations


class InsufficientStockError(Exception):
    def __init__(self, product_id: int, requested: int, available: int):
        self.product_id = product_id
        self.requested = requested
        self.available = available
        super().__init__(
            f"Product {product_id}: requested {requested}, available {available}"
        )


class OrderNotFoundError(Exception):
    pass


class PaymentError(Exception):
    pass


class InvalidOrderStatusError(Exception):
    def __init__(self, current: str, expected: list[str]):
        super().__init__(f"Order status is '{current}', expected one of {expected}")
