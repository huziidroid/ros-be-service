import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.middleware import SlowAPIMiddleware

from app.api.exception_handlers import register_exception_handlers
from app.api.router import api_router
from app.core.logger import configure_logging
from app.core.rate_limit import limiter
from app.core.settings import settings


# Configure before app creation so import-time logs use the correct config
configure_logging(settings)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    # --- Startup ---
    from app.clients.temporal import connect_temporal
    from app.core.database import engine

    app.state.temporal = await connect_temporal()

    yield

    # --- Shutdown ---
    from app.clients.redis import redis_client

    await engine.dispose()
    await redis_client.close()
    # No explicit Temporal client close; worker shutdown is handled by app/worker.py.


def create_application() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        description=(
            "WhatsApp-native AI business OS for B2B wholesale distributors.\n\n"
            "**Docs:** `/swagger-ui` (Swagger) · `/redoc` (ReDoc)"
        ),
        version="1.0.0",
        docs_url="/swagger-ui",
        swagger_ui_parameters={
            "defaultModelsExpandDepth": -1,
            "displayRequestDuration": True,
            "filter": True,
            "persistAuthorization": True,
        },
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    application.state.limiter = limiter
    register_exception_handlers(application)
    application.add_middleware(SlowAPIMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(api_router)
    return application


app = create_application()
