from __future__ import annotations

import pytest

from services.user.schemas import UserCreate
from services.user.service import get_vip_discount, register_user


def test_register_user_sets_default_vip_level(db_session):
    user = register_user(
        db_session,
        UserCreate(
            username="fresh-user",
            email="fresh@example.com",
            password="password123",
        ),
    )

    assert user.vip_level == 0


def test_bug_null_vip_breaks_discount_lookup(db_session, monkeypatch):
    monkeypatch.setenv("BUG_NULL_VIP", "true")
    user = register_user(
        db_session,
        UserCreate(
            username="bug-user",
            email="bug@example.com",
            password="password123",
        ),
    )

    with pytest.raises(TypeError):
        get_vip_discount(db_session, user.id)
