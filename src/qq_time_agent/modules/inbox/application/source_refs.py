"""Deterministic source references used for cross-module deletion propagation."""

from uuid import UUID

from qq_time_agent.contracts.source import SourceType


def build_source_ref(source_type: SourceType, connection_id: UUID, external_id: str) -> str:
    prefix = {
        SourceType.MICROSOFT_MAIL: "mail",
        SourceType.QQ_MAIL: "qq-mail",
        SourceType.QQ_FORWARD: "qq-forward",
        SourceType.OWNER_NOTE: "owner-note",
        SourceType.QQ_DIRECT: "qq",
    }[source_type]
    return f"{prefix}:{connection_id}:{external_id}"
