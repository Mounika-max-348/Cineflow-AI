"""
Run once to create the ClickHouse database + all tables.

Usage:
    cd backend
    python scripts/init_clickhouse.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import clickhouse_connect  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.services.clickhouse_service import ClickHouseService  # noqa: E402

if __name__ == "__main__":
    settings = get_settings()
    print(f"Connecting to ClickHouse at {settings.CLICKHOUSE_HOST}:{settings.CLICKHOUSE_PORT} ...")

    # Bootstrap connection: target database doesn't exist yet, so connect to
    # the always-present "default" database first, just to run CREATE DATABASE.
    bootstrap_client = clickhouse_connect.get_client(
        host=settings.CLICKHOUSE_HOST,
        port=settings.CLICKHOUSE_PORT,
        username=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database="default",
        secure=settings.CLICKHOUSE_SECURE,
    )
    bootstrap_client.command(f"CREATE DATABASE IF NOT EXISTS {settings.CLICKHOUSE_DATABASE}")
    print(f"Database '{settings.CLICKHOUSE_DATABASE}' ready.")

    # Now that it exists, reconnect scoped to it and apply the real schema.
    ch = ClickHouseService()
    schema_path = os.path.join(os.path.dirname(__file__), "..", "app", "db", "schema.sql")
    ch.run_migrations(schema_path)
    print("\u2705 ClickHouse schema applied.")