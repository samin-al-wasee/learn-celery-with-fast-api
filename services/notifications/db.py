import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

T = TypeVar("T")


class Base(DeclarativeBase):
    """The notifications service's own metadata: nothing here references the monolith's tables."""


_engine = None


def _sessions() -> async_sessionmaker[AsyncSession]:
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_settings().notifications_database_url, pool_pre_ping=True)
    return async_sessionmaker(_engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with _sessions()() as session:
        yield session


def run_db(fn: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """Run one unit of work from sync code (the pika consumer); per-call engine, see app/worker/db.py."""

    async def main() -> T:
        engine = create_async_engine(get_settings().notifications_database_url, poolclass=NullPool)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await fn(session)
        finally:
            await engine.dispose()

    return asyncio.run(main())
