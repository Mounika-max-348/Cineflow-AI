"""
Real auth endpoints backed by SQLite (or Postgres via AUTH_DATABASE_URL) and
JWT bearer tokens. `get_current_user` is exported so other routers (e.g.
projects) can require login and scope data per user.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.db.auth_db import Producer, User, get_db
from app.models.auth_schemas import Token, UserCreate, UserLogin, UserPublic, UserSettingsUpdate
from app.services.activity_service import log_activity
from app.services.auth_service import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    new_user_id,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    user = User(
        id=new_user_id(),
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    if user.role == "producer":
        # Real, linked directory entry — zero-state, not seeded fake stats.
        # This is what lets a producer account actually receive connection
        # requests from directors (see routes_producers.py).
        db.add(Producer(
            id=new_user_id(),
            user_id=user.id,
            name=user.full_name,
            company="Not set yet",
            country="Not set",
            languages="English",
            genres="",
            investment_min=0,
            investment_max=0,
            films_produced=0,
            success_rate_pct=0,
            avg_roi_x="—",
            rating="—",
        ))
        db.commit()

    log_activity(
        db, user_id=user.id, event_type="account_created",
        title="Account created",
        description=f"Welcome to CineFlow AI, {user.full_name.split(' ')[0]} — your {user.role} account is ready.",
    )

    token = create_access_token(user.id, user.email)
    return Token(access_token=token, user=UserPublic.model_validate(user))


@router.post("/login", response_model=Token)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated.")

    token = create_access_token(user.id, user.email)
    return Token(access_token=token, user=UserPublic.model_validate(user))


def get_current_user(
    token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    if token is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    try:
        payload = decode_access_token(token)
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    user = db.query(User).filter(User.id == payload.get("sub")).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists.")
    return user


@router.get("/me", response_model=UserPublic)
def me(current_user: User = Depends(get_current_user)):
    return UserPublic.model_validate(current_user)


@router.patch("/settings", response_model=UserPublic)
def update_settings(
    payload: UserSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.email_notifications is not None:
        current_user.email_notifications = payload.email_notifications
    if payload.public_profile is not None:
        current_user.public_profile = payload.public_profile
    if payload.currency is not None:
        current_user.currency = payload.currency
    db.commit()
    db.refresh(current_user)
    return UserPublic.model_validate(current_user)
