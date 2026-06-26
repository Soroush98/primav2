import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import get_settings

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: warm the agent so the OmniAnomaly checkpoint loads once here (not on the
    # first request). Guarded — if warmup fails (e.g. no creds in local dev), the agent
    # builds lazily on first use instead of blocking startup.
    get_settings()
    try:
        from app.agent.runtime import get_agent

        get_agent()
    except Exception:  # noqa: BLE001 — never block container startup on warmup
        log.warning("agent warmup skipped; will build on first request", exc_info=True)
    yield
    # Shutdown: close pools / clients here.


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="primav2", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
