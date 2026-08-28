"""Bootstrap-only environment loading and validation."""

from datetime import time
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from qq_time_agent.bootstrap.config_models import (
    AgentContextConfig,
    AppConfig,
    AssetConfig,
    DatabaseConfig,
    DeepSeekConfig,
    MicrosoftConfig,
    OllamaConfig,
    OwnerConfig,
    QqConfig,
    QqMailConfig,
    QqMailSandboxConfig,
    RetentionConfig,
    RuntimeConfig,
    ScheduleConfig,
)

CONTAINER_BIND_HOST = ip_address(0).compressed


def _require_loopback_host(value: str, name: str) -> None:
    try:
        is_loopback = ip_address(value).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        raise ValueError(f"{name} must be loopback")


class EnvironmentSettings(BaseSettings):
    """Flat environment contract; converted immediately to grouped config."""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
        hide_input_in_errors=True,
    )

    app_env: str = "development"
    app_container: bool = False
    app_listen_host: str = "127.0.0.1"
    app_listen_port: int = Field(default=8000, ge=1, le=65535)
    app_signing_key: SecretStr
    owner_qq_openid: SecretStr
    qq_bot_app_id: SecretStr
    qq_bot_secret: SecretStr
    qq_bot_sandbox: bool = True
    qq_bot_display_name: str = Field(default="小智", min_length=1, max_length=32)
    qq_diagnostic_raw_event_once: bool = False
    qq_interaction_probe_enabled: bool = False
    microsoft_tenant: str = "common"
    microsoft_client_id: SecretStr
    qq_mail_imap_host: str = "imap.qq.com"
    qq_mail_imap_port: int = Field(default=993, ge=1, le=65535)
    qq_mail_timeout_seconds: float = Field(default=20, gt=0, le=120)
    qq_mail_max_retries: int = Field(default=2, ge=0, le=5)
    qq_mail_page_size: int = Field(default=50, ge=1, le=100)
    deepseek_api_key: SecretStr
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_fast_model: str = "deepseek-v4-flash"
    deepseek_reasoning_model: str = "deepseek-v4-pro"
    deepseek_fast_timeout_seconds: float = Field(default=30, gt=0)
    deepseek_reasoning_timeout_seconds: float = Field(default=60, gt=0)
    deepseek_max_retries: int = Field(default=2, ge=0, le=5)
    deepseek_max_concurrency: int = Field(default=2, ge=1, le=10)
    agent_context_max_tokens: int = Field(default=12_000, ge=1_000, le=200_000)
    agent_context_safety_margin_tokens: int = Field(default=512, ge=0, le=8_000)
    agent_context_retrieval_limit: int = Field(default=6, ge=1, le=30)
    agent_context_history_limit: int = Field(default=8, ge=1, le=50)
    agent_context_observation_tokens: int = Field(default=4_000, ge=500, le=32_000)
    agent_model_output_token_budget: int = Field(default=9_600, ge=1, le=32_000)
    agent_max_output_tokens_per_request: int = Field(default=1_200, ge=1, le=32_000)
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
    asset_storage_path: Path = Path(".data/assets")
    asset_max_bytes: int = Field(default=20 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)
    asset_raw_retention_hours: int = Field(default=24, ge=1, le=24)
    asset_max_pdf_pages: int = Field(default=50, ge=1, le=200)
    asset_max_image_pixels: int = Field(default=40_000_000, ge=1_000_000, le=100_000_000)
    asset_max_output_chars: int = Field(default=200_000, ge=1_000, le=1_000_000)
    asset_processing_timeout_seconds: int = Field(default=60, ge=5, le=300)
    retention_source_content_days: int = Field(default=365, gt=0)
    retention_ai_metadata_days: int = Field(default=180, gt=0)
    retention_audit_days: int = Field(default=365, gt=0)
    retention_operational_days: int = Field(default=30, gt=0)
    retention_backup_days: int = Field(default=30, gt=0)
    source_deletion_purge_hours: int = Field(default=24, ge=1, le=24)
    persist_llm_payloads: bool = False

    @model_validator(mode="after")
    def validate_security_boundaries(self) -> "EnvironmentSettings":
        if self.app_container:
            self._validate_container_boundaries()
        else:
            self._validate_loopback_boundaries()
        if self.rag_embedding_dimensions != 1024:
            raise ValueError("RAG_EMBEDDING_DIMENSIONS must be 1024 for the active index")
        if abs(self.rag_vector_weight + self.rag_lexical_weight - 1.0) > 1e-9:
            raise ValueError("RAG retrieval weights must sum to 1")
        if self.persist_llm_payloads:
            raise ValueError("PERSIST_LLM_PAYLOADS must remain false")
        if self.qq_mail_imap_host != "imap.qq.com" or self.qq_mail_imap_port != 993:
            raise ValueError("QQ Mail IMAP must use imap.qq.com:993")
        if self.qq_interaction_probe_enabled and not self.qq_bot_sandbox:
            raise ValueError("QQ_INTERACTION_PROBE_ENABLED requires QQ_BOT_SANDBOX=true")
        if not self.qq_bot_display_name.strip():
            raise ValueError("QQ_BOT_DISPLAY_NAME must not be blank")
        if self.agent_max_output_tokens_per_request > self.agent_model_output_token_budget:
            raise ValueError(
                "AGENT_MAX_OUTPUT_TOKENS_PER_REQUEST must not exceed "
                "AGENT_MODEL_OUTPUT_TOKEN_BUDGET"
            )
        if (
            self.agent_max_output_tokens_per_request + self.agent_context_safety_margin_tokens
            >= self.agent_context_max_tokens
        ):
            raise ValueError(
                "Agent output reservation and safety margin must leave usable input context"
            )
        return self

    def _validate_container_boundaries(self) -> None:
        if self.app_listen_host != CONTAINER_BIND_HOST:
            raise ValueError("APP_CONTAINER requires APP_LISTEN_HOST=0.0.0.0")
        if self.database_host != "postgres":
            raise ValueError("APP_CONTAINER requires DATABASE_HOST=postgres")
        if self.ollama_base_url != "http://ollama:11434":
            raise ValueError("APP_CONTAINER requires OLLAMA_BASE_URL=http://ollama:11434")
        if self.asset_storage_path.as_posix() != "/var/lib/qq-time-agent/assets":
            raise ValueError(
                "APP_CONTAINER requires ASSET_STORAGE_PATH=/var/lib/qq-time-agent/assets"
            )

    def _validate_loopback_boundaries(self) -> None:
        _require_loopback_host(self.app_listen_host, "APP_LISTEN_HOST")
        _require_loopback_host(self.database_host, "DATABASE_HOST")
        ollama_host = urlparse(self.ollama_base_url).hostname
        if ollama_host is None:
            raise ValueError("OLLAMA_BASE_URL must use a loopback address")
        _require_loopback_host(ollama_host, "OLLAMA_BASE_URL")


