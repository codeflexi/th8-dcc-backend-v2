# app/api/cases.py

from fastapi import APIRouter, HTTPException, Request, Query
from typing import List, Dict, Any, Optional
from datetime import datetime
import hashlib
import json
from pydantic import BaseModel, Field
import math

# Schema imports
from app.schemas.case import CaseDetail
from app.schemas.portfolio import CasePortfolioItem
from app.schemas.decision import DecisionSummary
from app.services.audit_service import AuditService

# Decision Logic
from app.api.decisions import execute_decision_run, load_policy_yaml

router = APIRouter(tags=["cases"])

# =================================================
# Schemas
# =================================================
class CaseIngestRequest(BaseModel):
    case_id: str = Field(..., description="Enterprise case ID")
    domain: str = Field(default="procurement")
    payload: Dict[str, Any]

class CaseStats(BaseModel):
    total_exposure: float
    high_risk_count: int
    open_cases: int

class PaginatedCaseResponse(BaseModel):
    items: List[CasePortfolioItem]
    total: int
    page: int
    size: int
    pages: int

# =================================================
# ✅ Single Source of Truth — Risk Read Model
# =================================================
def determine_risk_display(payload: Dict) -> str:
    """
    Read-model for risk.
    Source of truth = payload.risk_level (written by decision engine)
    """
    return payload.get("risk_level", "LOW")

# =================================================
# 1. GET Stats
# =================================================
@router.get("/stats", response_model=CaseStats)
def get_case_stats(request: Request):
    case_repo = getattr(request.app.state, "case_repo", None)
    if not case_repo:
        return {"total_exposure": 0, "high_risk_count": 0, "open_cases": 0}
    
    all_cases = case_repo.list_cases()
    
    total_exposure = 0
    high_risk = 0
    
    for c in all_cases:
        payload = c.get("payload", {})
        
        # ---- exposure ----
        try:
            raw_amt = payload.get("amount_total") or payload.get("amount") or 0
            if isinstance(raw_amt, str):
                amt = float(raw_amt.replace(",", ""))
            else:
                amt = float(raw_amt)
        except:
            amt = 0

        total_exposure += amt
        
        # ---- risk ----
        if determine_risk_display(payload) in ["HIGH", "CRITICAL"]:
            high_risk += 1
            
    return {
        "total_exposure": total_exposure,
        "high_risk_count": high_risk,
        "open_cases": len(all_cases)
    }

