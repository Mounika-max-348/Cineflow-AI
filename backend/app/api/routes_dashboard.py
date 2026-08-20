"""
Dashboard summary stats — computed live from the real database, scoped to
the logged-in user. A brand-new account gets all zeros here; there is no
seeded/demo data merged in to make the UI look more populated than it is.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.routes_auth import get_current_user
from app.db.auth_db import Project, User, get_db

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats")
def my_stats(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    projects = db.query(Project).filter(Project.owner_id == current_user.id).all()
    return {
        "role": current_user.role,
        "total_projects": len(projects),
        "in_progress": len([p for p in projects if p.status == "analyzing"]),
        "completed": len([p for p in projects if p.status == "completed"]),
        "failed": len([p for p in projects if p.status == "failed"]),
        # Real placeholders for features not yet built — reported honestly as
        # zero/empty rather than populated with hardcoded demo numbers.
        "producer_matches": 0,
        "funding_committed": 0,
        "meetings_scheduled": 0,
    }
