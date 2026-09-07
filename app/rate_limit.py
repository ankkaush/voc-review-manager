from slowapi import Limiter
from slowapi.util import get_remote_address

# Shared limiter instance: proportionate, in-memory rate limiting (§H) — no Redis-backed
# distributed limiter, which this project's scale doesn't need.
limiter = Limiter(key_func=get_remote_address)
