"""Public Inbox contracts."""

from qq_time_agent.modules.inbox.contracts.models import (
    InboxContentPort,
    InboxContentView,
    InboxKnowledgeQueryPort,
    InboxProcessingPort,
    InboxProcessingQueryPort,
    InboxSourcePort,
    InboxSourceView,
    IngestResult,
    MailAddress,
    MailChange,
    MailDeltaPage,
    MailProvider,
    MailProviderError,
    MailSyncResult,
    QqInboxPort,
)

__all__ = [
    "InboxContentPort",
    "InboxContentView",
    "InboxKnowledgeQueryPort",
    "InboxProcessingPort",
    "InboxProcessingQueryPort",
    "InboxSourcePort",
    "InboxSourceView",
    "IngestResult",
    "MailAddress",
    "MailChange",
    "MailDeltaPage",
    "MailProvider",
    "MailProviderError",
    "MailSyncResult",
    "QqInboxPort",
]
