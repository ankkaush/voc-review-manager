"""Generates the synthetic review dataset described in ARCHITECTURE.md §7.

This is a *test fixture with known ground truth*, not demo filler: every category
(recurring negative/positive patterns, an emerging issue, a declining issue after a
simulated action, a stable negative control, multi-aspect/ambiguous/sarcastic reviews,
a multilingual subset, duplicates, and malformed records) is generated deliberately so
later phases can assert the pipeline actually discovers what was seeded.

Deterministic: fixed random seed, fixed anchor date. Re-running this script produces
byte-for-byte identical output.

Outputs (data/synthetic/):
  reviews.json           well-formed reviews for POST /reviews/batch (the main dataset)
  duplicates.json        exact + near-duplicates of entries already in reviews.json
  malformed_reviews.json deliberately invalid records, for ingestion-validation tests
  eval_labels.json       ~40 hand-labeled examples for the Phase 3 AI evaluation
  manifest.json          intended ground truth (weekly counts per seeded pattern) for
                          Phase 4/5 evaluation against real aggregation output
"""

import json
import random
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

SEED = 42
random.seed(SEED)

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "synthetic"

# Fixed anchor so output is reproducible regardless of when the script is run.
ANCHOR_END_DATE = date(2026, 8, 30)
WEEKS = 26

BUSINESS_NAME = "The Local Table"
LOCATIONS = ["Location A - Downtown", "Location B - Uptown", "Location C - Riverside"]
# Indices into LOCATIONS
LOC_A, LOC_B, LOC_C = 0, 1, 2

DISHES = ["burger", "pasta", "salmon", "risotto", "tacos", "steak", "salad", "pizza", "soup", "curry"]
STAFF_ADJ = ["friendly", "attentive", "welcoming", "polite", "helpful"]


def week_bounds(week_index: int) -> tuple[date, date]:
    """week_index 0 = oldest week, WEEKS-1 = most recent week."""
    weeks_from_end = (WEEKS - 1) - week_index
    end = ANCHOR_END_DATE - timedelta(weeks=weeks_from_end)
    start = end - timedelta(days=6)
    return start, end


def random_timestamp_in_week(week_index: int) -> str:
    start, _ = week_bounds(week_index)
    day_offset = random.randint(0, 6)
    d = start + timedelta(days=day_offset)
    t = time(hour=random.randint(11, 21), minute=random.randint(0, 59))
    return datetime.combine(d, t, tzinfo=UTC).isoformat()


_id_counter = 0


def next_id() -> str:
    global _id_counter
    _id_counter += 1
    return f"syn-{_id_counter:05d}"


def make_review(location_index: int, week_index: int, text: str, rating: int, category: str) -> dict:
    return {
        "source": "seed",
        "source_review_id": next_id(),
        "location_index": location_index,
        "text": text,
        "rating": rating,
        "submitted_at": random_timestamp_in_week(week_index),
        "_category": category,  # generator bookkeeping only; not a Review field
        "_week_index": week_index,
    }


# --- Template pools -----------------------------------------------------------------

def positive_food_text() -> str:
    dish = random.choice(DISHES)
    templates = [
        f"The {dish} was absolutely delicious, best I've had in a while.",
        f"Loved the {dish}, cooked perfectly and full of flavor.",
        f"Amazing {dish} tonight, will definitely come back for it.",
        f"The {dish} exceeded expectations, really high quality ingredients.",
        f"Fantastic {dish} — fresh, well seasoned, and beautifully plated.",
    ]
    return random.choice(templates)


def negative_wait_text() -> str:
    mins = random.choice([25, 30, 35, 40, 45, 50])
    templates = [
        f"We waited {mins} minutes just to be seated, way too long.",
        "Service was painfully slow, took forever to get our food out.",
        f"Had to wait almost {mins} minutes for our order, staff seemed overwhelmed.",
        "The wait time was ridiculous for how empty the place looked.",
        f"Sat for {mins} minutes before anyone even took our order.",
    ]
    return random.choice(templates)


