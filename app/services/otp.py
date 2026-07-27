"""
OTP service — generates, stores, sends, and verifies login/signup codes.
The only place login/signup OTP state lives before it's either consumed
(signup/login succeeds) or expires unused.

One code per phone number, not split by signup/login purpose: the two
can't collide, because request_otp's callers (app/services/auth.py) only
ever request a signup code for an unregistered phone and a login code for
a registered one — the phone's registration status already keeps them
mutually exclusive, so there's nothing extra to namespace against.

Nothing here is a system of record: every Redis key carries a TTL
(settings.otp_expire_seconds) and is safe to lose. For signup specifically,
the pending business_name/first_name/last_name travel alongside the code
hash under the same key, so POST /auth/otp/verify only needs
{phone_number, code} — no second round-trip to re-collect the form data.

Codes are sent over WhatsApp using Retail OS's own platform phone number
(settings.whatsapp_otp_sender_phone_number_id) — a distributor has no WABA
of their own until after they sign up, so the code can't go out from a
tenant-owned number the way ordinary business messaging does.

Key layout:
  otp:{phone_number}          — code hash, attempts, pending signup data
  otp:cooldown:{phone_number} — presence-only marker for resend throttling;
                                 value is unused
"""

import json
import logging
from dataclasses import asdict, dataclass

from app.clients.redis import RedisClient
from app.clients.whatsapp import send_text_message
from app.core.exceptions import RateLimitedError, UnprocessableError
from app.core.security import generate_numeric_code, hash_otp_code, verify_otp_code
from app.core.settings import settings


logger = logging.getLogger(__name__)


@dataclass
class PendingSignup:
    business_name: str
    first_name: str
    last_name: str


@dataclass
class _OTPRecord:
    code_hash: str
    attempts: int
    pending: dict[str, str] | None  # PendingSignup.__dict__, or None for login


def _otp_key(phone_number: str) -> str:
    return f"otp:{phone_number}"


def _cooldown_key(phone_number: str) -> str:
    return f"otp:cooldown:{phone_number}"


async def request_otp(
    redis: RedisClient,
    *,
    phone_number: str,
    pending: PendingSignup | None = None,
) -> None:
    """
    Generate a code, send it to the user over WhatsApp, then store its hash
    (+ any pending signup data) in Redis. Sending first means a delivery
    failure persists nothing, so the user isn't throttled without a code.

    Raises RateLimitedError if called again before the resend cooldown
    (settings.otp_resend_cooldown_seconds) elapses for this phone number.
    """
    if await redis.exists(_cooldown_key(phone_number)):
        raise RateLimitedError(
            "A code was already sent. Please wait before requesting another."
        )

    code = generate_numeric_code(settings.otp_length)
    record = _OTPRecord(
        code_hash=hash_otp_code(code),
        attempts=0,
        pending=asdict(pending) if pending is not None else None,
    )

    # Send first: if WhatsApp delivery fails this raises before anything is
    # persisted, so the user isn't throttled with no code and can retry.
    # phone_number is our stored/display E.164 format (leading '+'); the
    # Cloud API `to` field wants it without the '+'.
    minutes = settings.otp_expire_seconds // 60
    await send_text_message(
        phone_number_id=settings.whatsapp_otp_sender_phone_number_id,
        to=phone_number.lstrip("+"),
        body=f"Your Retail OS verification code is {code}. It expires in "
        f"{minutes} minute{'s' if minutes != 1 else ''}.",
    )

    await redis.set(
        _otp_key(phone_number),
        json.dumps(asdict(record)),
        ex=settings.otp_expire_seconds,
    )
    await redis.set(
        _cooldown_key(phone_number),
        "1",
        ex=settings.otp_resend_cooldown_seconds,
    )
    logger.info("otp_requested")


async def verify_otp(
    redis: RedisClient,
    *,
    phone_number: str,
    code: str,
) -> PendingSignup | None:
    """
    Verify a submitted code against the stored hash.

    On success, deletes the key (single-use — a code can't be replayed) and
    returns the pending signup data, if any (None means this was a login).

    Raises UnprocessableError if the code is missing/expired, wrong, or the
    max attempt count has been exceeded.
    """
    key = _otp_key(phone_number)
    raw = await redis.get(key)
    if raw is None:
        raise UnprocessableError(
            "This code has expired or was never requested. Request a new one."
        )

    data = json.loads(raw)
    record = _OTPRecord(**data)

    if record.attempts >= settings.otp_max_attempts:
        await redis.delete(key)
        raise UnprocessableError("Too many incorrect attempts. Request a new code.")

    if not verify_otp_code(code, record.code_hash):
        record.attempts += 1
        ttl = await redis.ttl(key)
        await redis.set(
            key,
            json.dumps(asdict(record)),
            ex=ttl if ttl > 0 else settings.otp_expire_seconds,
        )
        logger.warning("otp_verify_mismatch")
        raise UnprocessableError("Invalid code.")

    await redis.delete(key)
    logger.info("otp_verified")
    return PendingSignup(**record.pending) if record.pending is not None else None
