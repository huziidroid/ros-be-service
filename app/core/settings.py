from pydantic import Field, SecretStr, ValidationInfo, field_validator
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
    # Platform-level Meta App credentials (SecretStr masks values in logs).
    whatsapp_app_id: str = Field(alias="WHATSAPP_APP_ID")
    whatsapp_app_secret: SecretStr = Field(alias="WHATSAPP_APP_SECRET")
    # hub.verify_token for the GET handshake; payload signatures use app_secret.
    whatsapp_webhook_secret: SecretStr = Field(alias="WHATSAPP_WEBHOOK_SECRET")
    # System User — non-expiring platform token for sending on behalf of tenants.
    whatsapp_system_user_id: str = Field(alias="WHATSAPP_SYSTEM_USER_ID")
    whatsapp_system_user_token: SecretStr = Field(alias="WHATSAPP_SYSTEM_USER_TOKEN")
    # Extended credit line ID, shared with each tenant's WABA.
    whatsapp_extended_credit_id: str = Field(alias="WHATSAPP_EXTENDED_CREDIT_ID")
    # Optional number for smoke-testing a newly registered tenant number.
    whatsapp_test_recipient_number: str | None = Field(
        default=None, alias="WHATSAPP_TEST_RECIPIENT_NUMBER"
    )
    # phone_number_id on this platform's own WABA — sends login/signup OTPs.
    whatsapp_otp_sender_phone_number_id: str = Field(
        alias="WHATSAPP_OTP_SENDER_PHONE_NUMBER_ID"
    )
    # Approved AUTHENTICATION template for OTP delivery; unset → free-form text.
    whatsapp_otp_template_name: str | None = Field(
        default=None, alias="WHATSAPP_OTP_TEMPLATE_NAME"
    )
    whatsapp_otp_template_language: str = Field(
        default="en_US", alias="WHATSAPP_OTP_TEMPLATE_LANGUAGE"
    )

    @property
    def whatsapp_api_base(self) -> str:
        """Versioned base URL, e.g. https://graph.facebook.com/v25.0."""
        return f"{self.whatsapp_api_url}/{self.whatsapp_api_version}"

    # LLM / agents
    openai_api_key: SecretStr = Field(alias="OPENAI_API_KEY")
    openai_default_model: str = Field(
        default="gpt-4.1-mini", alias="OPENAI_DEFAULT_MODEL"
    )
    routing_confidence_threshold: float = Field(
        default=0.6, alias="ROUTING_CONFIDENCE_THRESHOLD"
    )
    routing_use_self_consistency: bool = Field(
        default=False, alias="ROUTING_USE_SELF_CONSISTENCY"
    )
    # Flip manually after running app/agents/eval/test_router.py and finding
    # ECE > 0.10 — a human decision from an offline batch metric, not something
    # the code auto-detects per request.
    routing_memory_turns: int = Field(default=6, alias="ROUTING_MEMORY_TURNS")
    routing_conversation_idle_minutes: int = Field(
        default=30, alias="ROUTING_CONVERSATION_IDLE_MINUTES"
    )
    routing_conversation_close_days: int = Field(
        default=7, alias="ROUTING_CONVERSATION_CLOSE_DAYS"
    )
    classify_max_intents: int = Field(default=3, alias="CLASSIFY_MAX_INTENTS")

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
    # Derives the Fernet key that encrypts WhatsApp two-step PINs at rest.
    pin_encryption_key: SecretStr = Field(alias="PIN_ENCRYPTION_KEY")

    @field_validator(
        "secret_key",
        "pin_encryption_key",
        "whatsapp_app_secret",
        "whatsapp_webhook_secret",
        "whatsapp_system_user_token",
        "openai_api_key",
        mode="after",
    )
    @classmethod
    def _reject_empty_secret(cls, value: SecretStr, info: ValidationInfo) -> SecretStr:
        # Fail at startup rather than deep inside a request.
        if not value.get_secret_value().strip():
            raise ValueError(f"{info.field_name} must be set and non-empty")
        return value

    # OTP — ephemeral state lives in Redis, keyed by phone number.
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

    # CORS — comma-separated browser origins. Empty = no cross-origin access.
    cors_allowed_origins: str = Field(default="", alias="CORS_ALLOWED_ORIGINS")

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    # Rate limiting — per-IP limits on public auth endpoints (slowapi format).
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


# Required fields are populated from the environment at runtime; mypy can't see
# that, so it flags missing arguments here — known false positive.
settings = Settings()  # type: ignore[call-arg]