class QqMailSandboxSettings(BaseSettings):
    """Loaded only by an explicitly opted-in real QQ Mail sandbox test."""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
        hide_input_in_errors=True,
    )

    qq_mail_sandbox_address: SecretStr
    qq_mail_sandbox_auth_code: SecretStr


def load_runtime_config() -> RuntimeConfig:
    """Load `.env` exactly once at the composition root."""

    settings = EnvironmentSettings()
    return _to_runtime_config(settings)


def load_qq_mail_sandbox_config() -> QqMailSandboxConfig:
    settings = QqMailSandboxSettings()
    return QqMailSandboxConfig(
        settings.qq_mail_sandbox_address,
        settings.qq_mail_sandbox_auth_code,
    )


def _to_runtime_config(value: EnvironmentSettings) -> RuntimeConfig:
    return RuntimeConfig(
        app=AppConfig(
            value.app_env,
            value.app_listen_host,
            value.app_listen_port,
            value.app_signing_key,
        ),
        owner=OwnerConfig(value.owner_qq_openid),
        qq=QqConfig(
            value.qq_bot_app_id,
            value.qq_bot_secret,
            value.qq_bot_sandbox,
            value.qq_bot_display_name.strip(),
            value.qq_diagnostic_raw_event_once,
            value.qq_interaction_probe_enabled,
        ),
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
            f"http://localhost:{value.app_listen_port}/oauth/microsoft/callback",
        ),
        qq_mail=QqMailConfig(
            value.qq_mail_imap_host,
            value.qq_mail_imap_port,
            value.qq_mail_timeout_seconds,
            value.qq_mail_max_retries,
            value.qq_mail_page_size,
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
        assets=AssetConfig(
            value.asset_storage_path,
            value.asset_max_bytes,
            value.asset_raw_retention_hours,
            value.asset_max_pdf_pages,
            value.asset_max_image_pixels,
            value.asset_max_output_chars,
            value.asset_processing_timeout_seconds,
        ),
        agent_context=AgentContextConfig(
            value.agent_context_max_tokens,
            value.agent_context_safety_margin_tokens,
            value.agent_context_retrieval_limit,
            value.agent_context_history_limit,
            value.agent_context_observation_tokens,
            value.agent_model_output_token_budget,
            value.agent_max_output_tokens_per_request,
        ),
        credential_encryption_key=value.credential_encryption_key,
        mail_initial_lookback_days=value.mail_initial_lookback_days,
        mail_sync_interval_seconds=value.mail_sync_interval_seconds,
        rag_retrieval_limit=value.rag_retrieval_limit,
        rag_vector_weight=value.rag_vector_weight,
        rag_lexical_weight=value.rag_lexical_weight,
    )