def negative_clean_text() -> str:
    templates = [
        "The tables were dirty and the restroom needed serious attention.",
        "Floor was sticky and the whole place felt unclean.",
        "Silverware had visible residue on it, pretty off-putting.",
        "The dining area wasn't cleaned between customers, noticed crumbs everywhere.",
        "Restrooms were in poor condition, not what I'd expect.",
    ]
    return random.choice(templates)


def negative_price_text() -> str:
    templates = [
        "A bit pricey for the portion size, wouldn't call it good value.",
        "Expensive for what you get, prices have crept up.",
        "Menu prices feel high compared to similar places nearby.",
        "Good food but overpriced for a casual spot like this.",
    ]
    return random.choice(templates)


def mixed_text() -> str:
    dish = random.choice(DISHES)
    staff = random.choice(STAFF_ADJ)
    templates = [
        f"The {dish} was great but we waited almost 45 minutes and the staff seemed overwhelmed.",
        f"Amazing {dish}, though the wait was way too long for how quiet it was.",
        f"Food was excellent and the staff were {staff}, but it's a bit overpriced.",
        f"Really good {dish}, but the place could use a deeper clean.",
        f"Staff were {staff} and the {dish} was tasty, though service was slow overall.",
    ]
    return random.choice(templates)


def ambiguous_text() -> str:
    return random.choice(["meh", "It was fine.", "Nice place.", "ok food.", "Decent, nothing special.", "It's a restaurant."])


def sarcasm_text() -> str:
    templates = [
        "Oh great, another 45 minute wait, exactly what I love on a weeknight.",
        "Wow, so fast... after 40 minutes of standing around.",
        "Really impressed by how long they can make you wait for a burger.",
    ]
    return random.choice(templates)


def spanish_text() -> str:
    templates = [
        "La comida estuvo deliciosa pero el servicio fue muy lento.",
        "Excelente atencion y ambiente agradable, volveremos pronto.",
        "El lugar estaba sucio y tuvimos que esperar demasiado.",
        "Buena relacion calidad-precio, la pasta estuvo muy rica.",
    ]
    return random.choice(templates)


def french_text() -> str:
    templates = [
        "La nourriture etait excellente mais le service etait lent.",
        "Personnel tres sympathique et rapide, tres bonne experience.",
        "L'endroit etait sale et l'attente etait beaucoup trop longue.",
        "Un peu cher pour la portion, mais le plat etait savoureux.",
    ]
    return random.choice(templates)


def seasonal_filler_text() -> str:
    templates = [
        "Busy night but the team handled the crowd well.",
        "Great atmosphere for the holidays, enjoyed the special menu.",
        "Packed house tonight, food still came out solid.",
    ]
    return random.choice(templates)


# --- Weekly count series (the actual seeded ground truth) ---------------------------

