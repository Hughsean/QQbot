from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qq_time_agent.modules.agenda.contracts import AgendaConflictView, AgendaNotificationItem
from qq_time_agent.modules.agent.application.context import AgentContextAssembler
from qq_time_agent.modules.agent.contracts import ContextScope, ScopedAgentReply
from qq_time_agent.modules.identity.contracts import OwnerGroupAlias
from qq_time_agent.modules.inbox.contracts import ConversationContextItem, InboxContentView
from qq_time_agent.modules.retrieval.contracts import RetrievedChunk
from qq_time_agent.modules.scheduling.contracts import ProposalSlot, SchedulingProposalView

NOW = datetime(2026, 8, 27, 10, tzinfo=UTC)
CURRENT = uuid4()
OLDER = uuid4()


class Retrieval:
    def __init__(self) -> None:
        self.calls = 0

    async def retrieve(self, query: str, filters: object, limit: int) -> tuple[RetrievedChunk, ...]:
        self.calls += 1
        del query, filters, limit
        return (
            RetrievedChunk(
                uuid4(),
                "knowledge:1",
                "OWNER_NOTE",
                "v1",
                NOW - timedelta(days=2),
                "历史资料",
                None,
                0.5,
                0.1,
            ),
        )


@dataclass
class Scopes:
    before: datetime | None = None

    async def ensure_scope(
        self, user_id: str, conversation_key: str | None, event_key: str | None, now: datetime
    ) -> ContextScope:
        del user_id, conversation_key, event_key, now
        return ContextScope(None, None)

    async def attach_item(
        self, scope: ContextScope, inbox_item_id: UUID, occurred_at: datetime
    ) -> None:
        del scope, inbox_item_id, occurred_at

    async def list_item_ids(
        self, scope_id: UUID, scope_type: str, exclude_id: UUID, before: datetime, limit: int
    ) -> tuple[UUID, ...]:
        del scope_id, scope_type, exclude_id, limit
        self.before = before
        return (OLDER,)

    async def list_final_replies(
        self, scope_id: UUID, scope_type: str, before: datetime, limit: int
    ) -> tuple[ScopedAgentReply, ...]:
        del scope_id, scope_type, limit
        self.before = before
        return (ScopedAgentReply(uuid4(), "请说明要修改哪一项日程。", NOW - timedelta(minutes=1)),)


class Inbox:
    async def get_content(self, inbox_item_id: UUID) -> InboxContentView | None:
        if inbox_item_id != OLDER:
            return None
        return InboxContentView(
            OLDER,
            "旧消息",
            "把项目会议改到明天",
            None,
            "text/plain",
            NOW - timedelta(minutes=2),
            "qq:older",
            "sha256:old",
            None,
        )


class Conversation:
    def __init__(self) -> None:
        self.calls = 0

    async def list_recent_conversation(
        self, user_id: str, before: datetime, exclude_id: UUID, limit: int = 8
    ) -> tuple[ConversationContextItem, ...]:
        assert user_id == "owner"
        assert before == NOW
        assert exclude_id == CURRENT
        assert limit == 8
        self.calls += 1
        return (
            ConversationContextItem(
                "QQ_DIRECT",
                NOW - timedelta(minutes=3),
                "旧消息",
                "全局会话回退",
                "qq:global",
            ),
        )


@dataclass
class EmptyScopes(Scopes):
    async def list_item_ids(
        self, scope_id: UUID, scope_type: str, exclude_id: UUID, before: datetime, limit: int
    ) -> tuple[UUID, ...]:
        del scope_id, scope_type, exclude_id, limit
        self.before = before
        return ()

    async def list_final_replies(
        self, scope_id: UUID, scope_type: str, before: datetime, limit: int
    ) -> tuple[ScopedAgentReply, ...]:
        del scope_id, scope_type, limit
        self.before = before
        return ()


class FailingScopes(EmptyScopes):
    async def list_item_ids(
        self, scope_id: UUID, scope_type: str, exclude_id: UUID, before: datetime, limit: int
    ) -> tuple[UUID, ...]:
        del scope_id, scope_type, exclude_id, before, limit
        raise RuntimeError("scope unavailable")


