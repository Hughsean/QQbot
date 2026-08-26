from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qq_time_agent.modules.agenda.contracts import AgendaConflictView, AgendaNotificationItem
from qq_time_agent.modules.agent.application.context import AgentContextAssembler
from qq_time_agent.modules.agent.contracts import ContextScope, ScopedAgentReply
from qq_time_agent.modules.inbox.contracts import InboxContentView
from qq_time_agent.modules.retrieval.contracts import RetrievedChunk
from qq_time_agent.modules.scheduling.contracts import ProposalSlot, SchedulingProposalView

NOW = datetime(2026, 8, 27, 10, tzinfo=UTC)
CURRENT = uuid4()
OLDER = uuid4()


class Retrieval:
    async def retrieve(self, query: str, filters: object, limit: int) -> tuple[RetrievedChunk, ...]:
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


@pytest.mark.asyncio
async def test_context_uses_prior_scope_only_and_includes_agent_calendar_facts() -> None:
    scopes = Scopes()
    context = await AgentContextAssembler(
        Retrieval(), None, scopes, Inbox(), Agenda(), Proposals()
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