# =================================================
# 2. GET List (FIXED FILTERS & SEARCH)
# =================================================
@router.get("", response_model=PaginatedCaseResponse)
def list_cases(
    request: Request,
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    search: Optional[str] = None,
    risk: Optional[str] = None,
    status: Optional[str] = None
):
    case_repo = getattr(request.app.state, "case_repo", None)
    if not case_repo:
        return {"items": [], "total": 0, "page": page, "size": size, "pages": 0}

    all_rows = case_repo.list_cases()
    filtered = []

    # ---------------------------------------------
    # ✅ 1. Prepare Filter Inputs (Normalize)
    # ---------------------------------------------
    q_search = search.lower().strip() if search else None
    q_risk = risk.upper() if risk and risk != "ALL" else None
    q_status = status.upper() if status and status != "ALL" else None

    for r in all_rows:
        payload = r.get("payload", {})
        
        # -----------------------------------------
        # ✅ 2. Normalize Data Values
        # -----------------------------------------
        # Risk
        p_risk_val = determine_risk_display(payload)
        p_risk_norm = str(p_risk_val).upper()
        
        # Status
        p_status_val = r.get("status", "OPEN")
        p_status_norm = str(p_status_val).upper()

        # Search Fields
        p_id = r["case_id"].lower()
        v_name = str(payload.get("vendor_name") or "").lower()
        v_id = str(payload.get("vendor_id") or "").lower()
        v_raw = str(payload.get("vendor") or "").lower()
        p_po = str(payload.get("po_number") or "").lower()

        # -----------------------------------------
        # ✅ 3. Apply Filters
        # -----------------------------------------
        
        # Filter: Risk
        if q_risk and p_risk_norm != q_risk:
            continue

        # Filter: Status
        if q_status and p_status_norm != q_status:
            continue

        # Filter: Search (Smart Search covers PO, ID, Vendor)
        if q_search:
            is_match = (
                (q_search in p_id) or 
                (q_search in v_name) or 
                (q_search in v_id) or 
                (q_search in v_raw) or
                (q_search in p_po)
            )
            if not is_match:
                continue
            
        # Store computed risk for display
        r["_computed_risk"] = p_risk_val 
        filtered.append(r)

    # ---------------------------------------------------------
    # Sort by Date DESC (Newest First) BEFORE Paging
    # ---------------------------------------------------------
    #filtered.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    # ป้องกันการระเบิดถ้า created_at ใน DB เป็น Null
    filtered.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    
    # ---- paging ----
    total = len(filtered)
    start = (page - 1) * size
    end = start + size
    paginated_rows = filtered[start:end]

    items = []
    for r in paginated_rows:
        payload = r.get("payload", {})
        
        vendor_display = (
            payload.get("vendor_name") or 
            payload.get("vendor_id") or 
            payload.get("vendor") or 
            "Unknown Vendor"
        )

        amount_display = (
            payload.get("amount_total") or 
            payload.get("amount") or 
            0
        )

        items.append(
            CasePortfolioItem(
                id=r["case_id"],
                domain=r.get("domain", "procurement"),
                vendor_id=vendor_display,
                amount_total=amount_display,
                status=r.get("status", "OPEN"),
                pending_reason=payload.get("pending_reason"),
                priority_score=payload.get("priority_score"),
                priority_reason=payload.get("priority_reason"),
                
                # Use value from loop
                risk_level=r.get("_computed_risk", "LOW"),

                created_at=r.get("created_at"),
            )
        )

    return {
        "items": items,
        "total": total,
        "page": page,
        "size": size,
        "pages": math.ceil(total / size) if size > 0 else 1
    }

# =================================================
# 3. GET Case Detail (UPDATED WITH STORY)
# =================================================
@router.get("/{case_id}", response_model=CaseDetail)
def get_case(case_id: str, request: Request):
    case_repo = getattr(request.app.state, "case_repo", None)
    if not case_repo:
        raise HTTPException(status_code=500)

    case = case_repo.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404)

    payload = case.get("payload", {})
    
    # ---- risk ----
    risk = determine_risk_display(payload)

    vendor_display = payload.get("vendor_name") or payload.get("vendor_id") or payload.get("vendor")
    amount_display = payload.get("amount_total") or payload.get("amount") or 0

    decision_summary = DecisionSummary(
        decision_required=case.get("status") == "OPEN",
        decision_reason=payload.get("pending_reason"),
        violated_rules=[],
        risk_level=risk,
        recommended_action=payload.get("last_decision", "REVIEW"),
    )

    # ----------------------------------------------------
    # ✅ GENERATE DECISION STORY (Mock Logic)
    # ----------------------------------------------------
    story_data = None
    print(risk);
    if risk in ["HIGH", "CRITICAL"]:
        story_data = {
            "headline": f"Why this case is {risk}",
            "risk_drivers": [
                {"label": "Vendor Blacklisted", "detail": "vendor_status = BLACKLISTED", "color": "red"},
                {"label": "High Amount Threshold", "detail": f"amount > 200,000", "color": "orange"}
            ],
            "business_impact": [
                f"Financial Exposure: THB {amount_display:,.2f}",
                "Compliance / Audit Risk: Blacklisted vendor exception"
            ],
            "suggested_action": {
                "title": "Hold & Escalate to COO",
                "description": "Requires executive approval due to blacklist status."
            },
            "evidence_list": [
                {
                    "title": "Master Contract – Office Supply 2026",
                    "subtitle": "Clause 4.2 • Pricing • Validity",
                    "description": "Evidence: ราคาสินค้าเกินราคาตามสัญญา / วันหมดอายุสัญญา",
                    "source_code": "doc_id=CONTRACT-2026-001 • page=6"
                },
                {
                    "title": "Vendor Profile: Bad Supplier Ltd.",
                    "subtitle": "Status = BLACKLISTED • last_update 2025-11-18",
                    "description": "Evidence: vendor ถูกระงับจาก incident ก่อนหน้า (มี reference)",
                    "source_code": "source=vendor_master • change_log_id=VM-18831"
                }
            ]
        }
    else:
        # Story for Low/Medium Risk
        story_data = {
            "headline": "Why this case is SAFE",
            "risk_drivers": [
                 {"label": "Vendor Verified", "detail": "Status = ACTIVE", "color": "green"},
                 {"label": "Within Budget", "detail": "Amount within department limit", "color": "green"}
            ],
            "business_impact": [
                "No negative impact detected.",
                "Standard SLA applies."
            ],
            "suggested_action": {
                "title": "Proceed to Auto-Approval",
                "description": "All checks passed. System can auto-approve."
            },
            "evidence_list": []
        }

    return CaseDetail(
        id=case["case_id"],
        domain=case.get("domain", "procurement"),
        vendor_id=vendor_display,
        amount_total=amount_display,
        status=case.get("status", "OPEN"),
        pending_reason=payload.get("pending_reason"),
        priority_score=payload.get("priority_score"),
        priority_reason=payload.get("priority_reason"),
        violations=[],
        decision_summary=decision_summary,
        created_at=case.get("created_at"),
        evaluated_at=case.get("updated_at"),
        # ✅ Pass story data to schema
        story=story_data,
        raw=case,
    )

