"""Create the per-service databases on the shared Postgres server (idempotent).

Usage:  python scripts/setup_databases.py
Then:   alembic -c services/notifications/alembic.ini upgrade head
"""
import asyncio

import asyncpg

from app.core.config import get_settings


async def main() -> None:
    settings = get_settings()
    admin = await asyncpg.connect(settings.database_url.replace("postgresql+asyncpg://", "postgresql://"))
    try:
        # M6: one server, one database per service; no service reads another's tables.
        name = settings.notifications_database_url.rsplit("/", 1)[1]
        exists = await admin.fetchval("select 1 from pg_database where datname = $1", name)
        if not exists:
            await admin.execute(f'CREATE DATABASE "{name}"')
        print(f"database {name}: {'exists' if exists else 'created'}")
    finally:
        await admin.close()


if __name__ == "__main__":
    asyncio.run(main())
