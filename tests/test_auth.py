import pytest
from fastapi.testclient import TestClient

from app.config import get_settings

settings = get_settings()


@pytest.mark.integration
def test_login_with_seeded_admin_returns_token(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        json={"email": settings.admin_email, "password": settings.admin_password},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


@pytest.mark.integration
def test_login_with_wrong_password_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        json={"email": settings.admin_email, "password": "definitely-wrong"},
    )
    assert response.status_code == 401


@pytest.mark.integration
def test_system_health_requires_auth(client: TestClient) -> None:
    response = client.get("/system-health/runs")
    assert response.status_code == 401


@pytest.mark.integration
def test_system_health_accessible_with_valid_token(client: TestClient) -> None:
    login_response = client.post(
        "/auth/login",
        json={"email": settings.admin_email, "password": settings.admin_password},
    )
    token = login_response.json()["access_token"]

    response = client.get("/system-health/runs", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == []
