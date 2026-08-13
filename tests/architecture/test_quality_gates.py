"""Mechanical size, secret-safety, and runtime compatibility gates."""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
SOURCE = ROOT / "src" / "qq_time_agent"


def test_handwritten_production_files_do_not_exceed_500_logical_lines() -> None:
    oversized: list[str] = []
    for path in SOURCE.rglob("*.py"):
        logical = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        if len(logical) > 500:
            oversized.append(f"{path.relative_to(ROOT)}: {len(logical)}")
    assert oversized == []


def test_real_environment_file_is_ignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", ".env"],  # noqa: S607
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0


def test_no_unexpected_secret_files_or_private_keys() -> None:
    unexpected = [
        path.name for path in ROOT.glob(".env*") if path.name not in {".env", ".env.example"}
    ]
    assert unexpected == []
    marker = "-----BEGIN " + "PRIVATE KEY-----"
    leaks: list[str] = []
    for path in _repository_text_files():
        if marker in path.read_text(encoding="utf-8", errors="ignore"):
            leaks.append(str(path.relative_to(ROOT)))
    assert leaks == []


def test_no_high_confidence_tokens_or_literal_production_secrets() -> None:
    token_patterns = (
        re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    )
    assignment = re.compile(
        r"(?i)([A-Za-z0-9_]*(?:secret|password|token|api_key)[A-Za-z0-9_]*)"
        r"\s*=\s*[\"']([^\"']{8,})[\"']"
    )
    leaks: list[str] = []
    for path in _repository_text_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(pattern.search(text) for pattern in token_patterns):
            leaks.append(str(path.relative_to(ROOT)))
            continue
        for match in assignment.finditer(text):
            variable = match.group(1).lower()
            value = match.group(2).lower()
            if variable == value:
                continue
            if not value.startswith(("synthetic", "sandbox", "not-for-logs")):
                leaks.append(str(path.relative_to(ROOT)))
                break
    assert leaks == []


def test_runtime_is_pinned_to_python_312() -> None:
    version_file = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert version_file == "3.12"
    assert 'requires-python = ">=3.12,<3.13"' in pyproject
    assert sys.version_info[:2] == (3, 12)


def _repository_text_files() -> list[Path]:
    excluded = {".git", ".venv", ".env"}
    return [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and not any(part in excluded for part in path.parts)
        and path.suffix in {".py", ".md", ".toml", ".yaml", ".yml", ".ini", ".example"}
    ]
