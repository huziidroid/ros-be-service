"""Security primitives: PIN encryption, password hashing, JWTs, and OTP codes."""

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


# --- PIN encryption (WhatsApp two-step PIN): Fernet, reversible, key derived
# via HKDF from settings.pin_encryption_key ---


class EncryptionError(Exception):
    """Raised when encryption/decryption cannot proceed safely."""


def _require_key() -> str:
    raw_key = settings.pin_encryption_key.get_secret_value()
    if not raw_key:
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
    """Encrypt a short secret (e.g. a PIN) for storage at rest."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a value from encrypt_secret; raises EncryptionError if invalid."""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise EncryptionError(
            "Could not decrypt stored secret — invalid ciphertext or "
            "PIN_ENCRYPTION_KEY has changed since it was encrypted."
        ) from exc


# --- Password hashing: Argon2id, one-way (User.password_hash) ---

_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a plaintext password for storage."""
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Check a password against an Argon2 hash; False (never raises) on mismatch."""
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHash):
        return False


# --- JWTs: access + refresh tokens, HS256, Bearer delivery ---

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
    """Decode and validate a JWT (signature, expiry, type); raises TokenError."""
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


# --- OTP codes: login/signup verification (app/services/otp.py) ---


def generate_numeric_code(length: int) -> str:
    """Generate a random, zero-padded `length`-digit code using a CSPRNG."""
    upper_bound = 10**length
    return f"{secrets.randbelow(upper_bound):0{length}d}"


def hash_otp_code(code: str) -> str:
    """Hash a code for storage; the plaintext is sent over WhatsApp, never persisted."""
    return hashlib.sha256(code.encode()).hexdigest()


def verify_otp_code(code: str, code_hash: str) -> bool:
    """Constant-time comparison against a stored hash from hash_otp_code."""
    return hmac.compare_digest(hash_otp_code(code), code_hash)
