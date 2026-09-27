from collections.abc import AsyncIterator

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import get_session

# Nothing listens on port 1, so connecting fails for real (connection refused).
UNREACHABLE_DATABASE_URL = "postgresql+asyncpg://localhost:1/unreachable"


async def test_health_reports_ok_when_database_is_reachable(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


async def test_health_returns_503_when_database_is_unreachable(
    app: FastAPI, client: AsyncClient
) -> None:
    broken_engine = create_async_engine(UNREACHABLE_DATABASE_URL, connect_args={"timeout": 1})
    broken_sessions = async_sessionmaker(broken_engine)

    async def unreachable_session() -> AsyncIterator[AsyncSession]:
        async with broken_sessions() as session:
            yield session

    app.dependency_overrides[get_session] = unreachable_session
    try:
        response = await client.get("/health")
    finally:
        await broken_engine.dispose()

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unreachable"}
