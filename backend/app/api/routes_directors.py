"""
Directors Workplace — the director-side mirror of the Producer Marketplace.

Every row returned here is a real registered account with role='director'.
There is no seed script for this list (unlike producers, which start with
a fictional demo directory): the moment someone signs up as a director,
routes_auth.register() creates their User row, and that's the only thing
that makes them show up here — this endpoint just queries User directly.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.routes_auth import get_current_user
from app.db.auth_db import Follow, Project, User, get_db

router = APIRouter(prefix="/api/directors", tags=["directors"])


@router.get("")
def list_directors(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    directors = (
        db.query(User)
        .filter(User.role == "director", User.id != current_user.id, User.is_active == True)  # noqa: E712
        .order_by(User.created_at.desc())
        .all()
    )
    director_ids = [d.id for d in directors]

    project_counts: dict[str, int] = {}
    if director_ids:
        for owner_id, in db.query(Project.owner_id).filter(Project.owner_id.in_(director_ids)).all():
            project_counts[owner_id] = project_counts.get(owner_id, 0) + 1

    follower_counts: dict[str, int] = {}
    following_ids: set[str] = set()
    if director_ids:
        for f in db.query(Follow).filter(Follow.followee_type == "user", Follow.followee_id.in_(director_ids)).all():
            follower_counts[f.followee_id] = follower_counts.get(f.followee_id, 0) + 1

        following_ids = {
            row[0]
            for row in db.query(Follow.followee_id).filter(
                Follow.follower_id == current_user.id,
                Follow.followee_type == "user",
                Follow.followee_id.in_(director_ids),
            ).all()
        }

    return {
        "directors": [
            {
                "id": d.id,
                "name": d.full_name,
                "email": d.email if d.public_profile else None,
                "project_count": project_counts.get(d.id, 0),
                "followers_count": follower_counts.get(d.id, 0),
                "is_following": d.id in following_ids,
                "joined_at": d.created_at.isoformat(),
            }
            for d in directors
        ],
        "total": len(directors),
    }