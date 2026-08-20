"""
Real follow/unfollow system shared by directors and producers — the same
mechanic Instagram uses, applied to CineFlow AI's two account types.

A "followee" is either:
  - type "user":     a real account (director or producer), identified by
                      User.id. This is what the Directors Workplace and a
                      producer's own account are followed through.
  - type "producer":  a row in the producer directory, identified by
                      Producer.id. This covers both real producer accounts
                      (which each have a linked Producer row — see
                      routes_auth.register) and the seeded demo producers.

Every row in `follows` is written the moment someone clicks Follow, and
genuinely deleted the moment they click Unfollow. Nothing here is a cached
or simulated counter — GET /api/social/followers and /following always
read the live table.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.routes_auth import get_current_user
from app.db.auth_db import Follow, Producer, User, get_db
from app.services.activity_service import log_activity

router = APIRouter(prefix="/api/social", tags=["social"])

VALID_TYPES = {"user", "producer"}


class FollowTarget(BaseModel):
    followee_type: str
    followee_id: str


def _resolve_display(db: Session, followee_type: str, followee_id: str) -> dict | None:
    if followee_type == "user":
        u = db.query(User).filter(User.id == followee_id).first()
        if u is None:
            return None
        return {"id": u.id, "name": u.full_name, "subtitle": u.role.capitalize(), "role": u.role, "type": "user"}
    if followee_type == "producer":
        p = db.query(Producer).filter(Producer.id == followee_id).first()
        if p is None:
            return None
        return {"id": p.id, "name": p.name, "subtitle": p.company, "role": "producer", "type": "producer"}
    return None


def _assert_not_self(current_user: User, db: Session, followee_type: str, followee_id: str) -> None:
    if followee_type == "user" and followee_id == current_user.id:
        raise HTTPException(status_code=400, detail="You can't follow yourself.")
    if followee_type == "producer":
        p = db.query(Producer).filter(Producer.id == followee_id).first()
        if p is not None and p.user_id == current_user.id:
            raise HTTPException(status_code=400, detail="You can't follow yourself.")


@router.post("/follow")
def follow(
    payload: FollowTarget,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.followee_type not in VALID_TYPES:
        raise HTTPException(status_code=400, detail="followee_type must be 'user' or 'producer'.")

    target = _resolve_display(db, payload.followee_type, payload.followee_id)
    if target is None:
        raise HTTPException(status_code=404, detail="That account no longer exists.")
    _assert_not_self(current_user, db, payload.followee_type, payload.followee_id)

    existing = (
        db.query(Follow)
        .filter(
            Follow.follower_id == current_user.id,
            Follow.followee_type == payload.followee_type,
            Follow.followee_id == payload.followee_id,
        )
        .first()
    )
    if existing:
        return {"status": "already_following", "followee_id": payload.followee_id}

    db.add(Follow(
        id=str(uuid.uuid4()),
        follower_id=current_user.id,
        followee_type=payload.followee_type,
        followee_id=payload.followee_id,
    ))
    db.commit()

    log_activity(
        db,
        user_id=current_user.id,
        event_type="started_following",
        title=f"You followed {target['name']}",
        description=f"{target['subtitle']} · now in your Following list.",
    )

    return {"status": "following", "followee_id": payload.followee_id}


@router.post("/unfollow")
def unfollow(
    payload: FollowTarget,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(Follow)
        .filter(
            Follow.follower_id == current_user.id,
            Follow.followee_type == payload.followee_type,
            Follow.followee_id == payload.followee_id,
        )
        .first()
    )
    if row is None:
        return {"status": "not_following", "followee_id": payload.followee_id}

    db.delete(row)
    db.commit()
    return {"status": "unfollowed", "followee_id": payload.followee_id}


@router.get("/following")
def my_following(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Real-time list of everyone the current user follows."""
    rows = (
        db.query(Follow)
        .filter(Follow.follower_id == current_user.id)
        .order_by(Follow.created_at.desc())
        .all()
    )
    out = []
    for r in rows:
        target = _resolve_display(db, r.followee_type, r.followee_id)
        if target is None:
            continue  # followee account was deleted since — skip silently
        out.append({**target, "followed_at": r.created_at.isoformat()})
    return {"following": out, "count": len(out)}


@router.get("/followers")
def my_followers(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Real-time list of everyone who follows the current user — as a user
    account directly, and (if this account has a linked producer profile)
    everyone who follows that producer directory entry too.
    """
    rows = (
        db.query(Follow)
        .filter(Follow.followee_type == "user", Follow.followee_id == current_user.id)
        .all()
    )

    my_producer_profile = db.query(Producer).filter(Producer.user_id == current_user.id).first()
    if my_producer_profile is not None:
        rows += (
            db.query(Follow)
            .filter(Follow.followee_type == "producer", Follow.followee_id == my_producer_profile.id)
            .all()
        )

    follower_ids = {r.follower_id for r in rows}
    followers = {u.id: u for u in db.query(User).filter(User.id.in_(follower_ids)).all()}

    out = []
    for r in rows:
        u = followers.get(r.follower_id)
        if u is None:
            continue
        out.append({
            "id": u.id,
            "name": u.full_name,
            "subtitle": u.role.capitalize(),
            "role": u.role,
            "type": "user",
            "followed_at": r.created_at.isoformat(),
        })
    out.sort(key=lambda x: x["followed_at"], reverse=True)
    return {"followers": out, "count": len(out)}


@router.get("/status")
def follow_status(
    followee_type: str,
    followee_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    exists = (
        db.query(Follow)
        .filter(
            Follow.follower_id == current_user.id,
            Follow.followee_type == followee_type,
            Follow.followee_id == followee_id,
        )
        .first()
        is not None
    )
    return {"following": exists}