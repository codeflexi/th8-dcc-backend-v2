from curses import raw
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, List, Any
import yaml
import uuid
import logging
import json
import os
from pathlib import Path
from datetime import datetime

from app.services.audit_service import AuditService
from app.services.decision_engine import DecisionEngine
from app.repositories.supabase_repo import SupabaseCaseRepository
from app.db.supabase_client import supabase # ✅ เพิ่ม: เพื่อดึงข้อมูล Metadata เก่า

logger = logging.getLogger("decisions_api")
router = APIRouter(tags=["decisions"])

print("🔥 decisions router loaded (Fixed: Recursive Unwrap + Metadata Fetching)")

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

def fmt_num(val: Any) -> str:
    try:
        if val is None:
            return "None"
        return "{:,.2f}".format(float(str(val).replace(",", "")))
    except:
        return str(val)

# =====================================================
# Helper: Load Contract from JSON (Robust Version ✅)
# =====================================================
def get_contract_for_vendor(vendor_name: str) -> Dict:
    print(f"\n🔍 [DEBUG] Start finding contract for vendor: '{vendor_name}'")
    
    try:
        # 1. Resolve Path (หาไฟล์จากหลายๆ ที่ที่เป็นไปได้)
        current_file = Path(__file__).resolve()
        backend_root = current_file.parents[2] 
        
        possible_paths = [
            backend_root / "data" / "mock_contracts.json",       
            backend_root / "app" / "data" / "mock_contracts.json", 
            Path("data/mock_contracts.json").resolve(),          
        ]
        
        json_path = None
        for p in possible_paths:
            if p.exists():
                json_path = p
                print(f"✅ [DEBUG] Found DB file at: {json_path}")
                break
        
        if not json_path:
            print(f"❌ [DEBUG] Contract DB NOT FOUND! Checked: {[str(p) for p in possible_paths]}")
            return {}

        # 2. Load Data
       
        raw = json.loads(json_path.read_text(encoding="utf-8"))

        # รองรับทั้งกรณี dict และ list
        if isinstance(raw, list) and len(raw) > 0:
            data = raw[0]
        elif isinstance(raw, dict):
            data = raw
        else:
            print("❌ [DEBUG] Invalid contract DB format")
            return {}

        contracts = data.get("contracts", {})
        

        # 3. Search Vendor (Case Insensitive Match)
        if vendor_name in contracts:
            print(f"✅ [DEBUG] Exact match found for '{vendor_name}'")
            return contracts[vendor_name]
            
        target_name = str(vendor_name).lower().strip()
        print(f"   [DEBUG] Trying fuzzy match for '{target_name}'...")
        
        for k, v in contracts.items():
            # Check key
            if str(k).lower().strip() == target_name:
            
                return v
            # Check inner field
            if v.get("vendor_name") and str(v.get("vendor_name")).lower().strip() == target_name:
               
                return v
        
        
        return {}
        
    except Exception as e:
        print(f"❌ [DEBUG] Error in get_contract_for_vendor: {e}")
        return {}

# =====================================================
# Helper: Load RULE from YAML Policy
# =====================================================
def load_policy_yaml(policy_id: str, version: str) -> Dict:
    base_dir = Path(__file__).resolve().parents[2]
    policy_dir = base_dir / "app" / "policies"

    if not policy_dir.exists():
        raise FileNotFoundError(f"Policy directory not found: {policy_dir}")

    for p in policy_dir.glob("*.yaml"):
        try:
            data = yaml.safe_load(p.read_text())
            pid = data.get("policy_id") or data.get("id") or data.get("policy", {}).get("id")
            ver = data.get("version") or data.get("policy_version") or data.get("policy", {}).get("version")
            if str(pid) == str(policy_id) and str(ver) == str(version):
                return data
        except:
            continue

    raise FileNotFoundError(f"Policy not found: {policy_id} v{version}")


# =====================================================
# Risk Derivation (POLICY-DRIVEN)
# =====================================================

RISK_PRIORITY = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]


