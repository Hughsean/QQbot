"""Worker-only composition for deterministic calendar change ingestion."""

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.adapters.inbound.workers.calendar_changes import (
    CalendarChangeIngestJobHandler,
)
from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.agenda.contracts import AgendaSourceLookupPort
from qq_time_agent.modules.normalization.contracts import AssetNormalizationQueryPort
from qq_time_agent.modules.understanding.application.calendar_ingestion import (
    CalendarChangeIngestionService,
)
from qq_time_agent.modules.understanding.infrastructure.calendar_fingerprints import (
    HmacCalendarEventFingerprinter,
)
from qq_time_agent.modules.understanding.infrastructure.calendar_repository import (
    SqlCalendarChangeRepository,
)


def build_calendar_change_handler(
    sessions: async_sessionmaker[AsyncSession],
    assets: AssetNormalizationQueryPort,
    agenda: AgendaSourceLookupPort,
    fingerprint_key: SecretStr,
    clock: Clock,
) -> CalendarChangeIngestJobHandler:
    service = CalendarChangeIngestionService(
        SqlCalendarChangeRepository(sessions),
        HmacCalendarEventFingerprinter(fingerprint_key),
        agenda,
    )
    return CalendarChangeIngestJobHandler(assets, service, clock)
