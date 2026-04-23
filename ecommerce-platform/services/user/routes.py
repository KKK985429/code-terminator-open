from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from services.shared.database import get_db
from services.user.schemas import (
    LoginResponse,
    UserCreate,
    UserDiscountResponse,
    UserLogin,
    UserResponse,
)
from services.user.service import get_user, get_vip_discount, login_user, register_user


router = APIRouter()


@router.post("/users/register", response_model=UserResponse, status_code=201)
def register_user_route(payload: UserCreate, db: Session = Depends(get_db)) -> UserResponse:
    try:
        return UserResponse.model_validate(register_user(db, payload))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/users/login", response_model=LoginResponse)
def login_user_route(payload: UserLogin, db: Session = Depends(get_db)) -> LoginResponse:
    try:
        user = login_user(db, payload)
        return LoginResponse(success=True, user_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.get("/users/{user_id}", response_model=UserResponse)
def get_user_route(user_id: int, db: Session = Depends(get_db)) -> UserResponse:
    try:
        return UserResponse.model_validate(get_user(db, user_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/users/{user_id}/discount", response_model=UserDiscountResponse)
def get_discount_route(user_id: int, db: Session = Depends(get_db)) -> UserDiscountResponse:
    try:
        return UserDiscountResponse(user_id=user_id, discount_rate=get_vip_discount(db, user_id))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
