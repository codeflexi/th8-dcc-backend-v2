# app/bootstrap.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.middleware import RequestLoggingMiddleware
from app.api.router import api_router


def create_app() -> FastAPI:
    setup_logging()

    app = FastAPI(title=settings.app_name)

    # -------------------------
    # Middleware
    # -------------------------
    app.add_middleware(RequestLoggingMiddleware)

    origins = [o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins if origins else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

 
    # -------------------------
    # Routers
    # -------------------------
    app.include_router(api_router, prefix=settings.api_prefix)

    # -------------------------
    # Health
    # -------------------------
    @app.get("/health/live", tags=["health"])
    def live():
        return {"status": "alive"}

    @app.get("/health/ready", tags=["health"])
    def ready():
        ready = getattr(app.state, "audit_repo", None) is not None
        return {"status": "ready" if ready else "degraded"}

    # -------------------------
    # Root
    # -------------------------
    @app.get("/", tags=["root"])
    def root():
        return {
            "status": "ok",
            "service": "TH8 Backend",
            "api_prefix": settings.api_prefix,
            "mode": "decision-run-on-demand",
        }

    return app
