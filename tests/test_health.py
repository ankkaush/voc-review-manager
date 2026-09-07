import pytest
from fastapi.testclient import TestClient


@pytest.mark.unit
def test_health_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