def build_reviews() -> tuple[list[dict], dict]:
    reviews: list[dict] = []

    # Seeded emerging issue: wait-time complaints at Location B, last 4 weeks.
    wait_b_baseline_weeks = list(range(0, WEEKS - 4))
    wait_b_last4 = [5, 7, 9, 18]
    wait_b_series: dict[int, int] = {}
    for w in wait_b_baseline_weeks:
        wait_b_series[w] = random.randint(2, 4)
    for offset, count in enumerate(wait_b_last4):
        wait_b_series[WEEKS - 4 + offset] = count

    for w, count in wait_b_series.items():
        for _ in range(count):
            reviews.append(make_review(LOC_B, w, negative_wait_text(), random.randint(1, 2), "wait_time_seeded"))

    # Seeded declining issue: cleanliness at Location A, spike weeks 9-12, decline after.
    clean_a_series: dict[int, int] = {}
    for w in range(0, WEEKS):
        if 9 <= w <= 12:
            clean_a_series[w] = random.randint(9, 13)
        elif 13 <= w <= 16:
            # tapering decline after the simulated "action taken" at week 12
            clean_a_series[w] = random.randint(2, 4)
        else:
            clean_a_series[w] = random.randint(1, 2)

    for w, count in clean_a_series.items():
        for _ in range(count):
            reviews.append(make_review(LOC_A, w, negative_clean_text(), random.randint(1, 2), "cleanliness_seeded"))

    # Stable negative control: price complaints, flat across all locations/weeks.
    price_series: dict[tuple[int, int], int] = {}
    for loc in (LOC_A, LOC_B, LOC_C):
        for w in range(WEEKS):
            count = random.randint(1, 3)
            price_series[(loc, w)] = count
            for _ in range(count):
                reviews.append(make_review(loc, w, negative_price_text(), random.randint(2, 3), "price_flat"))

    # Stable recurring positive: food quality, all locations, no trend.
    food_series: dict[tuple[int, int], int] = {}
    for loc in (LOC_A, LOC_B, LOC_C):
        for w in range(WEEKS):
            count = random.randint(3, 5)
            food_series[(loc, w)] = count
            for _ in range(count):
                reviews.append(make_review(loc, w, positive_food_text(), random.randint(4, 5), "food_positive"))

    # Minor baseline wait/cleanliness noise at the non-seeded locations (realism, not a pattern).
    for loc in (LOC_A, LOC_C):
        for w in range(WEEKS):
            for _ in range(random.randint(0, 2)):
                reviews.append(make_review(loc, w, negative_wait_text(), random.randint(1, 3), "wait_time_noise"))
    for loc in (LOC_B, LOC_C):
        for w in range(WEEKS):
            for _ in range(random.randint(0, 2)):
                reviews.append(make_review(loc, w, negative_clean_text(), random.randint(1, 3), "cleanliness_noise"))

    # Multi-aspect / mixed-sentiment reviews.
    for loc in (LOC_A, LOC_B, LOC_C):
        for w in range(WEEKS):
            for _ in range(random.randint(1, 3)):
                reviews.append(make_review(loc, w, mixed_text(), 3, "mixed"))

    # Ambiguous / non-actionable / short reviews.
    for loc in (LOC_A, LOC_B, LOC_C):
        for w in range(WEEKS):
            for _ in range(random.randint(0, 2)):
                reviews.append(make_review(loc, w, ambiguous_text(), random.randint(3, 4), "ambiguous"))

    # Sarcasm / difficult-to-interpret cases.
    for loc in (LOC_A, LOC_B, LOC_C):
        for w in range(WEEKS):
            if random.random() < 0.15:
                reviews.append(make_review(loc, w, sarcasm_text(), random.randint(1, 2), "sarcasm"))

    # Multilingual subset (~5-8% of total, split Spanish/French).
    for loc in (LOC_A, LOC_B, LOC_C):
        for w in range(WEEKS):
            if random.random() < 0.12:
                reviews.append(make_review(loc, w, spanish_text(), random.randint(2, 5), "multilingual_es"))
            if random.random() < 0.10:
                reviews.append(make_review(loc, w, french_text(), random.randint(2, 5), "multilingual_fr"))

    # Seasonal/volume variation: a holiday-week bump, unrelated to any specific aspect.
    holiday_week = 16
    for loc in (LOC_A, LOC_B, LOC_C):
        for _ in range(random.randint(4, 7)):
            reviews.append(make_review(loc, holiday_week, seasonal_filler_text(), random.randint(3, 5), "seasonal"))

    manifest = {
        "seed": SEED,
        "anchor_end_date": ANCHOR_END_DATE.isoformat(),
        "weeks": WEEKS,
        "week_date_ranges": {
            str(w): [d.isoformat() for d in week_bounds(w)] for w in range(WEEKS)
        },
        "locations": LOCATIONS,
        "seeded_patterns": {
            "wait_time_location_b_weekly": wait_b_series,
            "wait_time_location_b_last_4_weeks": wait_b_last4,
            "cleanliness_location_a_weekly": clean_a_series,
            "cleanliness_spike_weeks": [9, 10, 11, 12],
            "cleanliness_simulated_action_week": 12,
            "cleanliness_decline_weeks": [13, 14, 15, 16],
            "price_negative_control_note": "flat ~1-3/week/location across all 26 weeks, must NOT be flagged as emerging",
            "food_positive_note": "stable 4-8/week/location across all 26 weeks, must surface as stable positive, never an issue",
            "holiday_week": holiday_week,
        },
        "total_reviews": len(reviews),
    }

    return reviews, manifest


