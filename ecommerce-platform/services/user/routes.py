from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from services.shared.database import get_db
from services.shared.event_log import write_exception_event
from services.user.schemas import (
    LoginResponse,
    UserCreate,
    UserDiscountResponse,
    UserLogin,
    UserResponse,
)
from services.user.service import get_user, get_vip_discount, login_user, register_user


router = APIRouter()
logger = structlog.get_logger()


@router.post("/users/register", response_model=UserResponse, status_code=201)
def register_user_route(
    payload: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> UserResponse:
    try:
        return UserResponse.model_validate(register_user(db, payload))
    except Exception as exc:
        logger.warning("user_register_failed", error=str(exc), exc_info=True)
        write_exception_event(
            service="user-service",
            level="warning",
            event="user_register_failed",
            exc=exc,
            trace_id=getattr(request.state, "trace_id", None),
            source="service",
            method=request.method,
            path=request.url.path,
            status_code=400,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/users/login", response_model=LoginResponse)
def login_user_route(
    payload: UserLogin,
    request: Request,
    db: Session = Depends(get_db),
) -> LoginResponse:
    try:
        user = login_user(db, payload)
        return LoginResponse(success=True, user_id=user.id)
    except ValueError as exc:
        logger.warning("user_login_failed", error=str(exc), exc_info=True)
        write_exception_event(
            service="user-service",
            level="warning",
            event="user_login_failed",
            exc=exc,
            trace_id=getattr(request.state, "trace_id", None),
            source="service",
            method=request.method,
            path=request.url.path,
            status_code=401,
        )
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.get("/users/{user_id}", response_model=UserResponse)
def get_user_route(user_id: int, request: Request, db: Session = Depends(get_db)) -> UserResponse:
    try:
        return UserResponse.model_validate(get_user(db, user_id))
    except ValueError as exc:
        logger.warning("user_not_found", error=str(exc), exc_info=True)
        write_exception_event(
            service="user-service",
            level="warning",
            event="user_lookup_failed",
            exc=exc,
            trace_id=getattr(request.state, "trace_id", None),
            source="service",
            method=request.method,
            path=request.url.path,
            status_code=404,
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/users/{user_id}/discount", response_model=UserDiscountResponse)
def get_discount_route(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> UserDiscountResponse:
    try:
        return UserDiscountResponse(user_id=user_id, discount_rate=get_vip_discount(db, user_id))
    except Exception as exc:
        logger.error("user_discount_failed", error=str(exc), exc_info=True)
        write_exception_event(
            service="user-service",
            level="error",
            event="user_discount_failed",
            exc=exc,
            trace_id=getattr(request.state, "trace_id", None),
            source="service",
            method=request.method,
            path=request.url.path,
            status_code=500,
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc
