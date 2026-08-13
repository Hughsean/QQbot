"""Poll pending Proposals and idempotently deliver QQ confirmation cards."""

import logging

from qq_time_agent.modules.notifications.contracts import NotificationPort
from qq_time_agent.modules.scheduling.contracts import SchedulingPort

LOGGER = logging.getLogger(__name__)


class ProposalNotificationWorker:
    def __init__(self, scheduling: SchedulingPort, notifications: NotificationPort) -> None:
        self._scheduling = scheduling
        self._notifications = notifications

    async def run_once(self) -> int:
        sent = 0
        for proposal in await self._scheduling.list_pending(20):
            try:
                await self._notifications.send_confirmation("owner", proposal)
            except Exception as exc:
                LOGGER.warning(
                    "Proposal confirmation delivery failed",
                    extra={
                        "proposal_id": str(proposal.proposal_id),
                        "failure_class": type(exc).__name__,
                    },
                )
                continue
            else:
                sent += 1
        return sent
