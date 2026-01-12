from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dotenv import load_dotenv
load_dotenv()  # ต้องอยู่ก่อน import OpenAI / SDK ใด ๆ

from app.api.router import api_router
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.middleware import RequestLoggingMiddleware

from app.services.seed_data_loader import seed_demo_data
from app.services.orchestrator import DecisionOrchestrator

from app.repositories.supabase_repo import SupabaseCaseRepository
from app.repositories.supabase_audit_repo import SupabaseAuditRepository


def create_app() -> FastAPI:
    setup_logging()

    app = FastAPI(title=settings.app_name)

    # -------------------------------------------------
    # Middleware
    # -------------------------------------------------
    app.add_middleware(RequestLoggingMiddleware)

    origins = [o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins if origins else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -------------------------------------------------
    # Startup
    # -------------------------------------------------
    @app.on_event("startup")
    
    def startup_load_demo_data():
        # 1) init audit repo (ต้องมีเสมอ)
        app.state.audit_repo = SupabaseAuditRepository()
        app.state.case_repo = None

        try:
            case_repo = SupabaseCaseRepository()

            cases = case_repo.list_cases() or []

            for case in cases:
                case_repo.save_case(case)

                # CASE_LOADED audit (system-of-record)
                app.state.audit_repo.append_event(
                    case_id=case.get("case_id", ""),
                    event_type="CASE_LOADED",
                    actor="system",
                    payload={
                        "domain": case.get("domain"),
                        "status": case.get("status"),
                        "sources": case.get("sources", []),
                    },
                )

            app.state.case_repo = case_repo
            print("[startup] Supabase repositories initialized")
            print("[startup] cases loaded:", len(cases))

        except Exception as e:
            # case repo ล้มได้ แต่ audit ต้องอยู่
            app.state.case_repo = None
            print(f"[startup] Supabase init failed: {e}")

        # 2) Create Decision Orchestrator (run-on-demand)
        app.state.orchestrator = DecisionOrchestrator()
        print("[startup] DecisionOrchestrator ready")

    # -------------------------------------------------
    # Routers
    # -------------------------------------------------
    app.include_router(api_router, prefix=settings.api_prefix)

    # -------------------------------------------------
    # Root
    # -------------------------------------------------
    @app.get("/", tags=["root"])
    def root():
        return {
            "status": "ok",
            "service": "TH8 Backend",
            "api_prefix": settings.api_prefix,
            "mode": "decision-run-on-demand",
        }
    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready():
     ok = app.state.audit_repo is not None
     return {"status": "ready" if ok else "degraded"}

    return app


app = create_app()
