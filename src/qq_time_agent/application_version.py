"""Application deployment version loaded from the project version file."""

from pathlib import Path

_VERSION_FILE = Path(__file__).resolve().parents[2] / "version"


def load_deployment_version() -> str:
    value = _VERSION_FILE.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError("deployment version file is empty")
    return value


DEPLOYMENT_VERSION = load_deployment_version()
