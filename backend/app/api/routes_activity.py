"""
Real activity feed — every row returned here was written by
services/activity_service.log_activity() at the moment something actually
happened (account created, project created, an agent completing/failing).
A brand-new account has an empty list until it does something.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.routes_auth import get_current_user
from app.db.auth_db import Activity, User, get_db

router = APIRouter(prefix="/api/activity", tags=["activity"])


@router.get("")
def list_my_activity(
    limit: int = 10,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    events = (
        db.query(Activity)
        .filter(Activity.user_id == current_user.id)
        .order_by(Activity.created_at.desc())
        .limit(min(limit, 50))
        .all()
    )
    return {
        "events": [
            {
                "id": e.id,
                "event_type": e.activity_type,
                "title": e.title,
                "description": e.description,
                "project_id": e.project_id,
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ]
    }
