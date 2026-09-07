from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, sourced entirely from environment variables.

    No secret ever has a real default here — see .env.example for the full list
    of variables a deployment must set.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://voc:voc@localhost:5432/voc"

    jwt_secret: str = "change-me-in-env"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60 * 12

    admin_email: str = "admin@example.com"
    admin_password: str = "change-me-in-env"

    sentry_dsn: str | None = None

    anthropic_api_key: str | None = None
    # Haiku-class: sentiment/topic/aspect extraction is high-volume, well-defined
    # classification — not the kind of task that needs a larger model (§C tooling notes).
    analysis_model: str = "claude-haiku-4-5-20251001"
    analysis_timeout_seconds: float = 30.0

    cors_allowed_origins: str = "http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
