"""Thin database job handler for incremental Microsoft mail sync."""

from uuid import UUID

from qq_time_agent.adapters.inbound.workers.runner import RetryableJobError
from qq_time_agent.contracts.jobs import JobLease
from qq_time_agent.modules.connections.application.ports import OAuthProviderError
from qq_time_agent.modules.connections.contracts import ConnectionUnavailableError
from qq_time_agent.modules.inbox.application.sync import MailSyncService
from qq_time_agent.modules.inbox.contracts import InboxSourceDeletedError, MailProviderError

RETRYABLE_FAILURES = {"TransientProvider", "RateLimit", "PageLimit", "Normalization"}


class MailSyncJobHandler:
    def __init__(self, service: MailSyncService) -> None:
        self._service = service

    async def __call__(self, job: JobLease) -> None:
        raw_id = job.payload.get("connection_id")
        if not isinstance(raw_id, str):
            raise ValueError("mail sync job connection_id is required")
        try:
            await self._service.synchronize(UUID(raw_id))
        except (ConnectionUnavailableError, InboxSourceDeletedError):
            return
        except (MailProviderError, OAuthProviderError) as exc:
            if exc.failure_class in RETRYABLE_FAILURES:
                raise RetryableJobError(exc.failure_class) from exc
            raise


MicrosoftMailSyncJobHandler = MailSyncJobHandler
