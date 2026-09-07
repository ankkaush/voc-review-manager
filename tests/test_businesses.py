import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.factories import create_business_and_location


@pytest.fixture()
def auth_headers(client: TestClient) -> dict:
    from app.config import get_settings

    settings = get_settings()
    response = client.post(
        "/auth/login", json={"email": settings.admin_email, "password": settings.admin_password}
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
def test_list_businesses_requires_auth(client: TestClient) -> None:
    response = client.get("/businesses")
    assert response.status_code == 401


@pytest.mark.integration
def test_list_businesses_and_locations(client: TestClient, db_session: Session, auth_headers: dict) -> None:
    business, location = create_business_and_location(db_session)

    businesses = client.get("/businesses", headers=auth_headers).json()
    assert any(b["id"] == str(business.id) for b in businesses)

    locations = client.get(f"/businesses/{business.id}/locations", headers=auth_headers).json()
    assert len(locations) == 1
    assert locations[0]["id"] == str(location.id)