# =================================================
# 4. Ingest
# =================================================
@router.post("/ingest")
def ingest_case(data: CaseIngestRequest, request: Request):
    case_repo = getattr(request.app.state, "case_repo", None)
    if not case_repo:
        raise HTTPException(status_code=500)

    if case_repo.get_case(data.case_id):
        AuditService.write("INGESTION_FAILED", {"case_id": data.case_id, "reason": "Duplicate"}, "SYSTEM")
        raise HTTPException(status_code=409, detail=f"Case exists")

    now = datetime.utcnow().isoformat()
    payload_data = data.payload or {}
    
    vendor_display = payload_data.get("vendor_name") or payload_data.get("vendor_id") or "Unknown"
    amount_display = payload_data.get("amount_total") or payload_data.get("amount") or 0
    po_display = payload_data.get("po_number") or "-"

    try:
        payload_hash = hashlib.sha256(json.dumps(payload_data, sort_keys=True).encode()).hexdigest()
    except:
        payload_hash = "HASH_ERR"

    policy_id = "PROCUREMENT-001"
    policy_version = "v3.1"

    record = {
        "case_id": data.case_id,
        "domain": data.domain,
        "status": "OPEN",
        "payload": payload_data,
        "policy_id": policy_id, 
        "policy_version": policy_version,
        "created_at": now,
        "updated_at": now,
    }
    case_repo.save_case(record)

    AuditService.write(
        event_type="CASE_INGESTED",
        actor="SYSTEM",
        payload={
            "case_id": data.case_id,
            "domain": data.domain,
            "source": "WEB_CONSOLE",
            "vendor": vendor_display,
            "amount": amount_display,
            "po_number": po_display,
            "integrity_hash": payload_hash
        }
    )

    # ---- auto run decision ----
    try:
        policy = load_policy_yaml(policy_id, policy_version)
        execute_decision_run(
            case=record,
            policy=policy,
            policy_id=policy_id,
            policy_version=policy_version
        )
        print(f"🚀 Auto-evaluated case {data.case_id} on ingest")
    except Exception as e:
        print(f"⚠️ Auto-evaluation failed: {e}")

    return {"status": "OK", "case_id": data.case_id}