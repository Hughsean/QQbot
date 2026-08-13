"""PostgreSQL Credential Vault repository."""

from uuid import UUID

from sqlalchemy import delete, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.credentials.application.ports import EncryptedCredential
from qq_time_agent.modules.credentials.contracts import CredentialKind
from qq_time_agent.modules.credentials.infrastructure.tables import CredentialRow


class SqlCredentialRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def add(self, credential: EncryptedCredential) -> None:
        async with self._sessions.begin() as session:
            session.add(
                CredentialRow(
                    credential_id=credential.credential_id,
                    kind=credential.kind.value,
                    key_version=credential.key_version,
                    nonce=credential.nonce,
                    ciphertext=credential.ciphertext,
                    created_at=credential.created_at,
                    expires_at=credential.expires_at,
                )
            )

    async def get(self, credential_id: UUID) -> EncryptedCredential | None:
        async with self._sessions() as session:
            row = await session.get(CredentialRow, credential_id)
            return None if row is None else _to_record(row)

    async def delete(self, credential_id: UUID) -> bool:
        async with self._sessions.begin() as session:
            result = await session.execute(
                delete(CredentialRow).where(CredentialRow.credential_id == credential_id)
            )
            return isinstance(result, CursorResult) and result.rowcount == 1

    async def replace(self, credential: EncryptedCredential) -> bool:
        async with self._sessions.begin() as session:
            result = await session.execute(
                update(CredentialRow)
                .where(CredentialRow.credential_id == credential.credential_id)
                .values(
                    key_version=credential.key_version,
                    nonce=credential.nonce,
                    ciphertext=credential.ciphertext,
                    created_at=credential.created_at,
                )
            )
            return isinstance(result, CursorResult) and result.rowcount == 1


def _to_record(row: CredentialRow) -> EncryptedCredential:
    return EncryptedCredential(
        credential_id=row.credential_id,
        kind=CredentialKind(row.kind),
        key_version=row.key_version,
        nonce=row.nonce,
        ciphertext=row.ciphertext,
        created_at=row.created_at,
        expires_at=row.expires_at,
    )
