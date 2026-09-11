"""Provider-neutral conversation event construction at persistence boundaries."""

from datetime import datetime

from qq_time_agent.modules.agent.contracts import (
    ConversationEvent,
    ConversationEventType,
    ConversationScopeType,
    ToolObservation,
    bounded_event_content,
)
from qq_time_agent.modules.agent.infrastructure.tables import AgentRunRow


def build_agent_reply_event(
    run: AgentRunRow, delivery: str, now: datetime
) -> ConversationEvent | None:
    """Immutable AGENT_REPLY event for the run's conversation scope."""
    if run.conversation_id is None:
        return None
    content = run.final_content or ""
    if not content.strip():
        return None
    return ConversationEvent(
        scope_type=ConversationScopeType.CONVERSATION,
        scope_id=run.conversation_id,
        user_id=run.user_id,
        event_type=ConversationEventType.AGENT_REPLY,
        occurred_at=now,
        content=bounded_event_content(content),
        idempotency_key=f"agent-reply:{run.run_id}",
        run_id=run.run_id,
        content_ref=f"agent-run:{run.run_id}",
        metadata={"delivery": delivery, "source_type": run.source_type},
    )


def build_tool_events(
    run: AgentRunRow, observation: ToolObservation, now: datetime
) -> tuple[ConversationEvent, ...]:
    """TOOL_CALL plus TOOL_RESULT events for the run's conversation scope."""
    if run.conversation_id is None:
        return ()
    common = {
        "tool": observation.name,
        "call_id": observation.call_id,
        "arguments_hash": observation.arguments_hash,
        "is_error": observation.is_error,
    }
    call = ConversationEvent(
        scope_type=ConversationScopeType.CONVERSATION,
        scope_id=run.conversation_id,
        user_id=run.user_id,
        event_type=ConversationEventType.TOOL_CALL,
        occurred_at=now,
        content=bounded_event_content(
            f"tool {observation.name} call {observation.call_id} "
            f"arguments_sha256 {observation.arguments_hash}"
        ),
        idempotency_key=f"tool-call:{run.run_id}:{observation.call_id}",
        run_id=run.run_id,
        metadata=common,
    )
    result = ConversationEvent(
        scope_type=ConversationScopeType.CONVERSATION,
        scope_id=run.conversation_id,
        user_id=run.user_id,
        event_type=ConversationEventType.TOOL_RESULT,
        occurred_at=now,
        content=bounded_event_content(observation_token_text(observation)),
        idempotency_key=f"tool-result:{run.run_id}:{observation.call_id}",
        run_id=run.run_id,
        content_ref=f"agent-tool-call:{observation.call_id}",
        metadata=common,
    )
    return (call, result)


def observation_token_text(observation: ToolObservation) -> str:
    if isinstance(observation.output, str):
        return observation.output
    return str(observation.output)
