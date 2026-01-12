# app/lifecycle.py
import logging
from fastapi import FastAPI

from app.dependencies import init_repositories

logger = logging.getLogger(__name__)


def register_lifecycle(app: FastAPI) -> None:
    @app.on_event("startup")
    def on_startup() -> None:
        logger.info("Application startup begin")
        init_repositories(app)
        logger.info("Application startup completed")

    @app.on_event("shutdown")
    def on_shutdown() -> None:
        logger.info("Application shutdown begin")

        # Close connections if needed in future
        # e.g. app.state.db.close()

        logger.info("Application shutdown completed")
