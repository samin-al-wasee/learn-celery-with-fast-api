from collections.abc import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, echo=settings.debug, pool_pre_ping=True)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# NAIVE (deliberate, for the M1 lesson): a wholly synchronous engine using the
# psycopg driver. Sync drivers make real blocking system calls; this is what
# we wrongly drop inside async endpoints. See LEARNING.md.
_sync_url = settings.database_url.replace("+asyncpg", "+psycopg")
naive_sync_engine = create_engine(_sync_url, echo=settings.debug, pool_pre_ping=True)
naive_sync_session_factory = sessionmaker(naive_sync_engine, class_=Session, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session