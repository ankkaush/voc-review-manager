"""Router-level test for the /actions business_id filter added for the Phase 9
dashboard (the Actions page needs "every action for this business", which nothing
exposed before)."""


import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.action import Action, ActionType
from app.models.issue import Issue, IssueStatus
from tests.factories import create_business_and_location

settings = get_settings()


@pytest.fixture()
def auth_headers(client: TestClient) -> dict:
    response = client.post(
        "/auth/login", json={"email": settings.admin_email, "password": settings.admin_password}
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
def test_list_actions_filters_by_business_id(
    client: TestClient, db_session: Session, auth_headers: dict
) -> None:
    business_a, location_a = create_business_and_location(db_session, "A")
    business_b, location_b = create_business_and_location(db_session, "B")

    from sqlalchemy import select

    from app.models.taxonomy import Aspect, Topic

    topic = db_session.execute(select(Topic).where(Topic.key == "service")).scalar_one()
    aspect = db_session.execute(
        select(Aspect).where(Aspect.topic_id == topic.id, Aspect.key == "wait_time")
    ).scalar_one()

    issue_a = Issue(
        business_id=business_a.id, location_id=location_a.id, topic_id=topic.id, aspect_id=aspect.id,
        title="A", description="A", status=IssueStatus.RECOMMENDED,
    )
    issue_b = Issue(
        business_id=business_b.id, location_id=location_b.id, topic_id=topic.id, aspect_id=aspect.id,
        title="B", description="B", status=IssueStatus.RECOMMENDED,
    )
    db_session.add_all([issue_a, issue_b])
    db_session.commit()

    action_a = Action(
        issue_id=issue_a.id, type=ActionType.OPERATIONAL_TASK,
        recommended_text="x", status=IssueStatus.RECOMMENDED,
    )
    action_b = Action(
        issue_id=issue_b.id, type=ActionType.OPERATIONAL_TASK,
        recommended_text="y", status=IssueStatus.RECOMMENDED,
    )
    db_session.add_all([action_a, action_b])
    db_session.commit()

    response = client.get(f"/actions?business_id={business_a.id}", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["issue_id"] == str(issue_a.id)