def build_duplicates(reviews: list[dict]) -> list[dict]:
    """Two distinct dedup paths get two distinct fixtures (§3/§7):

    - Exact resubmission: the identical record (same source_review_id) sent again —
      exercises the primary (business_id, source, source_review_id) constraint.
    - Near-duplicate, no external id: two id-less submissions sharing the same
      text/location — exercises the secondary content-hash constraint, which only
      applies when no source_review_id is present (a review WITH an id is never
      content-hash-deduped against other wording, see `_find_duplicate`).
    """
    sample = random.sample(reviews, k=20)
    duplicates = []

    # Exact resubmissions (15): same source_review_id, same everything.
    for original in sample[:15]:
        duplicates.append({k: v for k, v in original.items() if not k.startswith("_")})

    # Near-duplicates (5 pairs = 10 records): identical text/location, no source_review_id
    # on either copy, submitted twice — the second must be caught as a duplicate.
    for original in sample[15:]:
        base = {k: v for k, v in original.items() if not k.startswith("_") and k != "source_review_id"}
        duplicates.append(dict(base))
        duplicates.append(dict(base))

    return duplicates


def build_malformed() -> list[dict]:
    """Deliberately invalid records — never expected to produce a Review row (§8)."""
    return [
        {"location_index": LOC_A, "rating": 4, "submitted_at": random_timestamp_in_week(20)},  # missing text
        {"location_index": LOC_A, "text": "", "rating": 3, "submitted_at": random_timestamp_in_week(20)},  # empty text
        {"location_index": LOC_A, "text": "Fine.", "rating": 0, "submitted_at": random_timestamp_in_week(20)},  # rating too low
        {"location_index": LOC_A, "text": "Great!", "rating": 7, "submitted_at": random_timestamp_in_week(20)},  # rating too high
        {"location_index": LOC_A, "text": "Good food."},  # missing submitted_at
        {"location_index": 99, "text": "Unknown location.", "rating": 3, "submitted_at": random_timestamp_in_week(20)},
        {"location_index": LOC_B, "text": "x" * 6000, "rating": 3, "submitted_at": random_timestamp_in_week(20)},  # too long
        {"location_index": LOC_B, "text": "Not sure what happened here.", "rating": "five", "submitted_at": random_timestamp_in_week(20)},  # wrong type
    ]


# Per-template sentiment overrides: some templates within a category don't share the
# category's default sentiment (e.g. most multilingual templates are purely positive or
# negative, not "mixed" — a blanket per-category label was a labeling bug, not a
# reflection of the actual template text; caught by comparing eval results against a
# real Claude run and finding the "errors" were mislabeled ground truth, not model
# mistakes). Keyed by exact template text.
TEMPLATE_SENTIMENT_OVERRIDES: dict[str, str] = {
    "Excelente atencion y ambiente agradable, volveremos pronto.": "positive",
    "El lugar estaba sucio y tuvimos que esperar demasiado.": "negative",
    "Buena relacion calidad-precio, la pasta estuvo muy rica.": "positive",
    "Personnel tres sympathique et rapide, tres bonne experience.": "positive",
    "L'endroit etait sale et l'attente etait beaucoup trop longue.": "negative",
    "Un peu cher pour la portion, mais le plat etait savoureux.": "mixed",
    "Good food but overpriced for a casual spot like this.": "mixed",
}


