"""Database engine construction at the persistence boundary."""

from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from qq_time_agent.bootstrap.config_models import DatabaseConfig


def database_url(config: DatabaseConfig) -> URL:
    return URL.create(
        drivername="postgresql+psycopg",
        username=config.user,
        password=config.password.get_secret_value(),
        host=config.host,
        port=config.port,
        database=config.name,
    )


def create_database_engine(config: DatabaseConfig) -> AsyncEngine:
    return create_async_engine(
        database_url(config),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        hide_parameters=True,
    )
