"""Shared retry/backoff policy for transient external-call failures (§8 reliability model).

Used by the `analysis` module (Phase 3+) around LLM calls, and available to any future
module making an outbound call that can fail transiently. Permanent failures (e.g. a
validation error after the retry budget is exhausted) are the caller's responsibility to
handle as a dead-letter, not retried further here.
"""

from collections.abc import Callable
from typing import TypeVar

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

T = TypeVar("T")


class TransientError(Exception):
    """Raised for failures that are safe to retry (timeouts, 5xx, rate limits)."""


def with_transient_retry(func: Callable[..., T]) -> Callable[..., T]:
    """Decorator: retry up to 3 attempts with exponential backoff (1s, 2s, 4s) on TransientError."""
    return retry(
        retry=retry_if_exception_type(TransientError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )(func)
