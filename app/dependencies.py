# app/dependencies.py
import logging
from fastapi import FastAPI

from app.repositories.supabase_repo import SupabaseCaseRepository
from app.repositories.supabase_audit_repo import SupabaseAuditRepository
from app.services.orchestrator import DecisionOrchestrator

logger = logging.getLogger(__name__)


def init_repositories(app: FastAPI) -> None:
    """
    Initialize infrastructure dependencies.
    Must be idempotent.
    """
    try:
        app.state.audit_repo = SupabaseAuditRepository()
        app.state.case_repo = SupabaseCaseRepository()
        logger.info("Repositories initialized")
    except Exception:
        # audit repo should always exist
        logger.exception("Repository initialization failed")
        app.state.audit_repo = SupabaseAuditRepository()
        app.state.case_repo = None


def get_orchestrator(app: FastAPI) -> DecisionOrchestrator:
    """
    Lazy init orchestrator to avoid heavy startup cost.
    """
    if not hasattr(app.state, "orchestrator"):
        app.state.orchestrator = DecisionOrchestrator()
        logger.info("DecisionOrchestrator initialized (lazy)")
    return app.state.orchestrator
