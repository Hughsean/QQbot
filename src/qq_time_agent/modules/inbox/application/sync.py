"""Bounded, restart-safe incremental mail synchronization."""

from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.contracts.source import SourceType
from qq_time_agent.modules.connections.contracts import ConnectionSyncPort
from qq_time_agent.modules.credentials.contracts import CredentialHandle
from qq_time_agent.modules.data_lifecycle.contracts import DeletionRequestPort
from qq_time_agent.modules.inbox.application.ports import InboxRepository
from qq_time_agent.modules.inbox.application.service import InboxService
from qq_time_agent.modules.inbox.contracts import (
    InboxSourceDeletedError,
    MailAttachmentMetadata,
    MailChange,
    MailProviderError,
    MailSyncProvider,
    MailSyncResult,
)
from qq_time_agent.modules.normalization.contracts import NormalizationPort

MAX_PAGES_PER_RUN = 100


class MailAssetDiscoveryPort(Protocol):
    async def discover(
        self,
        inbox_item_id: UUID,
        attachments: tuple[MailAttachmentMetadata, ...],
        now: datetime,
    ) -> tuple[UUID, ...]: ...


class AgentRunSchedulerPort(Protocol):
    async def schedule(self, inbox_item_id: UUID) -> None: ...


class MailSyncService:
    def __init__(
        self,
        connections: ConnectionSyncPort,
        inbox: InboxService,
        repository: InboxRepository,
        normalization: NormalizationPort,
        provider: MailSyncProvider,
        clock: Clock,
        lookback_days: int,
        deletion: DeletionRequestPort | None = None,
        source_type: SourceType = SourceType.MICROSOFT_MAIL,
        asset_discovery: MailAssetDiscoveryPort | None = None,
        agent_scheduler: AgentRunSchedulerPort | None = None,
    ) -> None:
        if lookback_days < 1:
            raise ValueError("mail lookback must be positive")
        self._connections = connections
        self._inbox = inbox
        self._repository = repository
        self._normalization = normalization
        self._provider = provider
        self._clock = clock
        self._lookback_days = lookback_days
        self._deletion = deletion
        self._source_type = source_type
        self._asset_discovery = asset_discovery
        self._agent_scheduler = agent_scheduler

    def set_agent_scheduler(self, scheduler: AgentRunSchedulerPort) -> None:
        self._agent_scheduler = scheduler

    async def synchronize(self, connection_id: UUID) -> MailSyncResult:
        try:
            return await self._run(connection_id)
        except MailProviderError as exc:
            if exc.failure_class == "Authentication":
                await self._connections.mark_sync_reauth_required(connection_id)
            elif exc.failure_class in {"TransientProvider", "RateLimit", "PageLimit"}:
                await self._connections.mark_sync_degraded(connection_id)
            raise

    async def _run(self, connection_id: UUID) -> MailSyncResult:
        grant = await self._connections.acquire_mail_access(connection_id)
        cursor = await self._repository.get_cursor(connection_id)
        since = self._clock.now() - timedelta(days=self._lookback_days)
        created = duplicates = deleted = pages = 0
        round_complete = False
        while pages < MAX_PAGES_PER_RUN:
            page = await self._provider.fetch_page(
                grant.mail_credential, grant.account_id, cursor, since
            )
            page_counts = await self._apply_page(
                connection_id, grant.user_id, grant.account_id, grant.mail_credential, page.changes
            )
            await self._connections.ensure_sync_available(connection_id)
            created += page_counts[0]
            duplicates += page_counts[1]
            deleted += page_counts[2]
            pages += 1
            await self._repository.save_cursor(
                connection_id, page.continuation_url, self._clock.now()
            )
            cursor = page.continuation_url
            round_complete = page.round_complete
            if round_complete:
                await self._connections.mark_sync_succeeded(connection_id, self._clock.now())
                break
        if not round_complete:
            raise MailProviderError("PageLimit")
        return MailSyncResult(created, duplicates, deleted, pages, True)

    async def _apply_page(
        self,
        connection_id: UUID,
        user_id: str,
        account_id: str,
        mail_credential: CredentialHandle,
        changes: tuple[MailChange, ...],
    ) -> tuple[int, int, int]:
        created = duplicates = deleted = 0
        for change in changes:
            if change.removed:
                existing = await self._repository.find_by_external(
                    connection_id, change.external_id
                )
                marked = await self._repository.mark_deleted(
                    connection_id, change.external_id, self._clock.now()
                )
                deleted += int(marked)
                if marked and existing is not None and existing.source_ref and self._deletion:
                    await self._deletion.record_deletion(existing.source_ref)
                continue
            existing = await self._repository.find_by_external(connection_id, change.external_id)
            if existing is not None:
                duplicates += 1
                if existing.status in {"RECEIVED", "FAILED_RETRYABLE"}:
                    complete_change = await self._provider.fetch_content(
                        mail_credential, account_id, change
                    )
                    await self._discover_assets(existing.inbox_item_id, complete_change)
                    await self._normalize_with_failure(existing.inbox_item_id)
                continue
            complete_change = await self._provider.fetch_content(
                mail_credential, account_id, change
            )
            try:
                result = await self._inbox.ingest_mail(
                    connection_id,
                    user_id,
                    complete_change,
                    self._clock.now(),
                    self._source_type,
                )
            except InboxSourceDeletedError:
                deleted += 1
                continue
            if not result.created:
                duplicates += 1
            await self._discover_assets(result.inbox_item_id, complete_change)
            if result.status not in {"RECEIVED", "FAILED_RETRYABLE"}:
                continue
            await self._normalize_with_failure(result.inbox_item_id)
            created += int(result.created)
        return created, duplicates, deleted

    async def _discover_assets(self, inbox_item_id: UUID, change: MailChange) -> None:
        if self._asset_discovery is not None and change.attachments:
            await self._asset_discovery.discover(
                inbox_item_id, change.attachments, self._clock.now()
            )

    async def _normalize_with_failure(self, inbox_item_id: UUID) -> None:
        try:
            await self._normalize(inbox_item_id)
        except Exception as exc:
            await self._inbox.mark_failed(inbox_item_id, type(exc).__name__, retryable=True)
            raise MailProviderError("Normalization") from exc

    async def _normalize(self, inbox_item_id: UUID) -> None:
        content = await self._inbox.content(inbox_item_id)
        if content is None:
            raise RuntimeError("new Inbox content is missing")
        await self._normalization.normalize(
            inbox_item_id,
            content.subject,
            content.body_text,
            content.body_html,
            content.content_hash,
            content.source_ref,
        )
        await self._inbox.mark_normalized(inbox_item_id)
        if self._agent_scheduler is not None:
            await self._agent_scheduler.schedule(inbox_item_id)
