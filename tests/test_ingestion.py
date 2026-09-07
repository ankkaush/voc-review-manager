import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.business import Business
from app.models.location import Location

settings = get_settings()


@pytest.fixture()
def auth_headers(client: TestClient) -> dict:
    response = client.post(
        "/auth/login", json={"email": settings.admin_email, "password": settings.admin_password}
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def business_and_location(db_session: Session) -> tuple[Business, Location]:
    business = Business(name=f"Test Business {uuid.uuid4()}", industry="restaurant")
    db_session.add(business)
    db_session.flush()
    location = Location(business_id=business.id, name="Downtown", city="Springfield")
    db_session.add(location)
    db_session.commit()
    db_session.refresh(business)
    db_session.refresh(location)
    return business, location


def _review_payload(business: Business, location: Location, **overrides) -> dict:
    payload = {
        "business_id": str(business.id),
        "location_id": str(location.id),
        "source": "seed",
        "source_review_id": f"r-{uuid.uuid4()}",
        "rating": 4,
        "text": "The food was great but the wait was too long.",
        "submitted_at": datetime.now(UTC).isoformat(),
    }
    payload.update(overrides)
    return payload


@pytest.mark.integration
def test_create_review_accepted(client: TestClient, auth_headers: dict, business_and_location) -> None:
    business, location = business_and_location
    response = client.post("/reviews", json=_review_payload(business, location), headers=auth_headers)

    assert response.status_code == 201
    body = response.json()
    assert body["ingestion_status"] == "accepted"
    assert body["analysis_status"] == "pending"
    assert body["detected_language"] == "en"


@pytest.mark.integration
def test_create_review_requires_auth(client: TestClient, business_and_location) -> None:
    business, location = business_and_location
    response = client.post("/reviews", json=_review_payload(business, location))
    assert response.status_code == 401


@pytest.mark.integration
def test_create_review_duplicate_source_id_rejected(
    client: TestClient, auth_headers: dict, business_and_location
) -> None:
    business, location = business_and_location
    payload = _review_payload(business, location)

    first = client.post("/reviews", json=payload, headers=auth_headers)
    assert first.status_code == 201

    second = client.post("/reviews", json=payload, headers=auth_headers)
    assert second.status_code == 409


@pytest.mark.unit
def test_create_review_invalid_rating_is_422(
    client: TestClient, auth_headers: dict, business_and_location
) -> None:
    business, location = business_and_location
    response = client.post(
        "/reviews", json=_review_payload(business, location, rating=99), headers=auth_headers
    )
    assert response.status_code == 422


@pytest.mark.integration
def test_batch_ingest_isolates_failures_and_is_idempotent(
    client: TestClient, auth_headers: dict, business_and_location
) -> None:
    business, location = business_and_location

    good_1 = _review_payload(business, location, text="Loved the food, but service was slow.")
    good_2 = _review_payload(business, location, text="Staff was rude and the place was dirty.")
    malformed_missing_text = {
        "business_id": str(business.id),
        "location_id": str(location.id),
        "submitted_at": datetime.now(UTC).isoformat(),
    }
    malformed_bad_rating = _review_payload(business, location, rating=0)
    unknown_location = _review_payload(business, location, location_id=str(uuid.uuid4()))

    batch = [good_1, good_2, malformed_missing_text, malformed_bad_rating, unknown_location]

    response = client.post("/reviews/batch", json=batch, headers=auth_headers)
    assert response.status_code == 200
    body = response.json()

    assert body["total"] == 5
    assert body["accepted"] == 2
    assert body["rejected"] == 3
    assert body["duplicate"] == 0
    assert len(body["results"]) == 5

    # Re-submitting the exact same batch must not create new rows for the two
    # already-accepted reviews (§8: idempotent processing).
    second_response = client.post("/reviews/batch", json=batch, headers=auth_headers)
    second_body = second_response.json()
    assert second_body["accepted"] == 0
    assert second_body["duplicate"] == 2
    assert second_body["rejected"] == 3


@pytest.mark.integration
def test_list_reviews_filters_by_business(
    client: TestClient, auth_headers: dict, business_and_location
) -> None:
    business, location = business_and_location
    client.post("/reviews", json=_review_payload(business, location), headers=auth_headers)

    response = client.get(f"/reviews?business_id={business.id}", headers=auth_headers)
    assert response.status_code == 200
    reviews = response.json()
    assert len(reviews) == 1
    assert reviews[0]["business_id"] == str(business.id)
