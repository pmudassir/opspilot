from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

DB_CONNECT_TIMEOUT_SECONDS = 5

# One engine (connection pool) per process, shared by all requests.
engine = create_async_engine(
    str(get_settings().database_url),
    pool_pre_ping=True,
    connect_args={"timeout": DB_CONNECT_TIMEOUT_SECONDS},
)

# expire_on_commit=False: after commit, attributes stay loaded instead of being
# lazily refreshed — lazy loading is not allowed with async sessions.
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """One session (unit of work) per HTTP request; always closed afterwards."""
    async with SessionFactory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
