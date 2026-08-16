"""PostgreSQL connection lifecycle repository with one-time OAuth claims."""

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.connections.domain.models import (
    ConnectionProvider,
    ConnectionStatus,
    ExternalConnection,
    OAuthTransaction,
)
from qq_time_agent.modules.connections.infrastructure.tables import (
    ConnectionRow,
    OAuthTransactionRow,
)


class SqlConnectionRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def add(self, connection: ExternalConnection) -> None:
        async with self._sessions.begin() as session:
            session.add(ConnectionRow(**_connection_values(connection)))

    async def add_authorization(
        self, connection: ExternalConnection, transaction: OAuthTransaction
    ) -> None:
        values = _connection_values(connection)
        statement = (
            insert(ConnectionRow)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[ConnectionRow.connection_id],
                set_={
                    "status": connection.status.value,
                    "version": connection.version,
                    "sync_enabled": connection.sync_enabled,
                },
            )
        )
        async with self._sessions.begin() as session:
            await session.execute(statement)
            session.add(_transaction_row(transaction))

    async def claim_transaction(
        self, state_hash: bytes, browser_hash: bytes, now: datetime
    ) -> OAuthTransaction | None:
        async with self._sessions.begin() as session:
            row = await session.scalar(
                select(OAuthTransactionRow)
                .where(
                    OAuthTransactionRow.state_hash == state_hash,
                    OAuthTransactionRow.browser_session_hash == browser_hash,
                    OAuthTransactionRow.consumed_at.is_(None),
                    OAuthTransactionRow.expires_at > now,
                )
                .with_for_update()
            )
            if row is None:
                return None
            transaction = _to_transaction(row)
            transaction.claim(state_hash, browser_hash, now)
            row.consumed_at = transaction.consumed_at
            return transaction

    async def get(self, connection_id: UUID) -> ExternalConnection | None:
        async with self._sessions() as session:
            row = await session.get(ConnectionRow, connection_id)
            return None if row is None else _to_connection(row)

    async def get_for_provider(self, user_id: str, provider: str) -> ExternalConnection | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(ConnectionRow).where(
                    ConnectionRow.user_id == user_id, ConnectionRow.provider == provider
                )
            )
            return None if row is None else _to_connection(row)

    async def list_for_provider(
        self, user_id: str, provider: str
    ) -> tuple[ExternalConnection, ...]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(ConnectionRow)
                .where(ConnectionRow.user_id == user_id, ConnectionRow.provider == provider)
                .order_by(
                    ConnectionRow.is_default.desc(),
                    ConnectionRow.status.asc(),
                    ConnectionRow.connection_id,
                )
            )
            return tuple(_to_connection(row) for row in rows)

    async def get_for_user(self, connection_id: UUID, user_id: str) -> ExternalConnection | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(ConnectionRow).where(
                    ConnectionRow.connection_id == connection_id,
                    ConnectionRow.user_id == user_id,
                )
            )
            return None if row is None else _to_connection(row)

    async def get_by_identity(
        self, user_id: str, provider: str, fingerprint: str
    ) -> ExternalConnection | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(ConnectionRow).where(
                    ConnectionRow.user_id == user_id,
                    ConnectionRow.provider == provider,
                    ConnectionRow.account_fingerprint == fingerprint,
                    ConnectionRow.status != ConnectionStatus.DISCONNECTED.value,
                )
            )
            return None if row is None else _to_connection(row)

    async def save(self, connection: ExternalConnection, expected_version: int) -> None:
        values = _connection_values(connection)
        values.pop("connection_id")
        async with self._sessions.begin() as session:
            result = await session.execute(
                update(ConnectionRow)
                .where(
                    ConnectionRow.connection_id == connection.connection_id,
                    ConnectionRow.version == expected_version,
                )
                .values(**values)
            )
            cursor = cast("CursorResult[tuple[()]]", result)
            if cursor.rowcount != 1:
                raise RuntimeError("connection version conflict")


def _connection_values(connection: ExternalConnection) -> dict[str, object]:
    return {
        "connection_id": connection.connection_id,
        "user_id": connection.user_id,
        "provider": connection.provider.value,
        "status": connection.status.value,
        "provider_account_id": connection.provider_account_id,
        "account_mask": connection.account_mask,
        "account_fingerprint": connection.account_fingerprint,
        "display_label": connection.display_label,
        "is_default": connection.is_default,
        "sync_enabled": connection.sync_enabled,
        "capabilities": sorted(connection.capabilities),
        "credential_ref": connection.credential_ref,
        "last_synced_at": connection.last_synced_at,
        "reauth_epoch": connection.reauth_epoch,
        "reauth_required_since": connection.reauth_required_since,
        "version": connection.version,
    }


def _transaction_row(value: OAuthTransaction) -> OAuthTransactionRow:
    return OAuthTransactionRow(
        transaction_id=value.transaction_id,
        connection_id=value.connection_id,
        user_id=value.user_id,
        state_hash=value.state_hash,
        browser_session_hash=value.browser_session_hash,
        flow_credential_ref=value.flow_credential_ref,
        expires_at=value.expires_at,
        created_at=value.created_at,
        consumed_at=value.consumed_at,
    )


def _to_connection(row: ConnectionRow) -> ExternalConnection:
    return ExternalConnection(
        connection_id=row.connection_id,
        user_id=row.user_id,
        provider=ConnectionProvider(row.provider),
        status=ConnectionStatus(row.status),
        provider_account_id=row.provider_account_id,
        account_mask=row.account_mask,
        capabilities=frozenset(row.capabilities),
        credential_ref=row.credential_ref,
        last_synced_at=row.last_synced_at,
        version=row.version,
        account_fingerprint=row.account_fingerprint,
        display_label=row.display_label,
        is_default=row.is_default,
        sync_enabled=row.sync_enabled,
        reauth_epoch=row.reauth_epoch,
        reauth_required_since=row.reauth_required_since,
    )


def _to_transaction(row: OAuthTransactionRow) -> OAuthTransaction:
    return OAuthTransaction(
        row.transaction_id,
        row.connection_id,
        row.user_id,
        row.state_hash,
        row.browser_session_hash,
        row.flow_credential_ref,
        row.expires_at,
        row.created_at,
        row.consumed_at,
    )
