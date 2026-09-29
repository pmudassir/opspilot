import os

# Must run before `app` is imported: settings are read at import time.
DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://opspilot:opspilot@localhost:5432/opspilot_test"
)
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
os.environ["ENVIRONMENT"] = "test"

from collections.abc import AsyncIterator, Callable, Iterator  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import make_url, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.db import SessionFactory, engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Base  # noqa: E402

# Tests wipe tables. Refuse to run against anything that isn't clearly a test database.
if not (make_url(os.environ["DATABASE_URL"]).database or "").endswith("_test"):
    raise RuntimeError("Refusing to run tests: DATABASE_URL must point at a *_test database")

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


@pytest.fixture(scope="session")
def alembic_config() -> Config:
    return Config(str(ALEMBIC_INI))


@pytest.fixture(scope="session", autouse=True)
def migrated_database(alembic_config: Config) -> Iterator[None]:
    """Build the test schema from migrations — the same path production uses.

    Downgrading first also exercises every downgrade() on each run.
    """
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    yield


@pytest.fixture(autouse=True)
async def clean_tables() -> AsyncIterator[None]:
    """Each test starts from empty tables. Real commits, no rollback tricks."""
    yield
    table_names = ", ".join(table.name for table in Base.metadata.sorted_tables)
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {table_names} CASCADE"))


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


DEFAULT_CLIENT_IP = "127.0.0.1"


@pytest.fixture
async def make_client(app: FastAPI) -> AsyncIterator[Callable[..., AsyncClient]]:
    """Independent clients = independent cookie jars = independent browsers/users.
    `ip` sets the caller's address (for throttling tests)."""
    clients: list[AsyncClient] = []

    def factory(ip: str = DEFAULT_CLIENT_IP) -> AsyncClient:
        transport = ASGITransport(app=app, client=(ip, 50000))
        new_client = AsyncClient(transport=transport, base_url="http://test")
        clients.append(new_client)
        return new_client

    yield factory
    for opened in clients:
        await opened.aclose()
