"""Alembic environment configured from the bootstrap Settings contract."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from qq_time_agent.adapters.outbound.persistence.database import database_url
from qq_time_agent.adapters.outbound.persistence.operations_tables import OperationsBase
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.modules.actions.infrastructure.tables import ActionsBase
from qq_time_agent.modules.agenda.infrastructure.tables import AgendaBase
from qq_time_agent.modules.ai_gateway.infrastructure.tables import AIGatewayBase
from qq_time_agent.modules.audit.infrastructure.tables import AuditBase
from qq_time_agent.modules.connections.infrastructure.tables import ConnectionsBase
from qq_time_agent.modules.credentials.infrastructure.tables import CredentialsBase
from qq_time_agent.modules.data_lifecycle.infrastructure.tables import LifecycleBase
from qq_time_agent.modules.identity.infrastructure.tables import IdentityBase
from qq_time_agent.modules.inbox.infrastructure.tables import InboxBase
from qq_time_agent.modules.knowledge.infrastructure.tables import KnowledgeBase
from qq_time_agent.modules.normalization.infrastructure.tables import NormalizationBase
from qq_time_agent.modules.notifications.infrastructure.tables import NotificationsBase
from qq_time_agent.modules.reminders.infrastructure.tables import RemindersBase
from qq_time_agent.modules.scheduling.infrastructure.tables import SchedulingBase
from qq_time_agent.modules.understanding.infrastructure.tables import UnderstandingBase
from qq_time_agent.modules.workflow.infrastructure.tables import WorkflowBase

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = [
    OperationsBase.metadata,
    LifecycleBase.metadata,
    CredentialsBase.metadata,
    ConnectionsBase.metadata,
    InboxBase.metadata,
    NormalizationBase.metadata,
    AIGatewayBase.metadata,
    UnderstandingBase.metadata,
    WorkflowBase.metadata,
    AgendaBase.metadata,
    AuditBase.metadata,
    SchedulingBase.metadata,
    IdentityBase.metadata,
    ActionsBase.metadata,
    RemindersBase.metadata,
    NotificationsBase.metadata,
    KnowledgeBase.metadata,
]


def run_migrations_offline() -> None:
    url = database_url(load_runtime_config().database).render_as_string(hide_password=False)
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = database_url(load_runtime_config().database).render_as_string(
        hide_password=False
    )
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
