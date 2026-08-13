"""Bootstrap-only environment loading and validation."""

from datetime import time
from ipaddress import ip_address
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from qq_time_agent.bootstrap.config_models import (
    AppConfig,
    DatabaseConfig,
    DeepSeekConfig,
    MicrosoftConfig,
    OllamaConfig,
    OwnerConfig,
    QqConfig,
    RetentionConfig,
    RuntimeConfig,
    ScheduleConfig,
)


class EnvironmentSettings(BaseSettings):
    """Flat environment contract; converted immediately to grouped config."""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
        hide_input_in_errors=True,
    )

    app_env: str = "development"
    app_base_url: str = "https://agent.hughsean.online"
    app_listen_host: str = "127.0.0.1"
    app_listen_port: int = Field(default=8000, ge=1, le=65535)
    app_signing_key: SecretStr
    owner_qq_openid: SecretStr
    qq_bot_app_id: SecretStr
    qq_bot_secret: SecretStr
    qq_bot_sandbox: bool = True
    microsoft_tenant: str = "common"
    microsoft_client_id: SecretStr
    microsoft_client_secret: SecretStr
    microsoft_redirect_uri: str = "https://agent.hughsean.online/oauth/microsoft/callback"
    deepseek_api_key: SecretStr
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_fast_model: str = "deepseek-v4-flash"
    deepseek_reasoning_model: str = "deepseek-v4-pro"
    deepseek_fast_timeout_seconds: float = Field(default=30, gt=0)
    deepseek_reasoning_timeout_seconds: float = Field(default=60, gt=0)
    deepseek_max_retries: int = Field(default=2, ge=0, le=5)
    deepseek_max_concurrency: int = Field(default=2, ge=1, le=10)
    database_host: str = "127.0.0.1"
    database_port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = "qq_time_agent"
    database_user: str = "qq_time_agent"
    database_password: SecretStr
    credential_encryption_key: SecretStr
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_embedding_model: str = "qwen3-embedding:4b"
    ollama_keep_alive: str = "30m"
    ollama_embedding_concurrency: int = Field(default=1, ge=1, le=4)
    rag_embedding_dimensions: int = 1024
    rag_index_version: str = "qwen3-embedding-4b-1024-v1"
    rag_retrieval_limit: int = Field(default=12, ge=1, le=30)
    rag_vector_weight: float = Field(default=0.65, ge=0, le=1)
    rag_lexical_weight: float = Field(default=0.35, ge=0, le=1)
    default_timezone: str = "Asia/Shanghai"
    default_work_start: time = time(9)
    default_work_end: time = time(18)
    default_lunch_start: time = time(12)
    default_lunch_end: time = time(13, 30)
    default_item_duration_minutes: int = Field(default=30, gt=0)
    default_reminder_lead_minutes: int = Field(default=15, ge=0)
    mail_initial_lookback_days: int = Field(default=7, ge=1, le=30)
    mail_sync_interval_seconds: int = Field(default=300, ge=60)
    retention_source_content_days: int = Field(default=365, gt=0)
    retention_ai_metadata_days: int = Field(default=180, gt=0)
    retention_audit_days: int = Field(default=365, gt=0)
    retention_operational_days: int = Field(default=30, gt=0)
    retention_backup_days: int = Field(default=30, gt=0)
    source_deletion_purge_hours: int = Field(default=24, ge=1, le=24)
    persist_llm_payloads: bool = False

    @model_validator(mode="after")
    def validate_security_boundaries(self) -> "EnvironmentSettings":
        if not ip_address(self.app_listen_host).is_loopback:
            raise ValueError("APP_LISTEN_HOST must be loopback")
        if not ip_address(self.database_host).is_loopback:
            raise ValueError("DATABASE_HOST must be loopback")
        ollama_host = urlparse(self.ollama_base_url).hostname
        if ollama_host is None or not ip_address(ollama_host).is_loopback:
            raise ValueError("OLLAMA_BASE_URL must use a loopback address")
        if self.rag_embedding_dimensions != 1024:
            raise ValueError("RAG_EMBEDDING_DIMENSIONS must be 1024 for the active index")
        if abs(self.rag_vector_weight + self.rag_lexical_weight - 1.0) > 1e-9:
            raise ValueError("RAG retrieval weights must sum to 1")
        if self.persist_llm_payloads:
            raise ValueError("PERSIST_LLM_PAYLOADS must remain false")
        return self


def load_runtime_config() -> RuntimeConfig:
    """Load `.env` exactly once at the composition root."""

    settings = EnvironmentSettings()
    return _to_runtime_config(settings)


def _to_runtime_config(value: EnvironmentSettings) -> RuntimeConfig:
    return RuntimeConfig(
        app=AppConfig(
            value.app_env,
            value.app_base_url,
            value.app_listen_host,
            value.app_listen_port,
            value.app_signing_key,
        ),
        owner=OwnerConfig(value.owner_qq_openid),
        qq=QqConfig(value.qq_bot_app_id, value.qq_bot_secret, value.qq_bot_sandbox),
        database=DatabaseConfig(
            value.database_host,
            value.database_port,
            value.database_name,
            value.database_user,
            value.database_password,
        ),
        microsoft=MicrosoftConfig(
            value.microsoft_tenant,
            value.microsoft_client_id,
            value.microsoft_client_secret,
            value.microsoft_redirect_uri,
        ),
        deepseek=DeepSeekConfig(
            value.deepseek_api_key,
            value.deepseek_base_url,
            value.deepseek_fast_model,
            value.deepseek_reasoning_model,
            value.deepseek_fast_timeout_seconds,
            value.deepseek_reasoning_timeout_seconds,
            value.deepseek_max_retries,
            value.deepseek_max_concurrency,
        ),
        ollama=OllamaConfig(
            value.ollama_base_url,
            value.ollama_embedding_model,
            value.ollama_keep_alive,
            value.ollama_embedding_concurrency,
            value.rag_embedding_dimensions,
            value.rag_index_version,
        ),
        schedule=ScheduleConfig(
            ZoneInfo(value.default_timezone),
            value.default_work_start,
            value.default_work_end,
            value.default_lunch_start,
            value.default_lunch_end,
            value.default_item_duration_minutes,
            value.default_reminder_lead_minutes,
        ),
        retention=RetentionConfig(
            value.retention_source_content_days,
            value.retention_ai_metadata_days,
            value.retention_audit_days,
            value.retention_operational_days,
            value.retention_backup_days,
            value.source_deletion_purge_hours,
        ),
        credential_encryption_key=value.credential_encryption_key,
        mail_initial_lookback_days=value.mail_initial_lookback_days,
        mail_sync_interval_seconds=value.mail_sync_interval_seconds,
        rag_retrieval_limit=value.rag_retrieval_limit,
        rag_vector_weight=value.rag_vector_weight,
        rag_lexical_weight=value.rag_lexical_weight,
    )
