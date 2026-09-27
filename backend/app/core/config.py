from functools import lru_cache
import json
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration. Secrets come exclusively from the environment."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    app_name: str = "Voice Agent Platform"

    # Public URL of this API (used for Twilio webhooks and OAuth callbacks)
    public_base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"
    # NoDecode: accept a plain comma-separated list from the environment (split below) instead of JSON.
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3000"])

    # Security
    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60 * 12
    # Fernet key used to encrypt OAuth tokens at rest
    encryption_key: str
    # Shared secret the LiveKit agent worker uses to call /internal endpoints
    internal_api_token: str = Field(min_length=24)

    # Data stores
    database_url: str = "postgresql+asyncpg://voice:voice@localhost:5432/voice"
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "knowledge_chunks"
    upload_dir: str = "./data/uploads"
    max_upload_mb: int = 25

    # Rate limiting
    rate_limit_default: str = "120/minute"
    rate_limit_auth: str = "10/minute"

    # AI providers
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    embedding_provider: Literal["openai", "gemini"] = "openai"
    openai_embedding_model: str = "text-embedding-3-small"
    gemini_embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = 1536
    intent_model: str = "gpt-4o-mini"
    gemini_intent_model: str = "gemini-3.5-flash-lite"

    # RAG tuning
    chunk_tokens: int = 400
    chunk_overlap_tokens: int = 60
    retrieval_top_k: int = 5
    retrieval_min_score: float = 0.35

    # LiveKit
    livekit_url: str = "ws://localhost:7880"
    livekit_api_key: str | None = None
    livekit_api_secret: str | None = None
    # SIP URI host of the LiveKit SIP service (e.g. xxxx.sip.livekit.cloud)
    livekit_sip_host: str | None = None
    livekit_outbound_trunk_id: str | None = None
    livekit_agent_name: str = "voice-agent"

    # Twilio
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_validate_signatures: bool = True
    # Twilio number used as caller ID for outbound calls when the business hasn't connected its own
    twilio_caller_id: str | None = None
    # Optional SIP credentials Twilio uses when dialing LiveKit's SIP endpoint
    twilio_sip_username: str | None = None
    twilio_sip_password: str | None = None

    # Google Calendar OAuth
    google_client_id: str | None = None
    google_client_secret: str | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, v):
        if isinstance(v, str):
            if v.strip().startswith("["):
                return json.loads(v)
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def google_redirect_uri(self) -> str:
        return f"{self.public_base_url}/api/integrations/google/callback"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
