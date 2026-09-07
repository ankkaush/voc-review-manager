"""Seeds Business/Locations (idempotent) and ingests the synthetic dataset through the
*real* ingestion service (app.ingestion.service.ingest_batch) — not a bypass of the
API's validation/dedup logic, so this script doubles as a live demonstration that the
pipeline works end-to-end.

Usage:
    python scripts/load_synthetic_dataset.py                 # loads reviews.json
    python scripts/load_synthetic_dataset.py --duplicates     # also loads duplicates.json
    python scripts/load_synthetic_dataset.py --malformed      # also loads malformed_reviews.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.ingestion.service import ingest_batch  # noqa: E402
from app.models.business import Business  # noqa: E402
from app.models.location import Location  # noqa: E402
from app.models.processing_run import ProcessingRunTrigger  # noqa: E402
from scripts.generate_synthetic_dataset import BUSINESS_NAME, LOCATIONS  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "synthetic"


def seed_business_and_locations(db) -> tuple[Business, list[Location]]:
    business = db.execute(select(Business).where(Business.name == BUSINESS_NAME)).scalar_one_or_none()
    if business is None:
        business = Business(name=BUSINESS_NAME, industry="restaurant")
        db.add(business)
        db.flush()

    locations = []
    for name in LOCATIONS:
        location = db.execute(
            select(Location).where(Location.business_id == business.id, Location.name == name)
        ).scalar_one_or_none()
        if location is None:
            location = Location(business_id=business.id, name=name, city="Springfield")
            db.add(location)
            db.flush()
        locations.append(location)

    db.commit()
    return business, locations


def resolve_location_ids(raw_items: list[dict], business: Business, locations: list[Location]) -> list[dict]:
    resolved = []
    for item in raw_items:
        payload = dict(item)
        location_index = payload.pop("location_index", None)
        payload["business_id"] = str(business.id)
        if location_index is not None and 0 <= location_index < len(locations):
            payload["location_id"] = str(locations[location_index].id)
        else:
            # Deliberately-invalid malformed-record case: no valid mapping available.
            payload["location_id"] = payload.get("location_id", "00000000-0000-0000-0000-000000000000")
        resolved.append(payload)
    return resolved


def load_file(db, business: Business, locations: list[Location], filename: str) -> None:
    path = DATA_DIR / filename
    if not path.exists():
        print(f"Skipping {filename} (not found — run generate_synthetic_dataset.py first)")
        return

    raw_items = json.loads(path.read_text())
    resolved = resolve_location_ids(raw_items, business, locations)

    result = ingest_batch(db, resolved, trigger=ProcessingRunTrigger.MANUAL)
    print(
        f"{filename}: total={result.total} accepted={result.accepted} "
        f"duplicate={result.duplicate} rejected={result.rejected} "
        f"(processing_run_id={result.processing_run_id})"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duplicates", action="store_true", help="also load duplicates.json")
    parser.add_argument("--malformed", action="store_true", help="also load malformed_reviews.json")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        business, locations = seed_business_and_locations(db)
        print(f"Business: {business.name} ({business.id})")
        for loc in locations:
            print(f"  Location: {loc.name} ({loc.id})")

        load_file(db, business, locations, "reviews.json")
        if args.duplicates:
            load_file(db, business, locations, "duplicates.json")
        if args.malformed:
            load_file(db, business, locations, "malformed_reviews.json")
    finally:
        db.close()


if __name__ == "__main__":
    main()
