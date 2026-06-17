from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.core.logger import configure_logging
from app.core.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    # Perform startup tasks here
    configure_logging(settings)
    yield
    # Perform shutdown tasks here


def create_application() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        description=f"API for {settings.app_name}",
        version="1.0.0",
        docs_url="/swagger-ui",
        lifespan=lifespan,
    )
    application.include_router(api_router)
    return application


app = create_application()
