from fastapi import APIRouter

from app.api.health import router as health_router
from app.api.demo import router as demo_router
from app.api.cases import router as cases_router
from app.api.audit import router as audit_router
from app.api.decisions import router as decisions_router
from app.api.evidence import router as evidence_router
from app.api.copilot import router as copilot_router

api_router = APIRouter()

# -------------------------------------------------
# system / ops
# -------------------------------------------------
api_router.include_router(
    health_router,
    prefix="/health",
    tags=["health"],
)

# -------------------------------------------------
# demo / bootstrap
# -------------------------------------------------
api_router.include_router(
    demo_router,
    prefix="/demo",
    tags=["demo"],
)

# -------------------------------------------------
# core business
# -------------------------------------------------
api_router.include_router(
    cases_router,
    prefix="/cases",
    tags=["cases"],
)

api_router.include_router(
    decisions_router,
    prefix="/decisions",
    tags=["decisions"],
)

# -------------------------------------------------
# audit / timeline  ✅ FIX HERE (NO PREFIX)
# -------------------------------------------------
api_router.include_router(
    audit_router,
    tags=["audit"],
)

# -------------------------------------------------
# evidence
# -------------------------------------------------
api_router.include_router(
    evidence_router,
    prefix="/evidence",
    tags=["evidence"],
)

# -------------------------------------------------
# copilot
# -------------------------------------------------
api_router.include_router(
    copilot_router,  # 2. ✅ แก้ตรงนี้จาก evidence_router เป็น copilot_router
    prefix="/copilot",
    tags=["copilot"],
)
