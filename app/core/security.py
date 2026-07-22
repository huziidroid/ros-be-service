"""
Security primitives — encryption, password hashing, JWTs, and OTP codes.
Everything here is either a keyed crypto operation or something that
directly protects one (random generation for a code that gets hashed).

Sections:
  PIN encryption   — Fernet, symmetric, decryptable (the WhatsApp two-step
                      PIN needs to be sent to Meta in plaintext later).
  Password hashing — Argon2id, one-way (User.password_hash).
  JWTs             — access + refresh tokens, Bearer-header delivery.
  OTP codes        — random N-digit codes + one-way hash for Redis storage
                      (app/services/otp.py). SHA-256 is enough here,
                      not Argon2: the code is single-use, expires in
                      minutes, and attempts are rate-limited by the caller
                      — there's no long-term secret to protect against
                      offline brute force the way a password hash needs to.
"""

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.settings import settings


# ---------------------------------------------------------------------------
# PIN encryption — currently the WhatsApp two-step PIN
# (app/domain/onboarding.py, app/activities/tenant_onboarding.py)
# ---------------------------------------------------------------------------
#
# Uses Fernet (AES-128-CBC + HMAC-SHA256), keyed from settings.pin_encryption_key,
# kept separate from secret_key so the two can be rotated independently.
# Fernet is symmetric and reversible, which the PIN requires (it goes back
# to Meta in plaintext on registration), and its API handles IV generation
# and authentication internally.
#
# The 32-byte Fernet key is derived via HKDF (RFC 5869) from
# PIN_ENCRYPTION_KEY, with info=b"pin_encryption" for domain separation —
# any other key derived from PIN_ENCRYPTION_KEY elsewhere, with a different
# info value, is guaranteed unrelated to this one.


class EncryptionError(Exception):
    """Raised when encryption/decryption cannot proceed safely."""


def _require_key() -> str:
    raw_key = settings.pin_encryption_key.get_secret_value()
    if not raw_key:
        # Refuse rather than deriving a guessable key from an empty secret.
        raise EncryptionError(
            "PIN_ENCRYPTION_KEY is not set. Set a strong, unique value before "
            "registering any WhatsApp phone number (its two-step PIN is "
            "encrypted with a key derived from PIN_ENCRYPTION_KEY)."
        )
    return raw_key


def _fernet() -> Fernet:
    derived = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=b"pin_encryption"
    ).derive(_require_key().encode())
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a short secret (e.g. a 6-digit PIN) for storage at rest."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    """
    Decrypt a value produced by encrypt_secret.

    Raises EncryptionError if the ciphertext is invalid or was encrypted
    with a different PIN_ENCRYPTION_KEY.
    """
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise EncryptionError(
            "Could not decrypt stored secret — invalid ciphertext or "
            "PIN_ENCRYPTION_KEY has changed since it was encrypted."
        ) from exc


# ---------------------------------------------------------------------------
# Password hashing — Argon2id (User.password_hash)
# ---------------------------------------------------------------------------
#
# One-way — we only ever compare, never decrypt. Separate from PIN
# encryption above, which is symmetric and reversible on purpose.

_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a plaintext password for storage in User.password_hash."""
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """
    Check a plaintext password against a stored Argon2 hash.

    Returns False (never raises) on mismatch or a malformed/foreign hash —
    callers don't need to know which.
    """
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHash):
        return False


# ---------------------------------------------------------------------------
# JWTs — access + refresh tokens
# ---------------------------------------------------------------------------
#
# Signed with settings.secret_key (HS256). Delivered via Bearer header —
# clients send `Authorization: Bearer <access_token>`; the refresh token is
# returned once at signup/login/refresh and stored by the client, not a
# cookie.
#
# No revocation store yet: logout is client-side (discard both tokens), and
# a leaked refresh token stays valid until it expires. Revocation (e.g. a
# Redis denylist keyed by jti) is a deferred fast-follow, not needed for
# the initial rollout.

JWT_ALGORITHM = "HS256"

TokenType = Literal["access", "refresh"]


class TokenError(Exception):
    """Raised when a token is missing, malformed, expired, or the wrong type."""


@dataclass
class TokenPayload:
    user_id: str
    tenant_id: str
    token_type: TokenType


def _create_token(
    *,
    user_id: str,
    tenant_id: str,
    token_type: TokenType,
    expires_delta: timedelta,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(
        payload, settings.secret_key.get_secret_value(), algorithm=JWT_ALGORITHM
    )


def create_access_token(*, user_id: str, tenant_id: str) -> str:
    return _create_token(
        user_id=user_id,
        tenant_id=tenant_id,
        token_type="access",
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )


def create_refresh_token(*, user_id: str, tenant_id: str) -> str:
    return _create_token(
        user_id=user_id,
        tenant_id=tenant_id,
        token_type="refresh",
        expires_delta=timedelta(days=settings.refresh_token_expire_days),
    )


def decode_token(token: str, *, expected_type: TokenType) -> TokenPayload:
    """
    Decode and validate a JWT, checking signature, expiry, and token type.

    Raises TokenError on any problem — callers translate that to a 401
    (see app.api.dependencies.get_current_user).
    """
    try:
        raw = jwt.decode(
            token, settings.secret_key.get_secret_value(), algorithms=[JWT_ALGORITHM]
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Token is invalid.") from exc

    token_type = raw.get("type")
    if token_type != expected_type:
        raise TokenError(f"Expected a {expected_type} token, got {token_type!r}.")

    user_id = raw.get("sub")
    tenant_id = raw.get("tenant_id")
    if not user_id or not tenant_id:
        raise TokenError("Token is missing required claims.")

    return TokenPayload(user_id=user_id, tenant_id=tenant_id, token_type=token_type)


# ---------------------------------------------------------------------------
# OTP codes — login/signup verification (app/services/otp.py)
# ---------------------------------------------------------------------------
#
# Unrelated to the WhatsApp Cloud API two-step verification PIN above —
# that PIN gates Meta's phone number registration and is sent *to Meta*;
# an OTP code is sent *to the user* over WhatsApp to prove they control the
# number.


def generate_numeric_code(length: int) -> str:
    """
    Generate a random `length`-digit numeric code.

    Uses `secrets` (CSPRNG), not `random` — the code proves phone/account
    ownership and must not be predictable. Zero-padded to `length` digits.
    """
    upper_bound = 10**length
    return f"{secrets.randbelow(upper_bound):0{length}d}"


def hash_otp_code(code: str) -> str:
    """Hash a code for storage — the plaintext code is sent over WhatsApp
    and never persisted anywhere, same principle as never storing a
    plaintext password."""
    return hashlib.sha256(code.encode()).hexdigest()


def verify_otp_code(code: str, code_hash: str) -> bool:
    """Constant-time comparison against a stored hash from hash_otp_code."""
    return hmac.compare_digest(hash_otp_code(code), code_hash)
