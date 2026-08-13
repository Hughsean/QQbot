"""Static safety contracts for destructive operational assets."""

from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_restore_preserves_current_tombstones_before_database_overwrite() -> None:
    script = (ROOT / "ops" / "Restore-QQTimeAgent.ps1").read_text(encoding="utf-8")
    export = script.index("Exporting current deletion ledger failed")
    restore = script.index("dropdb --force")
    migrate = script.index('alembic.exe") upgrade head')
    merge = script.index("Merging current deletion ledger failed")
    replay = script.index('qq-time-agent-replay-tombstones.exe")')
    assert export < restore < migrate < merge < replay
    assert "pg_restore --no-owner" in script
    assert "ON CONFLICT (subject_ref) DO NOTHING" in script


def test_restore_and_backup_fail_closed_on_native_command_errors() -> None:
    restore = (ROOT / "ops" / "Restore-QQTimeAgent.ps1").read_text(encoding="utf-8")
    backup = (ROOT / "ops" / "Backup-QQTimeAgent.ps1").read_text(encoding="utf-8")
    assert restore.count("$LASTEXITCODE -ne 0") >= 6
    assert backup.count("$LASTEXITCODE -ne 0") >= 2
