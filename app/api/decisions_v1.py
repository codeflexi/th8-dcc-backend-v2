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
        data = json.loads(json_path.read_text(encoding="utf-8"))
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
                print(f"✅ [DEBUG] Fuzzy Key match found! '{vendor_name}' matches '{k}'")
                return v
            # Check inner field
            if v.get("vendor_name") and str(v.get("vendor_name")).lower().strip() == target_name:
                print(f"✅ [DEBUG] Inner Field match found! '{vendor_name}' matches data inside '{k}'")
                return v
        
        print(f"⚠️ [DEBUG] Vendor '{vendor_name}' not found. Available keys in DB: {list(contracts.keys())}")
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
# ✅ NEW: Helper Fetch Original Metadata (ป้องกัน Error 500/400)
# =====================================================
def fetch_existing_metadata(case_id: str) -> Dict:
    """
    ดึงข้อมูล Case ตัวเต็มจาก DB เพื่อเอา created_at, domain เดิมมาใช้
    """
    try:
        res = supabase.table("cases").select("case_id, domain, created_at, status").eq("case_id", case_id).maybe_single().execute()
        if res.data:
            return res.data
        return {}
    except Exception as e:
        logger.error(f"Failed to fetch metadata for {case_id}: {e}")
        return {}

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

    # Initial payload
    root_payload = case.get("payload", {})

    # -------------------------------------------------
    # 🔴 FIX: Recursive Extraction (แก้ปัญหาข้อมูลซ้อนกันแบบเจาะลึก)
    # -------------------------------------------------
    real_payload = root_payload
    depth = 0
    # วนลูปเจาะลงไปจนกว่าจะเจอข้อมูลเนื้อในจริงๆ (ที่มี vendor หรือ line_items)
    # หรือจนกว่าจะลึกเกิน 3 ชั้น
    while depth < 3:
        # ถ้าเจอ key ที่บ่งบอกว่าเป็น Business Data ให้หยุดและใช้ตัวนี้เลย
        if "vendor" in real_payload or "vendor_name" in real_payload or "line_items" in real_payload:
            break
            
        # ถ้ายังไม่เจอ แต่มี key 'payload' ซ้อนอยู่ ให้เจาะลงไป
        if isinstance(real_payload, dict) and "payload" in real_payload and isinstance(real_payload["payload"], dict):
            print(f"🔄 [DEBUG] Unwrapping nested 'payload' layer {depth+1}...")
            real_payload = real_payload["payload"]
            depth += 1
        else:
            break # ทางตัน

    print(f"📦 [DEBUG] Working Data Keys: {list(real_payload.keys())}")

    # 1. Normalize Amount (ใช้ real_payload)
    raw_amount = real_payload.get("amount_total") or real_payload.get("amount") or real_payload.get("total_price") or 0
    try:
        amount = float(str(raw_amount).replace(",", ""))
    except:
        amount = 0.0

    # Update กลับไปที่ทุกชั้นเพื่อให้ save กลับ DB ได้ถูกต้อง
    if isinstance(real_payload, dict):
        real_payload["amount_total"] = amount
    if isinstance(root_payload, dict) and root_payload is not real_payload:
        root_payload["amount_total"] = amount

    # -------------------------------------------------
    # 2. Vendor Enrichment (Robust Extraction ✅)
    # -------------------------------------------------
    
    # พยายามดึงชื่อ Vendor จากหลายๆ Key ที่เป็นไปได้ จาก real_payload
    vendor_raw = (
        real_payload.get("vendor_name") or 
        real_payload.get("vendor_id") or 
        real_payload.get("vendor") or       # Key สำคัญใน DB
        real_payload.get("supplier") or     
        real_payload.get("partner_name") or 
        ""
    )
    
    vendor_name = str(vendor_raw).lower().strip()
    print(f"🔍 [DEBUG] Final Vendor Extracted: '{vendor_raw}' (Normalized: '{vendor_name}')")

    vendor_status = "ACTIVE"
    if "bad" in vendor_name or "blacklist" in vendor_name:
        vendor_status = "BLACKLISTED"

    vendor_rating = 95
    if "late" in vendor_name:
        vendor_rating = 55

    # 3. Budget / Fraud Context
    budget_limit = 1_000_000
    budget_remaining = budget_limit - amount
    po_count_24h = 1
    total_spend_24h = amount

    # -------------------------------------------------
    # 4. Pack Inputs (CANONICAL CONTRACT) ✅
    # -------------------------------------------------
    
    # 🔴 FIX 1: เรียกใช้ฟังก์ชันโหลดสัญญา
    contract_raw = get_contract_for_vendor(vendor_raw) 
    
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
        print(f"⚠️ [DEBUG] No contract found for vendor: '{vendor_raw}', passing empty dict to engine.")

    # 🔴 FIX 2: ส่ง contract เข้า inputs
    inputs = {
        "amount_total": amount,
        "amount": amount,
        "hours_to_sla": real_payload.get("hours_to_sla", 48),
        "vendor_status": vendor_status,
        "vendor_rating": vendor_rating,
        "budget_remaining": budget_remaining,
        "po_count_24h": po_count_24h,
        "total_spend_24h": total_spend_24h,
        "vendor_name": vendor_raw,
        "line_items": real_payload.get("line_items", []),
        
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
    new_risk = apply_threshold_safety_net(base_risk, amount, policy)

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
    # 10. Sync back to Case (SYSTEM OF RECORD)
    # -------------------------------------------------
    
    # Update ข้อมูลลงใน real_payload และ root_payload (ให้มันซิงค์กัน)
    updates = {
        "risk_level": new_risk,
        "last_decision": decision_val,
        "evaluated_at": datetime.utcnow().isoformat(),
        "last_rule_results": result["rule_results"]
    }
    
    if isinstance(real_payload, dict):
        real_payload.update(updates)
    if isinstance(root_payload, dict) and root_payload is not real_payload:
        root_payload.update(updates)

    violated_rules_list = [r["rule_id"] for r in result["rule_results"] if r["hit"]]
    
    case["decision_summary"] = {
        "decision_required": decision_val != "APPROVE",
        "risk_level": new_risk,
        "recommended_action": decision_val,
        "violated_rules": violated_rules_list,
        "reason": f"Risk detected based on {len(risk_drivers)} drivers."
    }

    case["story"] = {
        "headline": f"Why this case is {new_risk}",
        "risk_drivers": [
            {
                "label": d["rule_id"], 
                "detail": d["description"], 
                "color": "red" if d["impact"] == "CRITICAL" else "orange"
            } 
            for d in risk_drivers
        ],
        "suggested_action": {
            "title": decision_val,
            "description": "System recommendation based on policy logic."
        }
    }

    new_status = "EVALUATED"
    if decision_val == "REJECT": new_status = "EVALUATED"
    elif decision_val == "APPROVE": new_status = "APPROVED"
    
    case["status"] = new_status
    case["updated_at"] = datetime.utcnow().isoformat()

    try:
        repo = SupabaseCaseRepository()
        repo.save_case(case)
    except Exception as e:
        logger.error(f"Sync error: {e}")

    return {
        "run_id": run_id,
        "rule_results": result["rule_results"],
        "recommendation": result["recommendation"],
    }

# =====================================================
# Endpoints
# =====================================================

@router.post("/run", response_model=RunDecisionResponse)
def run_decision(req: RunDecisionRequest):
    repo = SupabaseCaseRepository()
    
    # 1. Get Payload from Repo
    payload_data = repo.get_case(req.case_id)
    if not payload_data:
        raise HTTPException(status_code=404, detail="CASE_NOT_FOUND")
    
    # 2. ✅ Get Real Metadata (from helper) to prevent Null error
    metadata = fetch_existing_metadata(req.case_id)

    # 3. Assemble Full Case
    full_case = {
        "case_id": req.case_id, 
        "payload": payload_data, 
        "status": metadata.get("status", "NEW"), 
        "domain": metadata.get("domain", "procurement"), 
        "created_at": metadata.get("created_at")
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
    
    payload_data = repo.get_case(case_id)
    if not payload_data:
        raise HTTPException(status_code=404, detail="CASE_NOT_FOUND")

    # 2. ✅ Get Real Metadata (from helper)
    metadata = fetch_existing_metadata(case_id)

    full_case = {
        "case_id": case_id, 
        "payload": payload_data, 
        "status": metadata.get("status", "NEW"),
        "domain": metadata.get("domain", "procurement"),
        "created_at": metadata.get("created_at")
    }

    policy_id = payload_data.get("policy_id") or "PROCUREMENT-001"
    policy_version = payload_data.get("policy_version") or "v3.1"

    try:
        policy = load_policy_yaml(policy_id, policy_version)
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail="Policy NOT FOUND")

    execution = execute_decision_run(
        case=full_case,
        policy=policy,
        policy_id=policy_id,
        policy_version=policy_version,
    )

    return {"status": "ok", "case_id": case_id, "run": execution}