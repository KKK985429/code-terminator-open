from __future__ import annotations

from decimal import Decimal

from services.shared.database import SessionLocal, init_database
from services.shared.models import Inventory, Product, User
from services.user.service import hash_password


def main() -> None:
    init_database()
    assert SessionLocal is not None
    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            users = [
                User(
                    username=f"user{i}",
                    email=f"user{i}@example.com",
                    password_hash=hash_password("password123"),
                    vip_level=i % 4,
                )
                for i in range(1, 101)
            ]
            db.add_all(users)
            db.flush()

        if db.query(Product).count() == 0:
            for i in range(1, 21):
                product = Product(
                    name=f"Product {i}",
                    price=Decimal(f"{9 + i}.99"),
                    category="general",
                    image_url=f"https://minio.local/product-{i}.png",
                )
                db.add(product)
                db.flush()
                db.add(
                    Inventory(
                        product_id=product.id,
                        total_qty=200,
                        reserved_qty=0,
                        sold_qty=0,
                    )
                )
        else:
            inventories = db.query(Inventory).all()
            for inventory in inventories:
                inventory.total_qty = max(inventory.total_qty, inventory.sold_qty + 200)
                inventory.reserved_qty = 0

        db.commit()
        print("database initialized")
    finally:
        db.close()


if __name__ == "__main__":
    main()
