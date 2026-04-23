from __future__ import annotations

import random

from locust import HttpUser, between, task


class EcommerceUser(HttpUser):
    wait_time = between(0.5, 2.0)
    host = "http://localhost:80"

    PRODUCT_IDS = list(range(1, 21))
    USER_IDS = list(range(1, 101))

    @task(7)
    def browse_inventory(self):
        product_id = random.choice(self.PRODUCT_IDS)
        self.client.get(f"/api/v1/inventory/{product_id}", name="/api/v1/inventory/[id]")

    @task(2)
    def create_order(self):
        items = [
            {
                "product_id": random.choice(self.PRODUCT_IDS),
                "quantity": random.randint(1, 3),
            }
            for _ in range(random.randint(1, 3))
        ]
        self.client.post(
            "/api/v1/orders",
            json={"user_id": random.choice(self.USER_IDS), "items": items},
            name="/api/v1/orders",
        )

    @task(1)
    def get_user_orders(self):
        user_id = random.choice(self.USER_IDS)
        self.client.get(f"/api/v1/orders/user/{user_id}", name="/api/v1/orders/user/[id]")

    @task(1)
    def get_payment_calculation(self):
        total = round(random.uniform(10.0, 999.99), 2)
        vip_level = random.randint(0, 3)
        self.client.get(
            f"/api/v1/payments/calculate?total={total}&vip_level={vip_level}",
            name="/api/v1/payments/calculate",
        )