class Agenda:
    async def list_active(
        self, range_start: datetime, range_end: datetime
    ) -> tuple[AgendaNotificationItem, ...]:
        assert range_start == NOW - timedelta(days=1)
        assert range_end == NOW + timedelta(days=90)
        return (
            AgendaNotificationItem(
                uuid4(),
                3,
                "项目会议",
                NOW + timedelta(days=1),
                NOW + timedelta(days=1, hours=1),
                "EVENT",
            ),
        )

    async def get_items(self, entry_ids: tuple[UUID, ...]) -> tuple[AgendaNotificationItem, ...]:
        del entry_ids
        return ()

    async def list_conflicts(
        self, range_start: datetime, range_end: datetime
    ) -> tuple[AgendaConflictView, ...]:
        del range_start, range_end
        return ()


class Proposals:
    async def list_pending(self, limit: int) -> tuple[SchedulingProposalView, ...]:
        assert limit == 8
        return (
            SchedulingProposalView(
                uuid4(),
                2,
                "owner",
                uuid4(),
                "TASK",
                "整理周报",
                ProposalSlot(NOW + timedelta(days=1), NOW + timedelta(days=1, hours=1), "UTC"),
                (),
                (),
                "",
                (),
                (),
                NOW + timedelta(hours=4),
                "PENDING_CONFIRMATION",
            ),
        )


class OwnerAliases:
    async def list_owner_group_aliases(self, user_id: str) -> tuple[OwnerGroupAlias, ...]:
        assert user_id == "owner"
        return (OwnerGroupAlias("风拾一"),)


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["", "  \t\n"])
async def test_context_skips_retrieval_for_blank_message(message: str) -> None:
    retrieval = Retrieval()
    context = await AgentContextAssembler(retrieval).build("owner", message)

    assert retrieval.calls == 0
    assert "[knowledge T2]" not in context
    assert "[stage-state]" in context


def test_context_rejects_history_limit_above_80() -> None:
    with pytest.raises(ValueError, match="source limits"):
        AgentContextAssembler(Retrieval(), history_limit=81)


@pytest.mark.asyncio
async def test_context_uses_prior_scope_only_and_includes_agent_calendar_facts() -> None:
    scopes = Scopes()
    context = await AgentContextAssembler(
        Retrieval(), None, scopes, Inbox(), Agenda(), Proposals(), owner_aliases=OwnerAliases()
    ).build(
        "owner",
        "刚才那个任务改到明天",
        before=NOW,
        exclude_id=CURRENT,
        conversation_id=uuid4(),
    )

    assert scopes.before == NOW
    assert "[scoped-context] qq:older" in context
    assert "[prior-agent-response]" in context
    assert "[agenda-fact]" in context and "version=3" in context
    assert "[pending-proposal]" in context
    assert "[knowledge T2] knowledge:1" in context
    assert "[owner-identity]" in context and "风拾一" in context
    assert "2026-08-28T18:00:00+08:00" in context


@pytest.mark.asyncio
async def test_context_without_scope_ids_uses_conversation_fallback() -> None:
    conversation = Conversation()
    context = await AgentContextAssembler(Retrieval(), conversation, Scopes(), Inbox()).build(
        "owner", "继续", before=NOW, exclude_id=CURRENT
    )

    assert conversation.calls == 1
    assert "[conversation] qq:global" in context
    assert "全局会话回退" in context


@pytest.mark.asyncio
async def test_context_empty_scope_uses_conversation_fallback() -> None:
    conversation = Conversation()
    scopes = EmptyScopes()
    context = await AgentContextAssembler(Retrieval(), conversation, scopes, Inbox()).build(
        "owner",
        "继续",
        before=NOW,
        exclude_id=CURRENT,
        conversation_id=uuid4(),
    )

    assert scopes.before == NOW
    assert conversation.calls == 1
    assert "[conversation] qq:global" in context


@pytest.mark.asyncio
async def test_context_nonempty_scope_does_not_mix_conversation_fallback() -> None:
    conversation = Conversation()
    context = await AgentContextAssembler(Retrieval(), conversation, Scopes(), Inbox()).build(
        "owner",
        "继续",
        before=NOW,
        exclude_id=CURRENT,
        conversation_id=uuid4(),
    )

    assert conversation.calls == 0
    assert "[scoped-context] qq:older" in context
    assert "qq:global" not in context


@pytest.mark.asyncio
async def test_context_propagates_scope_repository_failure() -> None:
    conversation = Conversation()
    with pytest.raises(RuntimeError, match="scope unavailable"):
        await AgentContextAssembler(Retrieval(), conversation, FailingScopes(), Inbox()).build(
            "owner",
            "继续",
            before=NOW,
            exclude_id=CURRENT,
            conversation_id=uuid4(),
        )
    assert conversation.calls == 0
