from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.modules.audit.application.service import AuditService
from qq_time_agent.modules.audit.infrastructure.repository import SqlAuditRepository
from qq_time_agent.modules.audit.infrastructure.tables import AuditEventRow
from qq_time_agent.modules.data_lifecycle.application.coordinator import DeletionCoordinator
from qq_time_agent.modules.data_lifecycle.infrastructure.repository import SqlTombstoneRepository
from qq_time_agent.modules.data_lifecycle.infrastructure.tables import PurgeResultRow, TombstoneRow
from qq_time_agent.modules.inbox.infrastructure.purge import InboxPurgeAdapter
from qq_time_agent.modules.inbox.infrastructure.tables import InboxItemRow, InboxRawContentRow
from qq_time_agent.modules.knowledge.application.ports import IndexedChunk, IndexedSource
from qq_time_agent.modules.knowledge.infrastructure.purge import KnowledgePurgeAdapter
from qq_time_agent.modules.knowledge.infrastructure.repository import SqlKnowledgeRepository
from qq_time_agent.modules.knowledge.infrastructure.tables import KnowledgeSourceRow
from qq_time_agent.modules.normalization.infrastructure.purge import NormalizationPurgeAdapter
from qq_time_agent.modules.normalization.infrastructure.tables import NormalizedContentRow
from qq_time_agent.modules.scheduling.domain.models import SchedulingProposal
from qq_time_agent.modules.scheduling.infrastructure.purge import SchedulingPurgeAdapter
from qq_time_agent.modules.scheduling.infrastructure.repository import SqlProposalRepository
from qq_time_agent.modules.scheduling.infrastructure.tables import ProposalRow
from qq_time_agent.modules.understanding.contracts import CandidateKind
from qq_time_agent.modules.understanding.domain.candidates import Candidate
from qq_time_agent.modules.understanding.infrastructure.purge import UnderstandingPurgeAdapter
from qq_time_agent.modules.understanding.infrastructure.repository import SqlCandidateRepository
from qq_time_agent.modules.understanding.infrastructure.tables import CandidateRow
from qq_time_agent.modules.workflow.application.ports import WorkflowCheckpoint
from qq_time_agent.modules.workflow.infrastructure.purge import WorkflowPurgeAdapter
from qq_time_agent.modules.workflow.infrastructure.repository import SqlWorkflowCheckpointRepository
from qq_time_agent.modules.workflow.infrastructure.tables import UnderstandingCheckpointRow

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    value = create_database_engine(load_runtime_config().database)
    yield value
    await value.dispose()


class Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


async def test_tombstone_replay_removes_content_restored_from_old_backup(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 20, tzinfo=UTC)
    clock = Clock(now)
    connection_id = uuid4()
    external_id = f"restore-{uuid4()}"
    source_ref = f"qq-mail:{connection_id}:{external_id}"
    knowledge = SqlKnowledgeRepository(sessions)
    coordinator = DeletionCoordinator(
        SqlTombstoneRepository(sessions, clock),
        (
            SchedulingPurgeAdapter(sessions),
            UnderstandingPurgeAdapter(sessions),
            WorkflowPurgeAdapter(sessions),
            KnowledgePurgeAdapter(knowledge),
            NormalizationPurgeAdapter(sessions),
            InboxPurgeAdapter(sessions),
        ),
        clock,
        timedelta(hours=24),
        AuditService(SqlAuditRepository(sessions)),
    )
    tombstone = None
    try:
        await _restore_source(sessions, knowledge, source_ref, connection_id, external_id, now)
        tombstone = await coordinator.record_deletion(source_ref)
        await _assert_absent(sessions, source_ref)

        await _restore_source(sessions, knowledge, source_ref, connection_id, external_id, now)
        assert await _counts(sessions, source_ref) == (1, 1, 1, 1, 1, 1)
        assert await coordinator.replay() >= 1
        await _assert_absent(sessions, source_ref)
    finally:
        await SchedulingPurgeAdapter(sessions).purge_subject(source_ref, uuid4())
        await UnderstandingPurgeAdapter(sessions).purge_subject(source_ref, uuid4())
        await WorkflowPurgeAdapter(sessions).purge_subject(source_ref, uuid4())
        await KnowledgePurgeAdapter(knowledge).purge_subject(source_ref, uuid4())
        await NormalizationPurgeAdapter(sessions).purge_subject(source_ref, uuid4())
        await InboxPurgeAdapter(sessions).purge_subject(source_ref, uuid4())
        async with sessions.begin() as session:
            if tombstone is not None:
                await session.execute(
                    delete(PurgeResultRow).where(
                        PurgeResultRow.tombstone_id == tombstone.tombstone_id
                    )
                )
                await session.execute(
                    delete(TombstoneRow).where(TombstoneRow.tombstone_id == tombstone.tombstone_id)
                )
            await session.execute(
                delete(AuditEventRow).where(AuditEventRow.subject_ref == source_ref)
            )


