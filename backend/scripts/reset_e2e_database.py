"""Create (if missing), migrate and empty the end-to-end test database.

Usage (from backend/): DATABASE_URL=...opspilot_e2e uv run python -m scripts.reset_e2e_database
Refuses to touch any database whose name doesn't end in `_e2e`.
"""

import asyncio
import os
import re
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import URL, make_url, text
from sqlalchemy.ext.asyncio import create_async_engine

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
SAFE_NAME = re.compile(r"^[a-z0-9_]+_e2e$")


async def create_database_if_missing(url: URL) -> None:
    # CREATE DATABASE can't run inside a transaction, hence AUTOCOMMIT on the maintenance DB.
    engine = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            exists = await connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database}
            )
            if not exists:
                await connection.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        await engine.dispose()


async def truncate_all_tables(url: URL) -> None:
    from app.models import Base

    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
            await connection.execute(text(f"TRUNCATE {tables} CASCADE"))
    finally:
        await engine.dispose()


def main() -> None:
    url = make_url(os.environ["DATABASE_URL"])
    if not SAFE_NAME.match(url.database or ""):
        sys.exit(f"Refusing to reset {url.database!r}: expected a database named *_e2e")
    asyncio.run(create_database_if_missing(url))
    command.upgrade(Config(str(ALEMBIC_INI)), "head")
    asyncio.run(truncate_all_tables(url))
    print(f"E2E database {url.database!r} ready (migrated, empty).")


if __name__ == "__main__":
    main()
