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
    assert 'APP_LISTEN_PORT: "${APP_LISTEN_PORT:-8000}"' in compose
    assert 'DATABASE_PORT: "5432"' in compose
    assert "127.0.0.1:${DATABASE_PORT:-5432}:5432" in compose
    assert "127.0.0.1:${APP_LISTEN_PORT:-8000}:${APP_LISTEN_PORT:-8000}" in compose
    assert "os.environ['APP_LISTEN_PORT']" in compose
    assert "qq-time-agent-requeue-knowledge-jobs" in compose


def test_process_supervision_has_no_public_tunnel_role() -> None:
    register = (ROOT / "ops" / "Register-QQTimeAgentTasks.ps1").read_text(encoding="utf-8")
    launcher = (ROOT / "ops" / "Start-QQTimeAgentRole.ps1").read_text(encoding="utf-8")
    combined = f"{register}\n{launcher}".lower()
    assert '"tunnel"' not in combined
    assert "reverse" not in combined
    assert "127.0.0.1:8000:127.0.0.1:8000" not in combined


def test_tencent_caddy_serves_only_static_site() -> None:
    caddyfile = (ROOT / "ops" / "tencent" / "Caddyfile").read_text(encoding="utf-8")
    assert "hughsean.online" in caddyfile
    assert "www.hughsean.online" in caddyfile
    assert "agent.hughsean.online" not in caddyfile
    assert "reverse_proxy" not in caddyfile
