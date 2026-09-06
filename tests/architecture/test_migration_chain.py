"""Static integrity gates for the Alembic migration chain (no database)."""

import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
VERSIONS = ROOT / "alembic" / "versions"
_REVISION = re.compile(r'^revision: str = "([^"]+)"', re.MULTILINE)
_DOWN_REVISION = re.compile(r'^down_revision: str \| None = (?:"([^"]+)"|None)$', re.MULTILINE)


def _load_chain() -> dict[str, str | None]:
    chain: dict[str, str | None] = {}
    for path in VERSIONS.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        revision = _REVISION.search(text)
        down = _DOWN_REVISION.search(text)
        if revision is None or down is None:
            raise AssertionError(f"migration file lacks revision metadata: {path.name}")
        chain[revision.group(1)] = down.group(1) if down.group(1) else None
    return chain


def test_migration_chain_has_a_single_head() -> None:
    chain = _load_chain()
    parents = {value for value in chain.values() if value is not None}
    heads = sorted(revision for revision in chain if revision not in parents)
    assert len(heads) == 1, f"expected one migration head, found {heads}"


def test_migration_chain_is_fully_connected() -> None:
    chain = _load_chain()
    head = next(
        revision
        for revision in chain
        if revision not in {value for value in chain.values() if value is not None}
    )
    walked: set[str] = set()
    current: str | None = head
    while current is not None:
        assert current not in walked, f"migration chain revisits {current}"
        walked.add(current)
        current = chain[current]
    assert walked == set(chain), "migration chain has orphan revisions"


def test_every_migration_defines_upgrade_and_downgrade() -> None:
    for path in VERSIONS.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert re.search(r"^def upgrade\(\)", text, re.MULTILINE), f"{path.name} lacks upgrade"
        assert re.search(r"^def downgrade\(\)", text, re.MULTILINE), f"{path.name} lacks downgrade"
