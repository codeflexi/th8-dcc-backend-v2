# app/api/decisions.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, List
import yaml
import uuid
from pathlib import Path

from app.services.audit_service import AuditService
from app.services.decision_engine import DecisionEngine
from app.repositories.supabase_repo import SupabaseCaseRepository

router = APIRouter(tags=["decisions"])

print("🔥 decisions router loaded")

# =====================================================
# Schemas
# =====================================================

class RunDecisionRequest(BaseModel):
    case_id: str
    policy_id: str
    policy_version: str


class RunDecisionResponse(BaseModel):
    case_id: str
    policy: Dict
    rule_results: List[Dict]
    recommendation: Dict
    written_events: List[str]


# =====================================================
# Helpers
# =====================================================

def load_policy_yaml(policy_id: str, version: str) -> Dict:
    """
    Load policy by content (immutable, schema-tolerant).
    """
    base_dir = Path(__file__).resolve().parents[2]
    policy_dir = base_dir / "app" / "policies"

    if not policy_dir.exists():
        raise FileNotFoundError(f"Policy directory not found: {policy_dir}")

    candidates = []

    for p in policy_dir.glob("*.yaml"):
        data = yaml.safe_load(p.read_text())

        pid = (
            data.get("policy_id")
            or data.get("id")
            or data.get("policy", {}).get("id")
        )

        ver = (
            data.get("version")
            or data.get("policy_version")
            or data.get("policy", {}).get("version")
        )

        if pid and ver is not None:
            candidates.append((p.name, pid, str(ver)))

            if pid == policy_id and str(ver) == str(version):
                return data

    debug = ", ".join(
        [f"{name}(id={pid}, version={ver})" for name, pid, ver in candidates]
    )

    raise FileNotFoundError(
        f"Policy not found: policy_id={policy_id}, version={version}. "
        f"Available policies: [{debug}]"
    )


def execute_decision_run(
    *,
    case: Dict,
    policy: Dict,
    policy_id: str,
    policy_version: str,
) -> Dict:
    
    payload = case.get("payload", {})
    amount = payload.get("amount_total", 0)
    
    # -------------------------------------------------------------
    # 🛠️ DATA ENRICHMENT (จำลองการดึงข้อมูลประกอบการตัดสินใจ)
    # ในระบบจริง: ต้อง Query Database หรือเรียก External API (SAP/ERP)
    # -------------------------------------------------------------
    
    # 1. จำลองข้อมูล Vendor
    # (ถ้าชื่อ Vendor มีคำว่า "Bad", "Unknown" ให้ลองสมมติว่าเป็น Blacklist)
    vendor_name = payload.get("vendor_name", "").lower()
    vendor_status = "BLACKLISTED" if "unknown" in vendor_name else "ACTIVE"
    vendor_rating = 55 if "late" in vendor_name else 95  # สมมติคะแนน

    # 2. จำลองข้อมูล Budget
    # (สมมติว่าถ้าซื้อเกิน 1 ล้าน งบจะติดลบ)
    budget_remaining = 1000000 - amount

    # 3. จำลองข้อมูล Split PO
    # (สมมติว่าถ้าเป็น Makro หรือ Lotus มักจะซื้อบ่อย -> นับเป็น 2 บิล)
    po_count_24h = 2 if "makro" in vendor_name or "lotus" in vendor_name else 1
    total_spend_24h = amount * po_count_24h

    # -------------------------------------------------------------
    # ✅ Pack Inputs ส่งให้ Engine (ต้องตรงกับ field ใน YAML)
    # -------------------------------------------------------------
    inputs = {
        "amount": amount,
        "hours_to_sla": payload.get("hours_to_sla", 48),
        
        # New Fields for Rules
        "vendor_status": vendor_status,
        "vendor_rating": vendor_rating,
        "budget_remaining": budget_remaining,
        "po_count_24h": po_count_24h,
        "total_spend_24h": total_spend_24h,
        
        # LLM context inputs
        "vendor_name": payload.get("vendor_name", ""),
        "line_items": payload.get("line_items", [])
    }

    run_id = str(uuid.uuid4())

    # -------------------------------------------------
    # Run started
    # -------------------------------------------------
    AuditService.write(
        event_type="DECISION_RUN_STARTED",
        actor="SYSTEM",
        payload={
            "case_id": case["case_id"],
            "run_id": run_id,
            "policy_id": policy_id,
            "policy_version": policy_version,
            "inputs": inputs,
        },
    )

    # -------------------------------------------------
    # Decision evaluation (existing behavior)
    # -------------------------------------------------
    result = DecisionEngine.evaluate(
        policy=policy,
        inputs=inputs,
    )

    for rr in result["rule_results"]:
        AuditService.write(
            event_type="RULE_EVALUATED",
            actor="SYSTEM",
            payload={
                "case_id": case["case_id"],
                "run_id": run_id,
                "policy": {
                    "policy_id": policy_id,
                    "version": policy_version,
                },
                "rule": {
                    "id": rr["rule_id"],
                    "description": rr.get("description"),
                },
                "hit": rr["hit"],
                # ✅ FIX: ใช้ .get() เพื่อป้องกัน KeyError ถ้า field นี้ไม่มี
                "matched": rr.get("matched", []),
                "inputs": inputs,
            },
        )

    # -------------------------------------------------
    # Recommendation
    # -------------------------------------------------
    AuditService.write(
        event_type="DECISION_RECOMMENDED",
        actor="SYSTEM",
        payload={
            "case_id": case["case_id"],
            "run_id": run_id,
            "policy": {
                "policy_id": policy_id,
                "version": policy_version,
            },
            "recommendation": result["recommendation"],
        },
    )

    # -------------------------------------------------
    # Run completed
    # -------------------------------------------------
    AuditService.write(
        event_type="DECISION_RUN_COMPLETED",
        actor="SYSTEM",
        payload={
            "case_id": case["case_id"],
            "run_id": run_id,
            "decision": result["recommendation"].get("decision"),
            "required_role": result["recommendation"].get("required_role"),
        },
    )

    return {
        "run_id": run_id,
        "rule_results": result["rule_results"],
        "recommendation": result["recommendation"],
    }


