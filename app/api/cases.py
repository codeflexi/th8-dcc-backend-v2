from fastapi import APIRouter, HTTPException, Request
from typing import List, Dict, Any
from datetime import datetime
import hashlib
import json
from pydantic import BaseModel, Field

from app.schemas.case import CaseDetail
from app.schemas.portfolio import CasePortfolioItem
from app.schemas.decision import DecisionSummary
from app.services.audit_service import AuditService  # <--- Import Audit Service

router = APIRouter(tags=["cases"])


# =================================================
# Request model for ingest (demo-safe)
# =================================================
class CaseIngestRequest(BaseModel):
    case_id: str = Field(..., description="Enterprise case ID")
    domain: str = Field(default="procurement")
    payload: Dict[str, Any]


# -------------------------
# List cases (Portfolio)
# -------------------------
@router.get("", response_model=List[CasePortfolioItem])
def list_cases(request: Request):
    case_repo = getattr(request.app.state, "case_repo", None)
    if not case_repo:
        return []

    rows = case_repo.list_cases()
    items: List[CasePortfolioItem] = []

    for r in rows:
        payload = r.get("payload", {})
        
        # Robust extraction for list view
        vendor_display = (
            payload.get("vendor_id") or 
            payload.get("vendor_name") or 
            payload.get("vendor") or 
            "Unknown Vendor"
        )

        items.append(
            CasePortfolioItem(
                id=r["case_id"],
                domain=r.get("domain", "procurement"),
                vendor_id=vendor_display,
                amount_total=payload.get("amount_total", 0),
                status=r.get("status", "OPEN"),
                pending_reason=payload.get("pending_reason"),
                priority_score=payload.get("priority_score"),
                priority_reason=payload.get("priority_reason"),
                created_at=r.get("created_at"),
            )
        )

    return items


# -------------------------
# Case detail (Decision-ready)
# -------------------------
@router.get("/{case_id}", response_model=CaseDetail)
def get_case(case_id: str, request: Request):
    case_repo = getattr(request.app.state, "case_repo", None)
    if not case_repo:
        raise HTTPException(status_code=500, detail="Case repository not initialized")

    case = case_repo.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    payload = case.get("payload", {})
    
    # Robust extraction for detail view
    vendor_display = (
        payload.get("vendor_id") or 
        payload.get("vendor_name") or 
        payload.get("vendor")
    )

    decision_summary = DecisionSummary(
        decision_required=case.get("status") == "OPEN",
        decision_reason=payload.get("pending_reason"),
        violated_rules=[],
        risk_level="HIGH" if payload.get("priority_score", 0) >= 80 else "MEDIUM",
        recommended_action="REVIEW",
    )

    return CaseDetail(
        id=case["case_id"],
        domain=case.get("domain", "procurement"),
        vendor_id=vendor_display,
        amount_total=payload.get("amount_total", 0),
        status=case.get("status", "OPEN"),
        pending_reason=payload.get("pending_reason"),
        priority_score=payload.get("priority_score"),
        priority_reason=payload.get("priority_reason"),
        violations=[],
        decision_summary=decision_summary,
        created_at=case.get("created_at"),
        evaluated_at=case.get("updated_at"),
        raw=case,  # full DB record (for audit/debug)
    )


# =================================================
# ✅ Case Ingestion (Enterprise Grade)
# POST /api/cases/ingest
# =================================================
@router.post("/ingest")
def ingest_case(data: CaseIngestRequest, request: Request):
    """
    Ingest case from ERP / workflow / manual demo input.
    Includes comprehensive Audit Logging and Data Integrity Checks.
    """
    case_repo = getattr(request.app.state, "case_repo", None)
    if not case_repo:
        raise HTTPException(status_code=500, detail="Case repository not initialized")

    # --- 1. Security Check & Failure Logging ---
    if case_repo.get_case(data.case_id):
        AuditService.write(
            event_type="INGESTION_FAILED",
            actor="SYSTEM",
            payload={
                "case_id": data.case_id,
                "reason": "Duplicate Case ID",
                "source": "MANUAL_CONSOLE"
            }
        )
        raise HTTPException(
            status_code=409,
            detail=f"Case already exists: {data.case_id}"
        )

    now = datetime.utcnow().isoformat()

    # --- 2. Robust Data Extraction (Shotgun Approach) ---
    # พยายามดึงค่าสำคัญออกมาให้ได้มากที่สุด ไม่ว่าจะส่งมาด้วย Key ไหน
    payload_data = data.payload or {}
    
    vendor_display = (
        payload_data.get("vendor_name") or 
        payload_data.get("vendor_id") or 
        payload_data.get("vendor") or 
        payload_data.get("supplier") or
        "Unknown Vendor"
    )
    
    amount_display = (
        payload_data.get("amount_total") or 
        payload_data.get("amount") or 
        payload_data.get("total_price") or
        0
    )

    po_display = (
        payload_data.get("po_number") or 
        payload_data.get("po") or 
        payload_data.get("id") or
        "N/A"
    )

    # --- 3. Compute Data Integrity Hash ---
    try:
        payload_str = json.dumps(payload_data, sort_keys=True)
        payload_hash = hashlib.sha256(payload_str.encode()).hexdigest()
    except Exception:
        payload_hash = "HASH_ERROR"

    # --- 4. Prepare DB Record (With Policy Binding) ---
    record = {
        "case_id": data.case_id,
        "domain": data.domain,
        "status": "OPEN",
        "payload": payload_data,
        
        # ✅ Bind Default Policy Immediately
        "policy_id": "PROCUREMENT-001", 
        "policy_version": "v3.1",
        
        "created_at": now,
        "updated_at": now,
    }

    case_repo.save_case(record)

    # --- 5. Log Success Event (Start of Timeline) ---
    AuditService.write(
        event_type="CASE_INGESTED",
        actor="SYSTEM",
        payload={
            "case_id": data.case_id,
            "domain": data.domain,
            "message": "Case ingested via Simulation Console",
            "source": "WEB_CONSOLE",
            "integrity_hash": payload_hash,
            
            # ✅ Extracted fields for rich UI display
            "vendor": vendor_display,
            "amount": amount_display,
            "po_number": po_display,
            
            # เก็บ Preview สั้นๆ ไว้ debug
            "raw_preview": str(payload_data)[:100] + "..."
        }
    )

    return {
        "status": "OK",
        "case_id": data.case_id,
        "message": "Case ingested successfully with audit trail"
    }