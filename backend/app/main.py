from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.auth.router import router as auth_router
from app.csrf import reject_cross_origin_writes
from app.db import engine
from app.health import router as health_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="OpsPilot API", version="0.1.0", lifespan=lifespan)
    app.middleware("http")(reject_cross_origin_writes)
    app.include_router(health_router)
    app.include_router(auth_router)
    return app


app = create_app()
