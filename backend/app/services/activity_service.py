"""
Central place to write Activity rows, so every part of the backend logs
activity the same way instead of each route inventing its own format.
Every call here corresponds to something that genuinely just happened —
this is not a simulated feed.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.db.auth_db import Activity


def log_activity(
    db: Session,
    *,
    user_id: str,
    event_type: str,
    title: str,
    description: str = "",
    project_id: str | None = None,
) -> None:
    db.add(Activity(
        id=str(uuid.uuid4()),
        user_id=user_id,
        activity_type=event_type,
        title=title,
        description=description,
        project_id=project_id,
    ))
    db.commit()
