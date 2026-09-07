"""Deterministic language detection (ADR-2 / Open Question 2, resolved).

Language ID is a solved, near-zero-cost classification problem — handled by a
library, never an LLM call, so AI budget stays on genuinely interpretive work
(sentiment/topic/aspect/severity in Phase 3).
"""

import logging

from langdetect import DetectorFactory, LangDetectException, detect

# langdetect's algorithm is otherwise non-deterministic on short/ambiguous text.
DetectorFactory.seed = 0

logger = logging.getLogger(__name__)


def detect_language(text: str) -> str | None:
    """Returns an ISO 639-1 code, or None if detection isn't possible (e.g. text too
    short/ambiguous). None is a valid, expected outcome — not an error.
    """
    stripped = text.strip()
    if not stripped:
        return None

    try:
        return detect(stripped)
    except LangDetectException:
        return None
