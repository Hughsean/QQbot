"""Strongly typed runtime configuration passed into application components."""

from dataclasses import dataclass
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import SecretStr


@dataclass(frozen=True, slots=True)
class AppConfig:
    environment: str
    listen_host: str
    listen_port: int
    signing_key: SecretStr


@dataclass(frozen=True, slots=True)
class OwnerConfig:
    qq_openid: SecretStr


@dataclass(frozen=True, slots=True)
class QqConfig:
    app_id: SecretStr
    secret: SecretStr
    sandbox: bool
    display_name: str = "小智"
    diagnostic_raw_event_once: bool = False
    interaction_probe_enabled: bool = False


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    host: str
    port: int
    name: str
    user: str
    password: SecretStr


@dataclass(frozen=True, slots=True)
class MicrosoftConfig:
    tenant: str
    client_id: SecretStr
    redirect_uri: str


@dataclass(frozen=True, slots=True)
class QqMailConfig:
    host: str
    port: int
    timeout_seconds: float
    max_retries: int
    page_size: int


@dataclass(frozen=True, slots=True)
class QqMailSandboxConfig:
    address: SecretStr
    authorization_code: SecretStr


@dataclass(frozen=True, slots=True)
class AgentContextConfig:
    max_context_tokens: int
    safety_margin_tokens: int
    retrieval_limit: int
    history_limit: int
    observation_tokens: int
    model_output_token_budget: int = 9_600
    max_output_tokens_per_request: int = 1_200


@dataclass(frozen=True, slots=True)
class DeepSeekConfig:
    api_key: SecretStr
    base_url: str
    fast_model: str
    reasoning_model: str
    fast_timeout_seconds: float
    reasoning_timeout_seconds: float
    max_retries: int
    max_concurrency: int


@dataclass(frozen=True, slots=True)
class OllamaConfig:
    base_url: str
    model: str
    keep_alive: str
    concurrency: int
    dimensions: int
    index_version: str


@dataclass(frozen=True, slots=True)
class ScheduleConfig:
    timezone: ZoneInfo
    work_start: time
    work_end: time
    lunch_start: time
    lunch_end: time
    default_item_minutes: int
    default_reminder_minutes: int


@dataclass(frozen=True, slots=True)
class RetentionConfig:
    source_content_days: int
    ai_metadata_days: int
    audit_days: int
    operational_days: int
    backup_days: int
    source_deletion_hours: int


@dataclass(frozen=True, slots=True)
class AssetConfig:
    storage_path: Path
    max_bytes: int
    raw_retention_hours: int
    max_pdf_pages: int
    max_image_pixels: int
    max_output_chars: int
    processing_timeout_seconds: int


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    app: AppConfig
    owner: OwnerConfig
    qq: QqConfig
    database: DatabaseConfig
    microsoft: MicrosoftConfig
    qq_mail: QqMailConfig
    deepseek: DeepSeekConfig
    ollama: OllamaConfig
    schedule: ScheduleConfig
    retention: RetentionConfig
    assets: AssetConfig
    agent_context: AgentContextConfig
    credential_encryption_key: SecretStr
    mail_initial_lookback_days: int
    mail_sync_interval_seconds: int
    rag_retrieval_limit: int
    rag_vector_weight: float
    rag_lexical_weight: float
