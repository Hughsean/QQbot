"""Static architecture gates derived from docs/04 and docs/13."""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
SOURCE = ROOT / "src" / "qq_time_agent"
MODULES = SOURCE / "modules"
PROVIDER_LOCATIONS = {
    "botpy": "/adapters/inbound/qq/",
    "msal": "/adapters/outbound/microsoft_graph/",
    "openai": "/adapters/outbound/ai/",
}
STANDARD_PROVIDER_LOCATIONS = {
    "email": "/adapters/outbound/qq_mail/",
    "imaplib": "/adapters/outbound/qq_mail/",
}
DOMAIN_FORBIDDEN = {
    "alembic",
    "botpy",
    "fastapi",
    "httpx",
    "langchain",
    "langgraph",
    "msal",
    "openai",
    "pydantic_settings",
    "sqlalchemy",
}
SIDE_EFFECT_SYMBOLS = {
    "ActionRequestHandler",
    "AgendaCommandPort",
    "CredentialHandle",
    "NotificationPort",
    "ReminderCommandPort",
}
READ_ONLY_MODULES = {
    "ai_gateway",
    "embeddings",
    "knowledge",
    "retrieval",
    "scheduling",
    "understanding",
}


def test_modules_only_import_other_modules_public_contracts() -> None:
    violations: list[str] = []
    for path in MODULES.rglob("*.py"):
        owner = path.relative_to(MODULES).parts[0]
        for imported in _imports(path):
            parts = imported.split(".")
            if len(parts) < 4 or parts[:2] != ["qq_time_agent", "modules"]:
                continue
            target = parts[2]
            if target != owner and parts[3] != "contracts":
                violations.append(f"{path.relative_to(ROOT)} -> {imported}")
    assert violations == []


def test_domain_is_framework_and_provider_free() -> None:
    violations: list[str] = []
    for path in MODULES.glob("*/domain/**/*.py"):
        for imported in _imports(path):
            if imported.split(".")[0] in DOMAIN_FORBIDDEN:
                violations.append(f"{path.relative_to(ROOT)} -> {imported}")
    assert violations == []


def test_provider_sdks_are_contained_in_matching_adapters() -> None:
    violations: list[str] = []
    for path in SOURCE.rglob("*.py"):
        imports = {name.split(".")[0] for name in _imports(path)}
        for provider in imports & PROVIDER_LOCATIONS.keys():
            normalized = path.as_posix()
            if PROVIDER_LOCATIONS[provider] not in normalized:
                violations.append(f"{path.relative_to(ROOT)} imports {provider}")
    assert violations == []


def test_imap_and_mime_objects_are_contained_in_qq_mail_adapter() -> None:
    violations: list[str] = []
    for path in SOURCE.rglob("*.py"):
        imports = {name.split(".")[0] for name in _imports(path)}
        for provider in imports & STANDARD_PROVIDER_LOCATIONS.keys():
            if STANDARD_PROVIDER_LOCATIONS[provider] not in path.as_posix():
                violations.append(f"{path.relative_to(ROOT)} imports {provider}")
    assert violations == []


def test_environment_reads_exist_only_in_bootstrap() -> None:
    violations: list[str] = []
    for path in SOURCE.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if ("os.getenv(" in text or "os.environ" in text) and "/bootstrap/" not in path.as_posix():
            violations.append(str(path.relative_to(ROOT)))
    assert violations == []


def test_module_tables_and_foreign_keys_stay_with_owner() -> None:
    violations: list[str] = []
    for path in MODULES.glob("*/infrastructure/**/*.py"):
        owner = path.relative_to(MODULES).parts[0]
        expected_prefix = f"{owner}_"
        text = path.read_text(encoding="utf-8")
        for table_name in re.findall(r'__tablename__\s*=\s*["\']([^"\']+)', text):
            if not table_name.startswith(expected_prefix):
                violations.append(f"{path.relative_to(ROOT)} owns table {table_name}")
        for target in re.findall(r'ForeignKey\(["\']([^"\']+)', text):
            if not target.startswith(expected_prefix):
                violations.append(f"{path.relative_to(ROOT)} references {target}")
    assert violations == []


def test_read_only_modules_do_not_import_side_effect_capabilities() -> None:
    violations: list[str] = []
    for module_name in READ_ONLY_MODULES:
        module_root = MODULES / module_name
        if not module_root.exists():
            continue
        for path in module_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imported = {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                for alias in node.names
            }
            leaked = imported & SIDE_EFFECT_SYMBOLS
            if leaked:
                violations.append(f"{path.relative_to(ROOT)} imports {sorted(leaked)}")
    assert violations == []


def test_modules_do_not_use_text_sql_to_bypass_data_ownership() -> None:
    violations = [
        str(path.relative_to(ROOT))
        for path in MODULES.rglob("*.py")
        if re.search(r"\btext\s*\(", path.read_text(encoding="utf-8"))
    ]
    assert violations == []


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names
