from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: warm settings. Later — open the BigQuery client / connection pool here.
    get_settings()
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
