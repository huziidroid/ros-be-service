from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = Field(default="Retail OS", alias="APP_NAME")
    debug: bool = Field(default=False, alias="DEBUG")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="APP_LOG_LEVEL")

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/retail_os",
        alias="DATABASE_URL",
    )

    # Redis
    redis_url: str = Field(
        default="redis://localhost:6379",
        alias="REDIS_URL",
    )

    # Temporal
    temporal_host: str = Field(
        default="localhost:7233",
        alias="TEMPORAL_HOST",
    )
    temporal_namespace: str = Field(default="default", alias="TEMPORAL_NAMESPACE")
    temporal_task_queue: str = Field(
        default="retail_os_queue",
        alias="TEMPORAL_TASK_QUEUE",
    )
    # How often TenantReconciliationWorkflow retries failed onboarding steps.
    reconciliation_interval_minutes: int = Field(
        default=60,
        alias="RECONCILIATION_INTERVAL_MINUTES",
    )

    # WhatsApp
    whatsapp_api_url: str = Field(
        default="https://graph.facebook.com",
        alias="WHATSAPP_API_URL",
    )
    whatsapp_api_version: str = Field(
        default="v25.0",
        alias="WHATSAPP_API_VERSION",
    )
    # Platform-level Meta App credentials (not per-tenant). SecretStr masks
    # values in logs/reprs — unwrap with .get_secret_value() at point of use.
    whatsapp_app_id: str = Field(alias="WHATSAPP_APP_ID")
    whatsapp_app_secret: SecretStr = Field(alias="WHATSAPP_APP_SECRET")
    # hub.verify_token for the GET handshake only; payload signatures
    # (X-Hub-Signature-256) are verified with whatsapp_app_secret instead.
    whatsapp_webhook_secret: SecretStr = Field(alias="WHATSAPP_WEBHOOK_SECRET")
    # System User — non-expiring platform token used to send messages on behalf of all tenants
    whatsapp_system_user_id: str = Field(alias="WHATSAPP_SYSTEM_USER_ID")
    whatsapp_system_user_token: SecretStr = Field(alias="WHATSAPP_SYSTEM_USER_TOKEN")
    # Retail OS's extended credit line ID (Business Manager > Extended
    # Credits) — shared with each tenant's WABA so distributors never add
    # their own WhatsApp payment method.
    whatsapp_extended_credit_id: str = Field(alias="WHATSAPP_EXTENDED_CREDIT_ID")
    # Optional — a number Retail OS controls, used to smoke-test a newly
    # registered tenant number after onboarding. Skipped if unset.
    whatsapp_test_recipient_number: str | None = Field(
        default=None, alias="WHATSAPP_TEST_RECIPIENT_NUMBER"
    )
    # A phone_number_id on Retail OS's own platform WABA (registered under
    # the System User's Business Manager, independent of any tenant).
    # Sends login/signup OTP codes — at signup a distributor has no WABA of
    # their own yet, so verification messages can't go out from a
    # tenant-owned number. See app/services/otp.py.
    whatsapp_otp_sender_phone_number_id: str = Field(
        alias="WHATSAPP_OTP_SENDER_PHONE_NUMBER_ID"
    )

    @property
    def whatsapp_api_base(self) -> str:
        """Versioned base URL — e.g. https://graph.facebook.com/v25.0"""
        return f"{self.whatsapp_api_url}/{self.whatsapp_api_version}"

    # Security
    secret_key: SecretStr = Field(alias="SECRET_KEY")
    access_token_expire_minutes: int = Field(
        default=60,
        alias="ACCESS_TOKEN_EXPIRE_MINUTES",
    )
    refresh_token_expire_days: int = Field(
        default=30,
        alias="REFRESH_TOKEN_EXPIRE_DAYS",
    )
    # Separate from secret_key — derives the Fernet key that encrypts
    # WhatsApp two-step PINs at rest (app/core/security.py).
    pin_encryption_key: SecretStr = Field(alias="PIN_ENCRYPTION_KEY")

    @field_validator(
        "secret_key",
        "pin_encryption_key",
        "whatsapp_app_secret",
        "whatsapp_webhook_secret",
        "whatsapp_system_user_token",
        mode="after",
    )
    @classmethod
    def _reject_empty_secret(cls, value: SecretStr, info) -> SecretStr:
        # Fail loudly at startup rather than deep inside a request (e.g. an
        # empty SECRET_KEY only surfaces as "HMAC key must not be empty" when
        # signing a token).
        if not value.get_secret_value().strip():
            raise ValueError(f"{info.field_name} must be set and non-empty")
        return value

    # OTP (login/signup verification codes — see app/core/security.py,
    # app/services/otp.py). All ephemeral state lives in Redis, keyed by
    # phone number and purpose (signup/login).
    otp_length: int = Field(default=6, alias="OTP_LENGTH")
    otp_expire_seconds: int = Field(
        default=300,  # 5 minutes
        alias="OTP_EXPIRE_SECONDS",
    )
    otp_max_attempts: int = Field(default=5, alias="OTP_MAX_ATTEMPTS")
    otp_resend_cooldown_seconds: int = Field(
        default=60,
        alias="OTP_RESEND_COOLDOWN_SECONDS",
    )

    # CORS — comma-separated origins allowed to call this API from a browser,
    # e.g. "https://app.retailos.com,https://admin.retailos.com". Empty by
    # default (no cross-origin browser access) rather than a wildcard or a
    # dev-permissive guess, since ros-frontend-core doesn't call this API yet
    # and the right dev origin/port isn't this service's business to assume.
    cors_allowed_origins: str = Field(default="", alias="CORS_ALLOWED_ORIGINS")

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    # Rate limiting (app/core/rate_limit.py) — per-IP limits on public auth
    # endpoints, on top of (not instead of) each flow's own per-identifier
    # throttling (e.g. the OTP resend cooldown in app/services/otp.py).
    # Format: slowapi/limits rate strings, e.g. "20/minute".
    rate_limit_otp_request: str = Field(
        default="20/minute", alias="RATE_LIMIT_OTP_REQUEST"
    )
    rate_limit_email_login: str = Field(
        default="10/minute", alias="RATE_LIMIT_EMAIL_LOGIN"
    )
    rate_limit_email_signup: str = Field(
        default="10/minute", alias="RATE_LIMIT_EMAIL_SIGNUP"
    )

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use the postgresql+asyncpg driver.")
        return value

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if value.upper() not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}.")
        return value.upper()

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        allowed = {"development", "staging", "production"}
        if value.lower() not in allowed:
            raise ValueError(f"ENVIRONMENT must be one of {allowed}.")
        return value.lower()

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_development(self) -> bool:
        return self.environment == "development"


# Required fields (WHATSAPP_*, SECRET_KEY, PIN_ENCRYPTION_KEY) have no
# defaults and are populated from the environment/.env at runtime by
# pydantic-settings — mypy's static signature check doesn't know that, so
# it flags this call as missing arguments. Known false positive.
settings = Settings()  # type: ignore[call-arg]