async def _restore_source(
    sessions: async_sessionmaker[AsyncSession],
    knowledge: SqlKnowledgeRepository,
    source_ref: str,
    connection_id: UUID,
    external_id: str,
    now: datetime,
) -> None:
    raw_id = uuid4()
    item_id = uuid4()
    async with sessions.begin() as session:
        session.add(
            InboxRawContentRow(
                raw_content_id=raw_id,
                subject="合成恢复资料",
                body_text="已删除内容",
                body_html=None,
                mime_type="text/plain",
                recipients=[],
                internet_message_id=None,
                change_key=None,
                has_attachments=False,
                created_at=now,
            )
        )
        session.add(
            InboxItemRow(
                inbox_item_id=item_id,
                connection_id=connection_id,
                user_id="owner",
                source_type="QQ_MAIL",
                ingress_type="SYNC",
                trust_level="T2",
                external_id=external_id,
                thread_id=None,
                sender_id="synthetic@example.test",
                sender_display=None,
                occurred_at=now,
                received_at=now,
                raw_content_ref=raw_id,
                content_hash="synthetic-hash",
                status="COMPLETED",
                failure_class=None,
                retry_count=0,
                version=1,
                deleted_at=None,
            )
        )
        session.add(
            NormalizedContentRow(
                inbox_item_id=item_id,
                subject="合成恢复资料",
                body="已删除内容",
                source_hash="synthetic-hash",
                normalizer_version="v1",
                source_ref=source_ref,
            )
        )
    candidate = await SqlCandidateRepository(sessions).add(
        Candidate.create(
            item_id,
            CandidateKind.TASK,
            "恢复后待办",
            None,
            None,
            now + timedelta(days=1),
            "Asia/Shanghai",
            None,
            (),
            30,
            "MEDIUM",
            (),
            0.95,
            (),
            ("已删除内容",),
            (source_ref,),
        )
    )
    await SqlProposalRepository(sessions).add(
        SchedulingProposal.create(
            "owner",
            candidate.candidate_id,
            "TASK",
            "恢复后待办",
            None,
            (),
            (),
            "根据恢复内容生成",
            (),
            (source_ref,),
            now + timedelta(hours=1),
            {},
        )
    )
    await SqlWorkflowCheckpointRepository(sessions).save(
        WorkflowCheckpoint(
            item_id,
            "COMPLETED",
            "TASK",
            candidate.candidate_id,
            0.95,
            None,
            1,
            1,
            source_ref,
        )
    )
    vector = (1.0,) + (0.0,) * 1023
    await knowledge.replace_active(
        IndexedSource(
            uuid4(),
            source_ref,
            "QQ_MAIL",
            "v1",
            now,
            "T2",
            {},
            "v1",
            "restore-v1",
            "model",
            "digest",
            1024,
            (IndexedChunk(uuid4(), 0, "已删除内容", "hash", vector),),
        )
    )


async def _assert_absent(sessions: async_sessionmaker[AsyncSession], source_ref: str) -> None:
    assert await _counts(sessions, source_ref) == (0, 0, 0, 0, 0, 0)


async def _counts(
    sessions: async_sessionmaker[AsyncSession], source_ref: str
) -> tuple[int, int, int, int, int, int]:
    _, connection_text, external_id = source_ref.split(":", 2)
    connection_id = UUID(connection_text)
    async with sessions() as session:
        knowledge_count = await session.scalar(
            select(func.count())
            .select_from(KnowledgeSourceRow)
            .where(KnowledgeSourceRow.source_ref == source_ref)
        )
        normalized_count = await session.scalar(
            select(func.count())
            .select_from(NormalizedContentRow)
            .where(NormalizedContentRow.source_ref == source_ref)
        )
        inbox_count = await session.scalar(
            select(func.count())
            .select_from(InboxItemRow)
            .where(
                InboxItemRow.connection_id == connection_id,
                InboxItemRow.external_id == external_id,
            )
        )
        candidate_count = await session.scalar(
            select(func.count())
            .select_from(CandidateRow)
            .where(CandidateRow.source_ref == source_ref)
        )
        proposal_count = await session.scalar(
            select(func.count())
            .select_from(ProposalRow)
            .where(ProposalRow.source_ref == source_ref)
        )
        checkpoint_count = await session.scalar(
            select(func.count())
            .select_from(UnderstandingCheckpointRow)
            .where(UnderstandingCheckpointRow.source_ref == source_ref)
        )
    return (
        int(knowledge_count or 0),
        int(normalized_count or 0),
        int(inbox_count or 0),
        int(candidate_count or 0),
        int(proposal_count or 0),
        int(checkpoint_count or 0),
    )
