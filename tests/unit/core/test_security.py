"""
Unit tests for app.core.security — encryption, password hashing, JWTs, and
OTP codes.
"""

import pytest
from pydantic import SecretStr

from app.core.security import (
    EncryptionError,
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    decrypt_secret,
    encrypt_secret,
    generate_numeric_code,
    hash_otp_code,
    hash_password,
    verify_otp_code,
    verify_password,
)
from app.core.settings import settings


class TestPinEncryption:
    @pytest.fixture(autouse=True)
    def _set_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Independent of whatever (if anything) PIN_ENCRYPTION_KEY is set to
        # in the local environment.
        monkeypatch.setattr(
            settings, "pin_encryption_key", SecretStr("test-pin-encryption-key")
        )

    def test_round_trips(self) -> None:
        ciphertext = encrypt_secret("123456")
        assert decrypt_secret(ciphertext) == "123456"

    def test_ciphertext_does_not_contain_plaintext(self) -> None:
        assert "123456" not in encrypt_secret("123456")

    def test_tampered_ciphertext_raises(self) -> None:
        ciphertext = encrypt_secret("123456")
        with pytest.raises(EncryptionError):
            decrypt_secret(ciphertext[:-4] + "abcd")

    def test_missing_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "pin_encryption_key", SecretStr(""))
        with pytest.raises(EncryptionError):
            encrypt_secret("123456")


class TestPasswordHashing:
    def test_verify_succeeds_for_matching_password(self) -> None:
        password_hash = hash_password("correct-horse-battery-staple")
        assert verify_password("correct-horse-battery-staple", password_hash) is True

    def test_verify_fails_for_wrong_password(self) -> None:
        password_hash = hash_password("correct-horse-battery-staple")
        assert verify_password("wrong-password", password_hash) is False

    def test_verify_fails_for_malformed_hash(self) -> None:
        assert verify_password("anything", "not-a-real-argon2-hash") is False

    def test_hash_does_not_contain_plaintext(self) -> None:
        password = "correct-horse-battery-staple"
        assert password not in hash_password(password)

    def test_same_password_hashes_differently_each_time(self) -> None:
        # Argon2 salts automatically — two hashes of the same password must differ.
        assert hash_password("same-password") != hash_password("same-password")


class TestTokens:
    def test_access_token_round_trips(self) -> None:
        token = create_access_token(user_id="user-1", tenant_id="tenant-1")
        payload = decode_token(token, expected_type="access")
        assert payload.user_id == "user-1"
        assert payload.tenant_id == "tenant-1"
        assert payload.token_type == "access"

    def test_refresh_token_round_trips(self) -> None:
        token = create_refresh_token(user_id="user-1", tenant_id="tenant-1")
        payload = decode_token(token, expected_type="refresh")
        assert payload.token_type == "refresh"

    def test_access_token_rejected_as_refresh(self) -> None:
        token = create_access_token(user_id="user-1", tenant_id="tenant-1")
        with pytest.raises(TokenError):
            decode_token(token, expected_type="refresh")

    def test_garbage_token_raises(self) -> None:
        with pytest.raises(TokenError):
            decode_token("not-a-real-token", expected_type="access")


class TestGenerateNumericCode:
    def test_respects_requested_length(self) -> None:
        for length in (4, 6, 8):
            code = generate_numeric_code(length)
            assert len(code) == length
            assert code.isdigit()

    def test_produces_varied_values(self) -> None:
        codes = {generate_numeric_code(6) for _ in range(50)}
        # Extremely unlikely to collide this much if randomness is broken.
        assert len(codes) > 40


class TestOtpHashing:
    def test_verify_succeeds_for_matching_code(self) -> None:
        code = generate_numeric_code(6)
        code_hash = hash_otp_code(code)
        assert verify_otp_code(code, code_hash) is True

    def test_verify_fails_for_wrong_code(self) -> None:
        code_hash = hash_otp_code("123456")
        assert verify_otp_code("654321", code_hash) is False

    def test_hash_does_not_contain_plaintext(self) -> None:
        code = "482913"
        assert code not in hash_otp_code(code)
