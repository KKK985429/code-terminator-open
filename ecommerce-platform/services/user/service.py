from __future__ import annotations

import hashlib
import os

import structlog
from sqlalchemy.orm import Session

from services.shared.models import User
from services.user.bugs import BugFlags
from services.user.schemas import UserCreate, UserLogin


logger = structlog.get_logger()


def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    hashed = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}:{hashed}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, hashed = stored_hash.split(":")
    except ValueError:
        return False
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest() == hashed


def register_user(db: Session, payload: UserCreate) -> User:
    if BugFlags.null_vip_level():
        user = User(
            username=payload.username,
            email=payload.email,
            password_hash=hash_password(payload.password),
            vip_level=None,
        )
    else:
        user = User(
            username=payload.username,
            email=payload.email,
            password_hash=hash_password(payload.password),
            vip_level=0,
        )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("user_registered", user_id=user.id, username=user.username)
    return user


def login_user(db: Session, payload: UserLogin) -> User:
    user = db.query(User).filter(User.username == payload.username).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise ValueError("Invalid username or password")
    return user


def get_user(db: Session, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise ValueError(f"User {user_id} not found")
    return user


def get_vip_discount(db: Session, user_id: int) -> float:
    user = get_user(db, user_id)
    discount_rates = [0.0, 0.05, 0.10, 0.15]
    return discount_rates[user.vip_level]
