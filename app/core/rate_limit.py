"""
Per-IP rate limiting for public auth endpoints — slowapi, Redis-backed.

IP-scoped only. Per-identifier throttling (e.g. one phone number getting
hammered from many IPs) is handled separately by each flow — see the
resend cooldown in app.services.otp.

Each check is a synchronous (blocking) Redis round-trip, since that's how
slowapi's storage backend works — negligible against a local/same-region
Redis.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.settings import settings


limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.redis_url,
    headers_enabled=True,  # X-RateLimit-* headers, so clients can back off proactively
)
