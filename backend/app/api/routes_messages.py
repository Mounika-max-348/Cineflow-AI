"""
Director ↔ Producer messaging.

Hard rule, enforced server-side (not just hidden in the UI): you can only
send or read messages on a ProducerConnection whose status is 'accepted',
and only if you're one of the two real parties on that connection (the
director who sent the request, or the user account linked to the producer
who accepted it). A pending or declined connection has no message thread.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.routes_auth import get_current_user
from app.db.auth_db import Message, Producer, ProducerConnection, User, get_db
from app.services.activity_service import log_activity

router = APIRouter(prefix="/api/messages", tags=["messages"])


class MessageCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)


def _authorize_connection(db: Session, connection_id: str, current_user: User) -> ProducerConnection:
    """Raises 404/403/409 if this user has no business reading/writing this
    thread. Returns the connection row if they do."""
    connection = db.query(ProducerConnection).filter(ProducerConnection.id == connection_id).first()
    if connection is None:
        raise HTTPException(status_code=404, detail="Connection not found.")

    if connection.status != "accepted":
        raise HTTPException(
            status_code=409,
            detail="Messaging is only available once this connection has been accepted.",
        )

    is_director = connection.director_id == current_user.id
    my_producer_profile = db.query(Producer).filter(Producer.user_id == current_user.id).first()
    is_producer_side = my_producer_profile is not None and connection.producer_id == my_producer_profile.id

    if not (is_director or is_producer_side):
        raise HTTPException(status_code=403, detail="You're not part of this conversation.")

    return connection


@router.get("/threads")
def my_threads(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Every accepted connection this user is part of, each treated as one
    conversation thread — with the other party's name and a last-message
    preview so the frontend can render an inbox list."""
    my_producer_profile = db.query(Producer).filter(Producer.user_id == current_user.id).first()

    query = db.query(ProducerConnection).filter(ProducerConnection.status == "accepted")
    if my_producer_profile is not None:
        query = query.filter(
            (ProducerConnection.director_id == current_user.id)
            | (ProducerConnection.producer_id == my_producer_profile.id)
        )
    else:
        query = query.filter(ProducerConnection.director_id == current_user.id)

    connections = query.order_by(ProducerConnection.created_at.desc()).all()

    threads = []
    for c in connections:
        if current_user.id == c.director_id:
            other_producer = db.query(Producer).filter(Producer.id == c.producer_id).first()
            other_name = other_producer.name if other_producer else "Unknown"
        else:
            director = db.query(User).filter(User.id == c.director_id).first()
            other_name = director.full_name if director else "Unknown"

        last_message = (
            db.query(Message)
            .filter(Message.connection_id == c.id)
            .order_by(Message.created_at.desc())
            .first()
        )
        threads.append({
            "connection_id": c.id,
            "other_party_name": other_name,
            "project_id": c.project_id,
            "last_message": last_message.body if last_message else None,
            "last_message_at": last_message.created_at.isoformat() if last_message else None,
        })

    return {"threads": threads}


@router.get("/{connection_id}")
def get_thread(
    connection_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _authorize_connection(db, connection_id, current_user)
    messages = (
        db.query(Message)
        .filter(Message.connection_id == connection_id)
        .order_by(Message.created_at.asc())
        .all()
    )
    return {
        "messages": [
            {
                "id": m.id,
                "sender_id": m.sender_id,
                "is_mine": m.sender_id == current_user.id,
                "body": m.body,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ]
    }


@router.post("/{connection_id}")
def send_message(
    connection_id: str,
    payload: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    connection = _authorize_connection(db, connection_id, current_user)

    message = Message(
        id=str(uuid.uuid4()),
        connection_id=connection_id,
        sender_id=current_user.id,
        body=payload.body,
    )
    db.add(message)
    db.commit()

    # Notify the other party via the real activity feed.
    recipient_id = (
        connection.director_id
        if current_user.id != connection.director_id
        else None
    )
    if recipient_id is None:
        # sender was the director -> notify the producer's linked account, if any
        producer = db.query(Producer).filter(Producer.id == connection.producer_id).first()
        recipient_id = producer.user_id if producer else None

    if recipient_id:
        log_activity(
            db,
            user_id=recipient_id,
            event_type="message_received",
            title=f"New message from {current_user.full_name}",
            description=payload.body[:120],
            project_id=connection.project_id,
        )

    return {
        "id": message.id,
        "connection_id": connection_id,
        "sender_id": current_user.id,
        "body": message.body,
        "created_at": message.created_at.isoformat(),
    }