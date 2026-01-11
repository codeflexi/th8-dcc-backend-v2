# app/api/cases.py

from fastapi import APIRouter, HTTPException, Request, Query
from typing import List, Dict, Any, Optional
from datetime import datetime
import hashlib
import json
from pydantic import BaseModel, Field
import math

from app.schemas.case import CaseDetail
from app.schemas.portfolio import CasePortfolioItem
from app.schemas.decision import DecisionSummary
from app.services.audit_service import AuditService

# ✅ Import Decision Logic & Loader
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
# ✅ Helper Function: Dynamic Risk Logic (Single Source of Truth)
# =================================================
def get_policy_threshold() -> float:
    """
    ดึงค่า High Risk Threshold จาก YAML ไฟล์จริง
    เพื่อให้ config ตรงกันทั้งระบบ (Single Source of Truth)
    """
    try:
        # โหลด Policy หลัก (Default)
        policy = load_policy_yaml("PROCUREMENT-001", "v3.1")
        config = policy.get("config", {})
        return float(config.get("high_risk_threshold", 200000))
    except Exception:
        # กรณีฉุกเฉินจริงๆ หาไฟล์ไม่เจอ ให้ใช้ Default เก่า
        return 200000.0

def determine_risk_display(payload: Dict) -> str:
    """
    Determine risk level for display (Read-Model).
    """
    db_risk = payload.get("risk_level", "LOW")
    
    # 1. Trust DB first if already High
    if db_risk == "HIGH":
        return "HIGH"
    
    # 2. Check Priority Score
    score = payload.get("priority_score", 0)
    if score >= 80:
        return "HIGH"
    
    # 3. Safety Net: Check Amount vs YAML Configured Threshold
    try:
        raw_amt = payload.get("amount_total") or payload.get("amount") or 0
        if isinstance(raw_amt, str):
            amt = float(raw_amt.replace(",", ""))
        else:
            amt = float(raw_amt)
            
        # ✅ เรียกใช้ค่าจาก YAML (Dynamic)
        threshold = get_policy_threshold()
        
        if amt > threshold:
            return "HIGH"
    except Exception:
        pass
    
    return db_risk

# =================================================
# 1. GET Stats Endpoint
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
        
        # Calculate Exposure
        try:
            raw_amt = payload.get("amount_total") or payload.get("amount") or 0
            if isinstance(raw_amt, str):
                amt = float(raw_amt.replace(",", ""))
            else:
                amt = float(raw_amt)
        except:
            amt = 0
        total_exposure += amt
        
        # ✅ ใช้ Logic ที่ดึงค่าจาก YAML
        if determine_risk_display(payload) == "HIGH":
            high_risk += 1
            
    return {
        "total_exposure": total_exposure,
        "high_risk_count": high_risk,
        "open_cases": len(all_cases)
    }

# =================================================
# 2. GET List Endpoint
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

    for r in all_rows:
        payload = r.get("payload", {})
        
        # ✅ คำนวณ Risk เพื่อใช้ในการ Filter และ Display
        p_risk = determine_risk_display(payload)
        
        p_status = r.get("status", "OPEN")
        p_id = r["case_id"].lower()
        p_vendor = str(payload.get("vendor_name") or payload.get("vendor_id") or payload.get("vendor") or "").lower()

        # Apply Filters
        if risk and risk != "ALL" and p_risk != risk: continue
        if status and status != "ALL" and p_status != status: continue
        if search:
            q = search.lower()
            if q not in p_id and q not in p_vendor: continue
            
        # Store computed risk in row object temporarily
        r["_computed_risk"] = p_risk 
        filtered.append(r)

    # Paging Logic
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
                # ✅ ใช้ค่า Risk ที่คำนวณมาแล้ว
                risk_level=r.get("_computed_risk", "LOW"),
                created_at=r.get("created_at"),
            )
        )

    import math
    return {
        "items": items,
        "total": total,
        "page": page,
        "size": size,
        "pages": math.ceil(total / size) if size > 0 else 1
    }

# -------------------------
# Case detail
# -------------------------
@router.get("/{case_id}", response_model=CaseDetail)
def get_case(case_id: str, request: Request):
    case_repo = getattr(request.app.state, "case_repo", None)
    if not case_repo: raise HTTPException(status_code=500)
    case = case_repo.get_case(case_id)
    if not case: raise HTTPException(status_code=404)
    payload = case.get("payload", {})
    
    # ✅ ใช้ Logic กลาง (อ่าน YAML)
    risk = determine_risk_display(payload)

    vendor_display = payload.get("vendor_name") or payload.get("vendor_id") or payload.get("vendor")
    amount_display = payload.get("amount_total") or payload.get("amount") or 0

    decision_summary = DecisionSummary(
        decision_required=case.get("status") == "OPEN",
        decision_reason=payload.get("pending_reason"),
        violated_rules=[],
        risk_level=risk,
        recommended_action="REVIEW",
    )
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
        raw=case,
    )

# -------------------------
# Ingest
# -------------------------
@router.post("/ingest")
def ingest_case(data: CaseIngestRequest, request: Request):
    case_repo = getattr(request.app.state, "case_repo", None)
    if not case_repo: raise HTTPException(status_code=500)

    if case_repo.get_case(data.case_id):
        AuditService.write("INGESTION_FAILED", {"case_id": data.case_id, "reason": "Duplicate"}, "SYSTEM")
        raise HTTPException(status_code=409, detail=f"Case exists")

    now = datetime.utcnow().isoformat()
    payload_data = data.payload or {}
    
    # Robust Extraction for Ingest Log
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

    # ✅ Auto-Run Decision (ไม่กระทบของเดิม เพราะอยู่ใน try-except)
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