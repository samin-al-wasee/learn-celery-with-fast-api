import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

T = TypeVar("T")


def run_db(fn: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """Run an async DB unit of work from a sync Celery task."""

    async def main() -> T:
        # M3: asyncpg connections are bound to the event loop that opened them, and each
        # asyncio.run() is a new loop, so a pooled engine shared across tasks breaks.
        # NullPool + a per-call engine keeps every connection inside its own loop.
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await fn(session)
        finally:
            await engine.dispose()

    return asyncio.run(main())
