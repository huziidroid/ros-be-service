"""
OTP service — generate, store, send, and verify login/signup codes.

All state lives in Redis with a TTL; for signup, the pending name fields ride
alongside the code hash so verify only needs {phone_number, code}.

Keys:
  otp:{phone_number}          — code hash, attempts, pending signup data
  otp:cooldown:{phone_number} — resend throttle marker (value unused)
"""

import json
import logging
from dataclasses import asdict, dataclass

from app.clients.redis import RedisClient
from app.clients.whatsapp import send_authentication_template, send_text_message
from app.core.exceptions import RateLimitedError, UnprocessableError
from app.core.security import generate_numeric_code, hash_otp_code, verify_otp_code
from app.core.settings import settings
from app.schemas.auth import PendingSignup


logger = logging.getLogger(__name__)


@dataclass
class _OTPRecord:
    code_hash: str
    attempts: int
    pending: dict[str, str] | None  # PendingSignup fields, or None for login


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
    Generate a code, send it over WhatsApp, then store its hash. Send-first so a
    delivery failure persists nothing. RateLimitedError within the resend cooldown.
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

    # Cloud API `to` wants the E.164 number without the leading '+'.
    to = phone_number.lstrip("+")
    if settings.whatsapp_otp_template_name:
        # Production: template delivers without a 24h session.
        await send_authentication_template(
            phone_number_id=settings.whatsapp_otp_sender_phone_number_id,
            to=to,
            template_name=settings.whatsapp_otp_template_name,
            language=settings.whatsapp_otp_template_language,
            code=code,
        )
    else:
        # Dev fallback: free-form text (delivers only inside a 24h session).
        minutes = settings.otp_expire_seconds // 60
        await send_text_message(
            phone_number_id=settings.whatsapp_otp_sender_phone_number_id,
            to=to,
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
    Verify a code against the stored hash; on success delete it (single-use) and
    return any pending signup data (None = login). UnprocessableError if the code
    is missing/expired, wrong, or the attempt limit is exceeded.
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