# =====================================================
# Endpoints (Backward Compatible)
# =====================================================

@router.post("/run", response_model=RunDecisionResponse)
def run_decision(req: RunDecisionRequest):
    """
    Legacy endpoint (unchanged contract)
    """

    repo = SupabaseCaseRepository()
    case = repo.get_case(req.case_id)

    if not case:
        raise HTTPException(status_code=404, detail="CASE_NOT_FOUND")

    policy = load_policy_yaml(req.policy_id, req.policy_version)

    execution = execute_decision_run(
        case=case,
        policy=policy,
        policy_id=req.policy_id,
        policy_version=req.policy_version,
    )

    return {
        "case_id": req.case_id,
        "policy": {
            "policy_id": req.policy_id,
            "version": req.policy_version,
        },
        "rule_results": execution["rule_results"],
        "recommendation": execution["recommendation"],
        "written_events": [
            "DECISION_RUN_STARTED",
            "RULE_EVALUATED",
            "DECISION_RECOMMENDED",
            "DECISION_RUN_COMPLETED",
        ],
    }


# =====================================================
# Enterprise Endpoint (New)
# =====================================================

@router.post("/cases/{case_id}/decisions/run")
def run_decision_by_case(case_id: str):
    """
    Enterprise-style endpoint

    - policy is bound to case
    - frontend does NOT send policy
    - run_id is first-class
    """

    repo = SupabaseCaseRepository()
    case = repo.get_case(case_id)

    if not case:
        raise HTTPException(status_code=404, detail="CASE_NOT_FOUND")

    policy_id = case.get("policy_id")
    policy_version = case.get("policy_version")

    if not policy_id or not policy_version:
        raise HTTPException(
            status_code=400,
            detail="CASE_HAS_NO_BOUND_POLICY",
        )

    policy = load_policy_yaml(policy_id, policy_version)

    execution = execute_decision_run(
        case=case,
        policy=policy,
        policy_id=policy_id,
        policy_version=policy_version,
    )

    return {
        "status": "ok",
        "case_id": case_id,
        "run": execution,
    }