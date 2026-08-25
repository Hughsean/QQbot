"""Static safety contracts for destructive operational assets."""

from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_restore_preserves_current_tombstones_before_database_overwrite() -> None:
    script = (ROOT / "ops" / "Restore-QQTimeAgent.ps1").read_text(encoding="utf-8")
    export = script.index("Exporting current deletion ledger failed")
    restore = script.index("dropdb --force")
    migrate = script.index("run --rm -e DATABASE_NAME=$DatabaseName migrate")
    merge = script.index("Merging current deletion ledger failed")
    replay = script.index("run --rm -e DATABASE_NAME=$DatabaseName replay-tombstones")
    assert export < restore < migrate < merge < replay
    assert "pg_restore --no-owner" in script
    assert "ON CONFLICT (subject_ref) DO NOTHING" in script
    assert r".venv\Scripts" not in script


def test_restore_and_backup_fail_closed_on_native_command_errors() -> None:
    restore = (ROOT / "ops" / "Restore-QQTimeAgent.ps1").read_text(encoding="utf-8")
    backup = (ROOT / "ops" / "Backup-QQTimeAgent.ps1").read_text(encoding="utf-8")
    assert restore.count("$LASTEXITCODE -ne 0") >= 6
    assert backup.count("$LASTEXITCODE -ne 0") >= 2


def test_compose_keeps_host_and_container_port_contracts_consistent() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "image: qq-time-agent:local" in compose
    assert compose.count("    build: .") == 1
    assert "pgvector/pgvector:0.8.1-pg17@sha256:" in compose
    assert "ollama/ollama@sha256:" in compose
    assert 'OLLAMA_BASE_URL: "http://ollama:11434"' in compose
    assert "ollama-init" in compose
    assert "qq_time_agent_ollama" in compose
    gpu = (ROOT / "compose.gpu.yaml").read_text(encoding="utf-8")
    assert "gpus: all" in gpu
    assert 'APP_LISTEN_PORT: "${APP_LISTEN_PORT:-8000}"' in compose
    assert 'DATABASE_PORT: "5432"' in compose
    assert "127.0.0.1:${DATABASE_PORT:-5432}:5432" in compose
    assert "127.0.0.1:${APP_LISTEN_PORT:-8000}:${APP_LISTEN_PORT:-8000}" in compose
    assert "os.environ['APP_LISTEN_PORT']" in compose
    assert "qq-time-agent-requeue-knowledge-jobs" in compose


def test_portable_bundle_scripts_do_not_package_dotenv() -> None:
    builder = (ROOT / "ops" / "Build-MigrationBundle.ps1").read_text(encoding="utf-8")
    starter = (ROOT / "start.sh").read_text(encoding="utf-8")
    assert '".env"' not in builder.split("$files =", 1)[1]
    assert "data/database.dump" in builder
    assert "data/assets.tar" in builder
    assert "data/ollama-model.tar" in builder
    assert "CREDENTIAL_ENCRYPTION_KEY" in builder
    assert "docker load" in starter
    assert "replay-tombstones" in starter


def test_ops_has_no_bare_metal_process_supervision_scripts() -> None:
    assert not (ROOT / "ops" / "Register-QQTimeAgentTasks.ps1").exists()
    assert not (ROOT / "ops" / "Start-QQTimeAgentRole.ps1").exists()


def test_tencent_caddy_serves_only_static_site() -> None:
    caddyfile = (ROOT / "ops" / "tencent" / "Caddyfile").read_text(encoding="utf-8")
    assert "hughsean.online" in caddyfile
    assert "www.hughsean.online" in caddyfile
    assert "agent.hughsean.online" not in caddyfile
    assert "reverse_proxy" not in caddyfile
