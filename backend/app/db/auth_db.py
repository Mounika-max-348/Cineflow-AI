"""
Auth storage — a real relational DB (SQLite by default, Postgres-compatible
via AUTH_DATABASE_URL) for users, separate from ClickHouse.

Why not put users in ClickHouse? ClickHouse is a MergeTree analytical store —
it has no unique constraints, no efficient point-updates, and is the wrong
tool for password/session data. Auth needs real ACID guarantees for things
like "email must be unique." SQLite (upgradeable to Postgres by changing
AUTH_DATABASE_URL) is the correct real choice here, not a shortcut.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.AUTH_DATABASE_URL,
    connect_args={"check_same_thread": False} if settings.AUTH_DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(String, nullable=False, default="director")  # 'director' | 'producer'
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    email_notifications = Column(Boolean, default=True)
    public_profile = Column(Boolean, default=False)
    currency = Column(String, default="USD")


class Project(Base):
    """
    Real, persistent project storage — replaces the earlier in-memory dict.
    Every project belongs to exactly one owner (director) and is invisible
    to every other account, including other directors and producers, unless
    a future sharing/marketplace feature explicitly grants access.
    """
    __tablename__ = "projects"

    id = Column(String, primary_key=True)
    owner_id = Column(String, index=True, nullable=False)
    title = Column(String, nullable=False, default="Untitled Project")
    input_mode = Column(String, nullable=False)  # 'idea' | 'screenplay'
    raw_text = Column(String, nullable=False)
    already_funded = Column(Boolean, default=False)
    country_context = Column(String, nullable=True)
    status = Column(String, nullable=False, default="draft")  # draft | analyzing | completed | failed
    created_at = Column(DateTime, default=datetime.utcnow)


class Activity(Base):
    """
    Real activity log — every row here corresponds to something that
    genuinely happened (project created, agent started/completed/failed,
    etc.), written at the moment it happens. This is what the dashboard's
    "Recent Activity" feed reads from; nothing here is a hardcoded demo list.
    """
    __tablename__ = "activities"

    id = Column(String, primary_key=True)
    user_id = Column(String, index=True, nullable=False)
    activity_type = Column(String, nullable=False)  # project_created | analysis_started | agent_completed | agent_failed | analysis_completed | analysis_failed
    title = Column(String, nullable=False)
    description = Column(String, nullable=False, default="")
    project_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class Producer(Base):
    """
    Real producer directory. Seeded once via scripts/seed_producers.py with
    clearly fictional companies/people (per the project's own rule: never
    use real people/companies as fake investors). Filtering in the API is a
    genuine SQL WHERE clause, not client-side fakery over a hardcoded list.
    """
    __tablename__ = "producers"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=True, index=True)  # linked real account, if any (null for seeded demo producers)
    name = Column(String, nullable=False)
    company = Column(String, nullable=False)
    country = Column(String, nullable=False, index=True)
    languages = Column(String, nullable=False)  # comma-separated
    genres = Column(String, nullable=False)      # comma-separated
    investment_min = Column(Integer, nullable=False)
    investment_max = Column(Integer, nullable=False)
    films_produced = Column(Integer, nullable=False, default=0)
    success_rate_pct = Column(Integer, nullable=False, default=0)
    avg_roi_x = Column(String, nullable=False, default="1.0x")
    rating = Column(String, nullable=False, default="4.5")


class ProducerConnection(Base):
    """
    A real connection request from a director to a producer. Created the
    moment someone clicks "Connect" — nothing here is simulated. Status
    starts at 'pending' since there is no real producer on the other end
    to accept it yet (that requires an actual producer account taking
    action, which is a future feature — see README roadmap).
    """
    __tablename__ = "producer_connections"

    id = Column(String, primary_key=True)
    director_id = Column(String, index=True, nullable=False)
    producer_id = Column(String, index=True, nullable=False)
    project_id = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending")  # pending | accepted | declined
    created_at = Column(DateTime, default=datetime.utcnow)


class ActivityEvent(Base):
    """
    Real activity log, scoped per user. Every row here corresponds to an
    actual thing that happened (account created, project created, an agent
    finishing or failing) — nothing is a hardcoded demo string. Populated by
    services/activity_service.py, read back by GET /api/activity.
    """
    __tablename__ = "activity_events"

    id = Column(String, primary_key=True)
    user_id = Column(String, index=True, nullable=False)
    event_type = Column(String, nullable=False)  # account_created | project_created | agent_completed | agent_failed | pipeline_completed
    title = Column(String, nullable=False)
    description = Column(String, nullable=False, default="")
    project_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Follow(Base):
    """
    Real Instagram-style follow graph. A row here is written the instant
    someone clicks Follow and deleted the instant they click Unfollow —
    nothing here is a cached/derived count.

    `follower_id` is always a real User.id (you have to be logged in to
    follow anyone). `followee_type` + `followee_id` describe who's being
    followed:
      - "user":     a real account (director or producer) — followee_id is
                     a User.id. This is what powers the Directors Workplace.
      - "producer":  a row in the producer directory — followee_id is a
                     Producer.id. This covers both the seeded demo
                     producers and real producer accounts, since every
                     producer account also has a linked Producer row.
    """
    __tablename__ = "follows"

    id = Column(String, primary_key=True)
    follower_id = Column(String, index=True, nullable=False)
    followee_type = Column(String, nullable=False)  # 'user' | 'producer'
    followee_id = Column(String, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class Message(Base):
    """
    Real chat message between a director and a producer. Gated entirely on
    ProducerConnection.status == 'accepted' — enforced in routes_messages.py,
    not just hidden in the UI. A message row is written the instant someone
    sends it; there is no draft/simulated state.

    `connection_id` ties every message to the specific ProducerConnection
    that unlocked the conversation, so each director↔producer pair (per
    project, if project_id was set on connect) has its own thread.
    """
    __tablename__ = "messages"

    id = Column(String, primary_key=True)
    connection_id = Column(String, index=True, nullable=False)
    sender_id = Column(String, index=True, nullable=False)
    body = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


def init_auth_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()