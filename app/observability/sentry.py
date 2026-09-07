import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

from app.config import Settings


def init_sentry(settings: Settings) -> None:
    """No-op if SENTRY_DSN isn't configured (e.g. local dev) — never required to run the app."""
    if not settings.sentry_dsn:
        return

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.env,
        integrations=[FastApiIntegration()],
        traces_sample_rate=0.1,
    )
