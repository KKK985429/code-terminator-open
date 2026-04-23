from __future__ import annotations

from fastapi.testclient import TestClient

from services.order.main import app


def test_create_order_route_returns_created(seeded_db):
    _, ids = seeded_db
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/orders",
            json={
                "user_id": ids["user_id"],
                "items": [{"product_id": ids["product_id"], "quantity": 1}],
            },
        )

        assert response.status_code == 201
        payload = response.json()
        assert payload["user_id"] == ids["user_id"]
        assert payload["status"] == "paid"


def test_get_user_orders_route_returns_empty_list(seeded_db):
    _, ids = seeded_db
    with TestClient(app) as client:
        response = client.get(f"/api/v1/orders/user/{ids['second_user_id']}")

        assert response.status_code == 200
        assert response.json() == []
