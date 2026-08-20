import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    routes_activity,
    routes_analytics,
    routes_auth,
    routes_dashboard,
    routes_directors,
    routes_messages,
    routes_producers,
    routes_projects,
    routes_social,
)
from app.config import get_settings
from app.db.auth_db import init_auth_db

settings = get_settings()
logging.basicConfig(level=settings.LOG_LEVEL)

app = FastAPI(
    title="CineFlow AI API",
    description="Autonomous film-production planning backend — Gemini Coordinator, "
                 "specialized agents, and ClickHouse analytics.",
    version="0.1.0",
)


@app.on_event("startup")
def on_startup():
    init_auth_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_auth.router)
app.include_router(routes_projects.router)
app.include_router(routes_dashboard.router)
app.include_router(routes_activity.router)
app.include_router(routes_producers.router)
app.include_router(routes_messages.router)
app.include_router(routes_directors.router)
app.include_router(routes_social.router)
app.include_router(routes_analytics.router)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "gemini_configured": settings.gemini_configured,
        "environment": settings.ENVIRONMENT,
    }