def collect_risk_drivers(policy: Dict, rule_results: List[Dict]) -> List[Dict]:
    drivers = []
    for r in rule_results:
        if not r.get("hit"):
            continue

        rule_def = next(
            (x for x in policy.get("rules", []) if x.get("id") == r.get("rule_id")),
            None
        )

        if rule_def and rule_def.get("risk_impact"):
            drivers.append({
                "rule_id": r["rule_id"],
                "impact": rule_def["risk_impact"],
                "description": rule_def.get("description"),
            })
    return drivers

def derive_risk_from_drivers(drivers: List[Dict]) -> str:
    if not drivers:
        return "LOW"
    impacts = [d["impact"] for d in drivers]
    for p in RISK_PRIORITY:
        if p in impacts:
            return p
    return "LOW"

def apply_threshold_safety_net(current_risk: str, amount: float, policy: Dict) -> str:
    risk = current_risk
    thresholds = policy.get("thresholds", {}).get("amount", {})
    high_th = thresholds.get("high")
    med_th = thresholds.get("medium")

    if high_th is not None and amount >= high_th:
        risk = "HIGH"
    elif med_th is not None and amount >= med_th and risk == "LOW":
        risk = "MEDIUM"

    config = policy.get("config", {})
    force_th = config.get("high_risk_threshold")
    if force_th is not None and amount > float(force_th):
        risk = config.get("force_risk_level", "HIGH")

    return risk


# =====================================================
# Core Execution
# =====================================================

