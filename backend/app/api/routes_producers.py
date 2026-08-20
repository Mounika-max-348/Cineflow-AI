"""
Producer marketplace endpoints.

GET  /api/producers          — real SQL-filtered query, not client-side fakery
POST /api/producers/{id}/connect — creates a real ProducerConnection row and
                                    logs a real activity event
GET  /api/producers/connections  — the current user's own connection requests
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.routes_auth import get_current_user
from app.db.auth_db import Follow, Producer, ProducerConnection, User, get_db
from app.services.activity_service import log_activity

router = APIRouter(prefix="/api/producers", tags=["producers"])


def _to_dict(p: Producer, connected_ids: set[str], follower_counts: dict[str, int], following_ids: set[str]) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "company": p.company,
        "country": p.country,
        "languages": p.languages.split(","),
        "genres": p.genres.split(","),
        "investment_min": p.investment_min,
        "investment_max": p.investment_max,
        "films_produced": p.films_produced,
        "success_rate_pct": p.success_rate_pct,
        "avg_roi_x": p.avg_roi_x,
        "rating": p.rating,
        "connection_status": "requested" if p.id in connected_ids else None,
        "followers_count": follower_counts.get(p.id, 0),
        "is_following": p.id in following_ids,
    }


@router.get("")
def list_producers(
    country: str | None = None,
    genre: str | None = None,
    min_budget: int | None = None,
    max_budget: int | None = None,
    language: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Producer)

    if country and country != "all":
        query = query.filter(Producer.country == country)
    if genre and genre != "all":
        query = query.filter(Producer.genres.like(f"%{genre}%"))
    if language and language != "all":
        query = query.filter(Producer.languages.like(f"%{language}%"))
    if min_budget is not None:
        query = query.filter(Producer.investment_max >= min_budget)
    if max_budget is not None:
        query = query.filter(Producer.investment_min <= max_budget)

    producers = query.order_by(Producer.success_rate_pct.desc()).all()
    producer_ids = [p.id for p in producers]

    my_connections = (
        db.query(ProducerConnection.producer_id)
        .filter(ProducerConnection.director_id == current_user.id)
        .all()
    )
    connected_ids = {row[0] for row in my_connections}

    follower_counts: dict[str, int] = {}
    following_ids: set[str] = set()
    if producer_ids:
        for f in db.query(Follow).filter(Follow.followee_type == "producer", Follow.followee_id.in_(producer_ids)).all():
            follower_counts[f.followee_id] = follower_counts.get(f.followee_id, 0) + 1
        following_ids = {
            row[0]
            for row in db.query(Follow.followee_id).filter(
                Follow.follower_id == current_user.id,
                Follow.followee_type == "producer",
                Follow.followee_id.in_(producer_ids),
            ).all()
        }

    return {
        "producers": [_to_dict(p, connected_ids, follower_counts, following_ids) for p in producers],
        "total_in_directory": db.query(Producer).count(),
    }


@router.get("/filters")
def get_filter_options(db: Session = Depends(get_db)):
    """Real distinct values pulled from the actual data, not a hardcoded list."""
    producers = db.query(Producer).all()
    countries = sorted({p.country for p in producers})
    genres = sorted({g for p in producers for g in p.genres.split(",")})
    languages = sorted({lang for p in producers for lang in p.languages.split(",")})
    return {"countries": countries, "genres": genres, "languages": languages}


@router.post("/{producer_id}/connect")
def connect_with_producer(
    producer_id: str,
    project_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    producer = db.query(Producer).filter(Producer.id == producer_id).first()
    if producer is None:
        raise HTTPException(status_code=404, detail="Producer not found.")

    existing = (
        db.query(ProducerConnection)
        .filter(
            ProducerConnection.director_id == current_user.id,
            ProducerConnection.producer_id == producer_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="You already have a pending request with this producer.")

    connection = ProducerConnection(
        id=str(uuid.uuid4()),
        director_id=current_user.id,
        producer_id=producer_id,
        project_id=project_id,
        status="pending",
    )
    db.add(connection)
    db.commit()

    log_activity(
        db,
        user_id=current_user.id,
        event_type="producer_connection_requested",
        title=f"Connection requested — {producer.name}",
        description=f"You reached out to {producer.company} ({producer.country}).",
        project_id=project_id,
    )

    return {"status": "requested", "producer_id": producer_id}


@router.get("/connections")
def my_connections(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (
        db.query(ProducerConnection)
        .filter(ProducerConnection.director_id == current_user.id)
        .order_by(ProducerConnection.created_at.desc())
        .all()
    )
    producer_ids = {r.producer_id for r in rows}
    producers = {p.id: p for p in db.query(Producer).filter(Producer.id.in_(producer_ids)).all()}
    return {
        "connections": [
            {
                "id": r.id,
                "producer_id": r.producer_id,
                "producer_name": producers[r.producer_id].name if r.producer_id in producers else "Unknown",
                "producer_company": producers[r.producer_id].company if r.producer_id in producers else "",
                "status": r.status,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


@router.get("/inbox")
def producer_inbox(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Incoming connection requests for a producer account. Empty for
    directors (they have no inbox) and for producers with no requests yet —
    genuinely zero, not a placeholder."""
    my_producer_profile = db.query(Producer).filter(Producer.user_id == current_user.id).first()
    if my_producer_profile is None:
        return {"requests": [], "note": "No linked producer profile — only producer accounts have an inbox."}

    rows = (
        db.query(ProducerConnection)
        .filter(ProducerConnection.producer_id == my_producer_profile.id)
        .order_by(ProducerConnection.created_at.desc())
        .all()
    )
    director_ids = {r.director_id for r in rows}
    directors = {u.id: u for u in db.query(User).filter(User.id.in_(director_ids)).all()}

    return {
        "requests": [
            {
                "id": r.id,
                "director_name": directors[r.director_id].full_name if r.director_id in directors else "Unknown",
                "director_email": directors[r.director_id].email if r.director_id in directors else "",
                "project_id": r.project_id,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


@router.post("/connections/{connection_id}/respond")
def respond_to_connection(
    connection_id: str,
    decision: str,  # "accepted" | "declined"
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if decision not in ("accepted", "declined"):
        raise HTTPException(status_code=400, detail="decision must be 'accepted' or 'declined'.")

    connection = db.query(ProducerConnection).filter(ProducerConnection.id == connection_id).first()
    if connection is None:
        raise HTTPException(status_code=404, detail="Connection request not found.")

    my_producer_profile = db.query(Producer).filter(Producer.user_id == current_user.id).first()
    if my_producer_profile is None or connection.producer_id != my_producer_profile.id:
        raise HTTPException(status_code=403, detail="This request wasn't sent to you.")

    connection.status = decision
    db.commit()

    # Notify the director who sent the request — a real cross-account
    # activity write, not a one-sided log.
    log_activity(
        db,
        user_id=connection.director_id,
        event_type="producer_connection_responded",
        title=f"{my_producer_profile.name} {decision} your request",
        description=f"{my_producer_profile.company or my_producer_profile.name} {decision} your connection request.",
        project_id=connection.project_id,
    )

    return {"status": decision, "connection_id": connection_id}


@router.get("/profile-stats")
def my_profile_stats(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Real followers/following counts, read live from the `follows` table
    (see routes_social.py) — the same Instagram-style follow graph that
    powers the Producer Marketplace and Directors Workplace follow
    buttons. Not derived from connection requests.
    """
    following_count = db.query(Follow).filter(Follow.follower_id == current_user.id).count()

    followers_count = (
        db.query(Follow)
        .filter(Follow.followee_type == "user", Follow.followee_id == current_user.id)
        .count()
    )
    my_producer_profile = db.query(Producer).filter(Producer.user_id == current_user.id).first()
    if my_producer_profile is not None:
        followers_count += (
            db.query(Follow)
            .filter(Follow.followee_type == "producer", Follow.followee_id == my_producer_profile.id)
            .count()
        )

    return {"following": following_count, "followers": followers_count}