def _resolve_aspects_for_text(category: str, text: str, default: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """`mixed` and `seasonal` each cover several templates with genuinely different
    negative/positive aspects (e.g. one `mixed` template complains about cleanliness,
    not wait time) — a single per-category aspect tuple was wrong for those, same root
    cause as TEMPLATE_SENTIMENT_OVERRIDES above. Resolved by content, not category.
    """
    if category == "mixed":
        if "overpriced" in text:
            return [("food_quality", "positive"), ("price_value", "negative")]
        if "deeper clean" in text:
            return [("food_quality", "positive"), ("cleanliness_general", "negative")]
        return [("food_quality", "positive"), ("wait_time", "negative")]

    if category == "seasonal":
        if "atmosphere" in text.lower():
            return [("atmosphere", "positive")]
        if "crowd" in text:
            return [("staff_attentiveness", "positive")]
        if "food" in text.lower():
            return [("food_quality", "positive")]
        return default

    return default


def build_eval_labels(reviews: list[dict]) -> list[dict]:
    """~40 hand-selected examples with ground-truth labels for the Phase 3 AI evaluation.

    Labels are derived from the template category each review was generated from — the
    generator authored these reviews to have deterministic characteristics, so this is a
    legitimate ground truth, not a guess — except where TEMPLATE_SENTIMENT_OVERRIDES
    corrects a specific template that doesn't match its category's default sentiment.
    """
    label_map = {
        "wait_time_seeded": ("negative", ["service"], [("wait_time", "negative")], "medium"),
        "wait_time_noise": ("negative", ["service"], [("wait_time", "negative")], "low"),
        "cleanliness_seeded": ("negative", ["cleanliness"], [("cleanliness_general", "negative")], "medium"),
        "cleanliness_noise": ("negative", ["cleanliness"], [("cleanliness_general", "negative")], "low"),
        "price_flat": ("negative", ["price"], [("price_value", "negative")], "low"),
        "food_positive": ("positive", ["food"], [("food_quality", "positive")], None),
        "mixed": ("mixed", ["food", "service"], [("food_quality", "positive"), ("wait_time", "negative")], "low"),
        "ambiguous": ("neutral", [], [], None),
        "sarcasm": ("negative", ["service"], [("wait_time", "negative")], "low"),
        "multilingual_es": ("mixed", ["food", "service"], [], None),
        "multilingual_fr": ("mixed", ["food", "service"], [], None),
        "seasonal": ("positive", ["ambiance"], [("atmosphere", "positive")], None),
    }

    by_category: dict[str, list[dict]] = {}
    for r in reviews:
        by_category.setdefault(r["_category"], []).append(r)

    labels = []
    per_category_target = 4
    for category, (sentiment, topics, aspects, severity) in label_map.items():
        candidates = by_category.get(category, [])
        if not candidates:
            continue
        picks = random.sample(candidates, k=min(per_category_target, len(candidates)))
        for review in picks:
            resolved_sentiment = TEMPLATE_SENTIMENT_OVERRIDES.get(review["text"], sentiment)
            resolved_aspects = _resolve_aspects_for_text(category, review["text"], aspects)
            labels.append(
                {
                    "source_review_id": review["source_review_id"],
                    "text": review["text"],
                    "location_index": review["location_index"],
                    "expected_overall_sentiment": resolved_sentiment,
                    "expected_topics": topics,
                    "expected_aspects": [{"aspect": a, "sentiment": s} for a, s in resolved_aspects],
                    "expected_severity": severity,
                    "expected_language": "es" if category == "multilingual_es" else (
                        "fr" if category == "multilingual_fr" else "en"
                    ),
                    "category": category,
                }
            )

    return labels


def strip_generator_fields(reviews: list[dict]) -> list[dict]:
    return [{k: v for k, v in r.items() if not k.startswith("_")} for r in reviews]


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    reviews, manifest = build_reviews()
    duplicates = build_duplicates(reviews)
    malformed = build_malformed()
    eval_labels = build_eval_labels(reviews)

    manifest["duplicates_count"] = len(duplicates)
    manifest["malformed_count"] = len(malformed)
    manifest["eval_labels_count"] = len(eval_labels)
    manifest["business_name"] = BUSINESS_NAME
    manifest["locations"] = LOCATIONS

    (OUTPUT_DIR / "reviews.json").write_text(json.dumps(strip_generator_fields(reviews), indent=2))
    (OUTPUT_DIR / "duplicates.json").write_text(json.dumps(duplicates, indent=2))
    (OUTPUT_DIR / "malformed_reviews.json").write_text(json.dumps(malformed, indent=2))
    (OUTPUT_DIR / "eval_labels.json").write_text(json.dumps(eval_labels, indent=2))
    (OUTPUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))

    print(f"Generated {len(reviews)} reviews, {len(duplicates)} duplicates, "
          f"{len(malformed)} malformed, {len(eval_labels)} eval labels.")
    print(f"Written to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