def execute_decision_run(
    *,
    case: Dict,
    policy: Dict,
    policy_id: str,
    policy_version: str,
) -> Dict:

    payload = case.get("payload", {})

    # -------------------------------------------------
    # 1. Normalize Amount
    # -------------------------------------------------
    raw_amount = payload.get("amount_total") or payload.get("amount") or payload.get("total_price") or 0
    try:
        amount = float(raw_amount.replace(",", "")) if isinstance(raw_amount, str) else float(raw_amount)
    except:
        amount = 0.0

    payload["amount_total"] = amount

    # -------------------------------------------------
    # 2. Vendor Enrichment
    # -------------------------------------------------
    vendor_raw = payload.get("vendor_name") or payload.get("vendor_id") or payload.get("vendor") or ""
    vendor_name = str(vendor_raw).lower()
    
    

    vendor_status = "ACTIVE"
    if "bad" in vendor_name or "blacklist" in vendor_name:
        vendor_status = "BLACKLISTED"

    vendor_rating = 95
    if "late" in vendor_name:
        vendor_rating = 55

    # -------------------------------------------------
    # 3. Budget / Fraud Context
    # -------------------------------------------------
    budget_limit = 1_000_000
    budget_remaining = budget_limit - amount

    po_count_24h = 1
    if "makro" in vendor_name or "lotus" in vendor_name:
        po_count_24h = 2

    total_spend_24h = amount * po_count_24h

    # -------------------------------------------------
    # 4. Pack Inputs (CANONICAL CONTRACT) ✅
    # -------------------------------------------------
    
    # 🔴 FIX 1: เรียกใช้ฟังก์ชันโหลดสัญญา
    contract_raw = get_contract_for_vendor(vendor_name) 
    
    engine_contract_input = {}
    if contract_raw:
        price_map = {
            item["sku"]: item["agreed_price"] 
            for item in contract_raw.get("items", {}).values()
        }
        engine_contract_input = {
            "doc_id": contract_raw.get("doc_id"),
            "is_active": True, 
            "prices": price_map
        }
    else:
        print(f"⚠️ [DEBUG] No contract found for vendor: '{vendor_name}', passing empty dict to engine.")
        
    
    print(f"🔍 [DEBUG] Contract input for engine: {engine_contract_input}")

    # 🔴 FIX 2: ส่ง contract เข้า inputs
    inputs = {
        "amount_total": amount,
        "amount": amount,
        "hours_to_sla": payload.get("hours_to_sla", 48),
        "vendor_status": vendor_status,
        "vendor_rating": vendor_rating,
        "budget_remaining": budget_remaining,
        "po_count_24h": po_count_24h,
        "total_spend_24h": total_spend_24h,
        "vendor_name": vendor_raw,
        "line_items": payload.get("line_items", []),
        
        # ✅ ใส่ข้อมูลสัญญาลงไปให้ Engine ใช้คำนวณ
        "contract": engine_contract_input 
    }

    run_id = str(uuid.uuid4())

    AuditService.write(
        "DECISION_RUN_STARTED",
        {"case_id": case["case_id"], "run_id": run_id, "inputs": inputs},
        "SYSTEM",
    )

    # -------------------------------------------------
    # 5. Run Decision Engine
    # -------------------------------------------------
    result = DecisionEngine.evaluate(policy=policy, inputs=inputs)
    decision_val = result["recommendation"].get("decision", "REVIEW")

   
    # -------------------------------------------------
    # 6. Derive Risk Level (POLICY-DRIVEN)
    # -------------------------------------------------
    risk_drivers = collect_risk_drivers(policy, result["rule_results"])

    base_risk = derive_risk_from_drivers(risk_drivers)

    new_risk = apply_threshold_safety_net(
        base_risk,
        amount,
        policy
    )
    print(f"\n🧠 [DEBUG] Decision Engine RESULTS: {new_risk}")
    
    # -------------------------------------------------
    # 7. Audit: Risk Derived
    # -------------------------------------------------
    AuditService.write(
        "RISK_LEVEL_DERIVED",
        {
            "case_id": case["case_id"],
            "run_id": run_id,
            "risk_level": new_risk,
            "derived_from": {
                "policy_id": policy_id,
                "policy_version": policy_version,
                "decision": decision_val,
                "amount": amount,
                "risk_drivers": risk_drivers,
            },
        },
        "SYSTEM",
    )

    # -------------------------------------------------
    # 8. Build Evaluation Logic (AUDIT-GRADE)
    # -------------------------------------------------
    for rr in result["rule_results"]:
        eval_logic = {}

        conditions_to_check = []
        if rr.get("matched"):
            conditions_to_check = rr["matched"]
        else:
            rule_def = next((r for r in policy.get("rules", []) if r.get("id") == rr["rule_id"]), None)
            if rule_def:
                for c in rule_def.get("when", []):
                    conditions_to_check.append({
                        "field": c.get("field"),
                        "operator": c.get("operator"),
                        "expected": c.get("value"),
                        "actual": inputs.get(c.get("field")),
                    })
       
        for m in conditions_to_check:
            field = m.get("field")
            operator = m.get("operator")
            expected = m.get("expected")
            actual = m.get("actual")

            act_str = fmt_num(actual)
            exp_str = fmt_num(expected)

            # ✅ FIX: เชื่อผลลัพธ์ (hit) ที่ Decision Engine ส่งมาเลย (Optimized)
            is_true = rr["hit"]

            if is_true:
                msg = f"⚠️ Risk Detected ({act_str} {operator} {exp_str})"
            else:
                msg = f"✅ Pass ({act_str} does NOT satisfy {operator} {exp_str})"

            eval_logic[field] = f"{act_str} (Rule: {operator} {exp_str}) -> {msg}"
            
        if not eval_logic:
            eval_logic["Result"] = "Criteria Met" if rr["hit"] else "Passed"

        rr["inputs"] = eval_logic

        AuditService.write(
            "RULE_EVALUATED",
            {
                "case_id": case["case_id"],
                "run_id": run_id,
                "rule": {"id": rr["rule_id"], "description": rr.get("description")},
                "hit": rr["hit"],
                "matched": rr["matched"],
                "inputs": eval_logic,
            },
            "SYSTEM",
        )

   # -------------------------------------------------
    # 9. Decision Summary
    # -------------------------------------------------
    AuditService.write(
        "DECISION_RECOMMENDED",
        {"case_id": case["case_id"], "run_id": run_id, "recommendation": result["recommendation"]},
        "SYSTEM",
    )

    AuditService.write(
        "DECISION_RUN_COMPLETED",
        {
            "case_id": case["case_id"],
            "run_id": run_id,
            "decision": decision_val,
            "risk_level": new_risk,
        },
        "SYSTEM",
    )


    # -------------------------------------------------
    # 🔴 Step 10: Sync back (Correct Structure Only)
    # -------------------------------------------------
    # สร้าง Payload ก้อนใหม่ที่รวม Business Data + Results
    final_payload = payload.copy()
    
    final_payload.update({
        "risk_level": new_risk,
        "last_decision": decision_val,
        "evaluated_at": datetime.utcnow().isoformat(),
    
        "last_rule_results": result["rule_results"],
        "decision_summary": {
            "risk_level": new_risk,
            "recommended_action": decision_val,
            "reason_codes": result["recommendation"].get("reason_codes", []),
        },
    })
    
   # if "payload" in final_payload: del final_payload["payload"]

    # บันทึกข้อมูลกลับที่ Case Object
    case["payload"] = final_payload
    case["status"] = "EVALUATED"
    case["updated_at"] = datetime.utcnow().isoformat()
    case["policy_id"] = policy_id
    case["policy_version"] = policy_version 
    case["domain"] = case.get("domain") or "procurement"  # Default Domain  
    case["created_at"] = case.get("created_at") or datetime.utcnow().isoformat()  # Default Created At
    
    # # ✅ ป้องกัน Metadata หาย (สาเหตุ Error 500)
    # if not case.get("created_at"): case["created_at"] = datetime.utcnow().isoformat()
    # if not case.get("domain"): case["domain"] = "procurement"

    try:
        repo = SupabaseCaseRepository()
        repo.save_case(case) # Save ผ่าน Repo เพื่อผ่าน Pentest
    except Exception as e:
        logger.error(f"Sync error: {e}")

    return { "run_id": str(uuid.uuid4()), "rule_results": result["rule_results"], "recommendation": result["recommendation"] }

