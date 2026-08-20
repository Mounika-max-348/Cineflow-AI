"""
Central configuration for CineFlow AI backend.

All secrets/credentials come from environment variables ONLY.
Never hardcode API keys, passwords, or connection strings here.
See .env.example for the full list of variables this app reads.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Gemini / Vertex AI ---
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash"

    # --- Google Cloud (optional, used when deployed via Vertex AI instead of API key) ---
    GOOGLE_CLOUD_PROJECT: str = ""
    GOOGLE_CLOUD_LOCATION: str = "us-central1"
    USE_VERTEX_AI: bool = False

    # --- ClickHouse ---
    CLICKHOUSE_HOST: str = "localhost"
    CLICKHOUSE_PORT: int = 8443
    CLICKHOUSE_USER: str = "default"
    CLICKHOUSE_PASSWORD: str = ""
    CLICKHOUSE_DATABASE: str = "cineflow"
    CLICKHOUSE_SECURE: bool = True

    # --- App ---
    ENVIRONMENT: str = "development"
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"
    LOG_LEVEL: str = "INFO"

    # --- Auth ---
    AUTH_DATABASE_URL: str = "sqlite:///./cineflow_auth.db"
    JWT_SECRET_KEY: str = "dev-only-change-me-before-any-real-deployment"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    @property
    def gemini_configured(self) -> bool:
        return bool(self.GEMINI_API_KEY) or (self.USE_VERTEX_AI and bool(self.GOOGLE_CLOUD_PROJECT))

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
