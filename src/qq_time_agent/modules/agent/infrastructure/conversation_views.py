"""Database row mappings for conversation timeline persistence."""

from qq_time_agent.modules.agent.contracts import (
    ConversationDeliveryStatus,
    ConversationEventRole,
    ConversationEventType,
    ConversationEventView,
    ConversationScopeType,
    ConversationSummaryView,
)
from qq_time_agent.modules.agent.infrastructure.tables import (
    ConversationEventRow,
    ConversationSummaryRow,
)


def event_view(row: ConversationEventRow) -> ConversationEventView:
    return ConversationEventView(
        event_id=row.event_id,
        scope_type=ConversationScopeType(row.scope_type),
        scope_id=row.scope_id,
        user_id=row.user_id,
        sequence=row.sequence,
        event_type=ConversationEventType(row.event_type),
        role=ConversationEventRole(row.role),
        occurred_at=row.occurred_at,
        created_at=row.created_at,
        content=row.content,
        content_ref=row.content_ref or "",
        content_hash=row.content_hash,
        delivery_status=None
        if row.delivery_status is None
        else ConversationDeliveryStatus(row.delivery_status),
        run_id=row.run_id,
        inbox_item_id=row.inbox_item_id,
        notification_intent_id=row.notification_intent_id,
        idempotency_key=row.idempotency_key,
        metadata=dict(row.metadata_json),
    )


def summary_view(row: ConversationSummaryRow) -> ConversationSummaryView:
    return ConversationSummaryView(
        summary_id=row.summary_id,
        user_id=row.user_id,
        scope_type=ConversationScopeType(row.scope_type),
        scope_id=row.scope_id,
        from_sequence=row.from_sequence,
        to_sequence=row.to_sequence,
        summary_text=row.content,
        source_hash=row.source_hash,
        facts=_summary_values(row.structured_json, "facts"),
        decisions=_summary_values(row.structured_json, "decisions"),
        commitments=_summary_values(row.structured_json, "commitments"),
        open_loops=_summary_values(row.structured_json, "open_loops"),
        preferences=_summary_values(row.structured_json, "preferences"),
        time_anchors=_summary_values(row.structured_json, "time_anchors"),
        tool_side_effects=_summary_values(row.structured_json, "tool_side_effects"),
        idempotency_key=row.idempotency_key,
        created_at=row.created_at,
    )


def summary_matches(row: ConversationSummaryRow, summary: ConversationSummaryView) -> bool:
    return (
        row.summary_id == summary.summary_id
        and row.user_id == summary.user_id
        and row.scope_type == summary.scope_type.value
        and row.scope_id == summary.scope_id
        and row.from_sequence == summary.from_sequence
        and row.to_sequence == summary.to_sequence
        and row.source_hash == summary.source_hash
        and row.content == summary.summary_text
        and (row.structured_json or {}) == structured_summary(summary)
    )


def structured_summary(summary: ConversationSummaryView) -> dict[str, list[str]]:
    return {
        key: list(values)
        for key, values in {
            "facts": summary.facts,
            "decisions": summary.decisions,
            "commitments": summary.commitments,
            "open_loops": summary.open_loops,
            "preferences": summary.preferences,
            "time_anchors": summary.time_anchors,
            "tool_side_effects": summary.tool_side_effects,
        }.items()
        if values
    }


def _summary_values(data: dict[str, object], key: str) -> tuple[str, ...]:
    value = data.get(key, ())
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, str))
