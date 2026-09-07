from collections.abc import Iterator
from urllib.parse import urlsplit, urlunsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models import Base
from app.taxonomy_seed import seed_taxonomy

settings = get_settings()


def _test_database_url(base_url: str) -> str:
    """Always run tests against a separate `<db>_test` database, never the configured
    dev/deployment database — this suite creates and drops tables, and must not be able
    to touch data a developer is looking at in docker-compose or a real deployment.
    """
    parts = urlsplit(base_url)
    test_path = f"{parts.path}_test"
    return urlunsplit((parts.scheme, parts.netloc, test_path, parts.query, parts.fragment))


def _ensure_test_database_exists(base_url: str, test_db_name: str) -> None:
    admin_parts = urlsplit(base_url)
    admin_url = urlunsplit((admin_parts.scheme, admin_parts.netloc, "/postgres", "", ""))
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": test_db_name}
            ).scalar_one_or_none()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{test_db_name}"'))
    finally:
        admin_engine.dispose()


test_database_url = _test_database_url(settings.database_url)
_ensure_test_database_exists(settings.database_url, urlsplit(test_database_url).path.lstrip("/"))

engine = create_engine(test_database_url, future=True)
TestSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture(scope="session", autouse=True)
def _create_schema() -> Iterator[None]:
    Base.metadata.create_all(bind=engine)
    # Static reference data (§3) — normally seeded by the app's startup lifespan, but
    # tests that exercise services directly (not through `client`/TestClient) never
    # trigger that lifespan, so it's seeded once here instead.
    with TestSessionLocal(bind=engine) as seed_session:
        seed_taxonomy(seed_session)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db_session() -> Iterator[Session]:
    connection = engine.connect()
    transaction = connection.begin()
    session = TestSessionLocal(bind=connection)

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture()
def client(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    def _get_db_override() -> Iterator[Session]:
        yield db_session

    # The app's startup lifespan seeds the admin user via its own SessionLocal
    # (app.database, pointed at the configured dev/deployment database). Redirect it to
    # the test engine too, so admin-seeding never touches a non-test database.
    monkeypatch.setattr("app.main.SessionLocal", TestSessionLocal)

    app.dependency_overrides[get_db] = _get_db_override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
