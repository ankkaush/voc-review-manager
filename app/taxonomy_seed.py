"""Seeds the static topic/aspect taxonomy if empty (§3, §5 mentor point E).

Taxonomy-based classification is the locked v1 approach for issue detection (ADR-1) —
this fixed vocabulary is what makes deterministic aggregation in Phase 4 possible at all.
Not user-editable in v1; changing categories means editing this list and re-seeding.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.taxonomy import Aspect, Topic

logger = logging.getLogger(__name__)

# topic_key -> (topic_label, [(aspect_key, aspect_label), ...])
TAXONOMY: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "food": ("Food", [("food_quality", "Food Quality"), ("menu_variety", "Menu Variety")]),
    "service": ("Service", [("wait_time", "Wait Time"), ("order_accuracy", "Order Accuracy")]),
    "staff": (
        "Staff",
        [("staff_friendliness", "Staff Friendliness"), ("staff_attentiveness", "Staff Attentiveness")],
    ),
    "price": ("Price", [("price_value", "Price / Value")]),
    "cleanliness": ("Cleanliness", [("cleanliness_general", "General Cleanliness")]),
    "delivery": ("Delivery", [("delivery_experience", "Delivery Experience")]),
    "ambiance": ("Ambiance", [("atmosphere", "Atmosphere")]),
}


def seed_taxonomy(db: Session) -> None:
    if db.execute(select(Topic.id)).first() is not None:
        return

    for topic_key, (topic_label, aspects) in TAXONOMY.items():
        topic = Topic(key=topic_key, label=topic_label)
        db.add(topic)
        db.flush()  # assigns topic.id for the FK below

        for aspect_key, aspect_label in aspects:
            db.add(Aspect(topic_id=topic.id, key=aspect_key, label=aspect_label))

    db.commit()
    logger.info("Seeded taxonomy", extra={"context": {"topics": len(TAXONOMY)}})
