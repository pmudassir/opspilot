from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.ai.assistant.router import router as assistant_router
from app.ai.proposals.router import router as proposals_router
from app.ai.router import router as ai_router
from app.auth.router import router as auth_router
from app.comments.router import router as comments_router
from app.csrf import reject_cross_origin_writes
from app.db import engine
from app.departments.router import router as departments_router
from app.errors import register_error_handlers
from app.health import router as health_router
from app.metrics.router import router as metrics_router
from app.organizations.router import router as organizations_router
from app.requests.router import router as requests_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="OpsPilot API", version="0.1.0", lifespan=lifespan)
    app.middleware("http")(reject_cross_origin_writes)
    register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(organizations_router)
    app.include_router(departments_router)
    app.include_router(requests_router)
    app.include_router(comments_router)
    app.include_router(metrics_router)
    app.include_router(ai_router)
    app.include_router(assistant_router)
    app.include_router(proposals_router)
    return app


app = create_app()
