from pydantic import SecretStr, ValidationError
from pytest import raises

from qq_time_agent.bootstrap.settings import EnvironmentSettings, _to_runtime_config


def test_settings_accept_safe_loopback_configuration() -> None:
    settings = EnvironmentSettings.model_validate(_values())
    assert settings.rag_embedding_dimensions == 1024
    assert settings.database_password.get_secret_value() == "synthetic-password"
    assert _to_runtime_config(settings).microsoft.redirect_uri == (
        "http://localhost:8000/oauth/microsoft/callback"
    )


def test_settings_reject_non_loopback_database() -> None:
    values = _values()
    values["database_host"] = "192.168.1.20"
    with raises(ValidationError, match="DATABASE_HOST must be loopback") as error:
        EnvironmentSettings.model_validate(values)
    assert "synthetic-password" not in str(error.value)
    assert "input_value" not in str(error.value)


def test_settings_reject_llm_payload_persistence() -> None:
    values = _values()
    values["persist_llm_payloads"] = True
    with raises(ValidationError, match="PERSIST_LLM_PAYLOADS must remain false"):
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