# =====================================================
# Endpoints
# =====================================================

@router.post("/run", response_model=RunDecisionResponse)
def run_decision(req: RunDecisionRequest):
    repo = SupabaseCaseRepository()
    case = repo.get_case(req.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="CASE_NOT_FOUND")
    
    # ✅ เรียกผ่าน Repo (ต้องมีฟังก์ชัน get_case_metadata ใน Repo แล้ว)
    metadata = repo.get_case_metadata(req.case_id)

    full_case = {
        "case_id": req.case_id, 
        "payload": case.get("payload", {}),
        "status": metadata.get("status", "NEW"), 
        "domain": metadata.get("domain", "procurement"), 
        "created_at": metadata.get("created_at"),
        "policy_id": req.policy_id or metadata.get("payload.policy_id"),
        "policy_version": req.policy_version or metadata.get("payload.policy_version")
    }

    try:
        policy = load_policy_yaml(req.policy_id, req.policy_version)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    execution = execute_decision_run(
        case=full_case,
        policy=policy,
        policy_id=req.policy_id,
        policy_version=req.policy_version,
    )

    return {
        "case_id": req.case_id,
        "policy": {"policy_id": req.policy_id, "version": req.policy_version},
        "rule_results": execution["rule_results"],
        "recommendation": execution["recommendation"],
        "written_events": ["DECISION_RUN_COMPLETED"],
    }


@router.post("/cases/{case_id}/decisions/run")
def run_decision_by_case(case_id: str):
    repo = SupabaseCaseRepository()
    case = repo.get_case(case_id)
    if not case: raise HTTPException(status_code=404, detail="CASE_NOT_FOUND")

    # ✅ เรียกผ่าน Repo
    metadata = repo.get_case_metadata(case_id)

    full_case = {
        "case_id": case_id, 
        "payload": case.get("payload", {}),
        "status": metadata.get("status", "NEW"),
        "domain": metadata.get("domain", "procurement"),
        "created_at": metadata.get("created_at"),
        "policy_id": metadata.get("payload.policy_id"),
        "policy_version": metadata.get("payload.policy_version")
    }

    # Use Metadata Policy OR Default
    pid = metadata.get("payload.policy_id") or "PROCUREMENT-001"
    pver = metadata.get("payload.policy_version") or "v3.1"

    try:
        policy = load_policy_yaml(pid, pver)
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail="Policy NOT FOUND")

    execution = execute_decision_run(
        case=full_case,
        policy=policy,
        policy_id=pid,
        policy_version=pver,
    )

    return {"status": "ok", "case_id": case_id, "run": execution}