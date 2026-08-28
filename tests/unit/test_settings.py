from pydantic import SecretStr, ValidationError
from pytest import raises

from qq_time_agent.bootstrap.settings import (
    CONTAINER_BIND_HOST,
    EnvironmentSettings,
    _to_runtime_config,
)


def test_settings_accept_safe_loopback_configuration() -> None:
    settings = EnvironmentSettings.model_validate(_values())
    assert settings.rag_embedding_dimensions == 1024
    assert settings.qq_diagnostic_raw_event_once is False
    assert settings.database_password.get_secret_value() == "synthetic-password"
    assert _to_runtime_config(settings).microsoft.redirect_uri == (
        "http://localhost:8000/oauth/microsoft/callback"
    )
    assert _to_runtime_config(settings).qq.diagnostic_raw_event_once is False


def test_settings_diagnostic_flag_can_be_enabled() -> None:
    values = _values()
    values["qq_diagnostic_raw_event_once"] = True
    settings = EnvironmentSettings.model_validate(values)
    assert settings.qq_diagnostic_raw_event_once is True
    assert _to_runtime_config(settings).qq.diagnostic_raw_event_once is True


def test_settings_accept_200k_agent_context_profile() -> None:
    values = _values()
    values.update(
        {
            "agent_context_max_tokens": 200_000,
            "agent_context_safety_margin_tokens": 4_096,
            "agent_context_retrieval_limit": 20,
            "agent_context_history_limit": 40,
            "agent_context_observation_tokens": 20_000,
            "agent_model_output_token_budget": 32_000,
            "agent_max_output_tokens_per_request": 4_000,
        }
    )
    settings = EnvironmentSettings.model_validate(values)
    config = _to_runtime_config(settings).agent_context
    assert config.max_context_tokens == 200_000
    assert config.observation_tokens == 20_000
    assert config.model_output_token_budget == 32_000
    assert config.max_output_tokens_per_request == 4_000


def test_settings_reject_agent_context_above_200k() -> None:
    values = _values()
    values["agent_context_max_tokens"] = 200_001
    with raises(ValidationError):
        EnvironmentSettings.model_validate(values)


def test_settings_reject_per_request_output_above_total_budget() -> None:
    values = _values()
    values["agent_model_output_token_budget"] = 1_000
    values["agent_max_output_tokens_per_request"] = 1_001
    with raises(ValidationError, match="must not exceed"):
        EnvironmentSettings.model_validate(values)


def test_settings_require_output_and_margin_to_leave_input_context() -> None:
    values = _values()
    values["agent_context_max_tokens"] = 2_000
    values["agent_context_safety_margin_tokens"] = 1_000
    values["agent_max_output_tokens_per_request"] = 1_000
    with raises(ValidationError, match="must leave usable input context"):
        EnvironmentSettings.model_validate(values)


def test_settings_reject_non_loopback_database() -> None:
    values = _values()
    values["database_host"] = "192.168.1.20"
    with raises(ValidationError, match="DATABASE_HOST must be loopback") as error:
        EnvironmentSettings.model_validate(values)
    assert "synthetic-password" not in str(error.value)
    assert "input_value" not in str(error.value)


def test_settings_container_mode_accepts_exact_compose_values() -> None:
    values = _values()
    values["app_container"] = True
    values["app_listen_host"] = CONTAINER_BIND_HOST
    values["database_host"] = "postgres"
    values["ollama_base_url"] = "http://ollama:11434"
    values["asset_storage_path"] = "/var/lib/qq-time-agent/assets"
    settings = EnvironmentSettings.model_validate(values)
    assert settings.app_listen_host == CONTAINER_BIND_HOST
    assert _to_runtime_config(settings).assets.raw_retention_hours == 24


def test_settings_container_mode_rejects_non_zero_bind() -> None:
    values = _values()
    values["app_container"] = True
    values["app_listen_host"] = "127.0.0.1"
    values["database_host"] = "postgres"
    values["ollama_base_url"] = "http://ollama:11434"
    with raises(ValidationError, match="APP_CONTAINER requires APP_LISTEN_HOST"):
        EnvironmentSettings.model_validate(values)


def test_settings_container_mode_rejects_non_compose_database_host() -> None:
    values = _values()
    values["app_container"] = True
    values["app_listen_host"] = CONTAINER_BIND_HOST
    values["database_host"] = "192.168.1.20"
    values["ollama_base_url"] = "http://ollama:11434"
    with raises(ValidationError, match="APP_CONTAINER requires DATABASE_HOST"):
        EnvironmentSettings.model_validate(values)


def test_settings_container_mode_rejects_non_docker_ollama_url() -> None:
    values = _values()
    values["app_container"] = True
    values["app_listen_host"] = CONTAINER_BIND_HOST
    values["database_host"] = "postgres"
    values["ollama_base_url"] = "http://127.0.0.1:11434"
    with raises(ValidationError, match="APP_CONTAINER requires OLLAMA_BASE_URL"):
        EnvironmentSettings.model_validate(values)


def test_settings_bare_metal_rejects_container_database_host() -> None:
    values = _values()
    values["database_host"] = "postgres"
    with raises(ValidationError, match="DATABASE_HOST must be loopback"):
        EnvironmentSettings.model_validate(values)


def test_settings_reject_llm_payload_persistence() -> None:
    values = _values()
    values["persist_llm_payloads"] = True
    with raises(ValidationError, match="PERSIST_LLM_PAYLOADS must remain false"):
        EnvironmentSettings.model_validate(values)


def test_settings_reject_blank_qq_display_name() -> None:
    values = _values()
    values["qq_bot_display_name"] = "  "
    with raises(ValidationError, match="QQ_BOT_DISPLAY_NAME must not be blank"):
        EnvironmentSettings.model_validate(values)


def test_secret_string_does_not_render_value() -> None:
    secret = SecretStr("synthetic-secret")
    assert "synthetic-secret" not in repr(secret)


def _values() -> dict[str, object]:
    return {
        "app_signing_key": "synthetic-signing-key",
        "owner_qq_openid": "owner-openid",
        "qq_bot_app_id": "sandbox-app",
        "qq_bot_secret": "sandbox-secret",
        "microsoft_client_id": "synthetic-client",
        "deepseek_api_key": "synthetic-api-key",
        "deepseek_fast_model": "fast-model",
        "deepseek_reasoning_model": "reasoning-model",
        "database_name": "test_db",
        "database_user": "test_user",
        "database_password": "synthetic-password",
        "credential_encryption_key": "synthetic-encryption-key",
        "rag_index_version": "test-index-v1",
    }


def test_settings_container_mode_rejects_unmounted_asset_path() -> None:
    values = _values()
    values["app_container"] = True
    values["app_listen_host"] = CONTAINER_BIND_HOST
    values["database_host"] = "postgres"
    values["ollama_base_url"] = "http://ollama:11434"
    values["asset_storage_path"] = "/srv/assets"
    with raises(ValidationError, match="APP_CONTAINER requires ASSET_STORAGE_PATH"):
        EnvironmentSettings.model_validate(values)
