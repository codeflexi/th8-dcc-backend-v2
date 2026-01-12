from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, List, Any
import yaml
import uuid
import logging
from pathlib import Path
from datetime import datetime

from app.services.audit_service import AuditService
from app.services.decision_engine import DecisionEngine
from app.repositories.supabase_repo import SupabaseCaseRepository

logger = logging.getLogger("decisions_api")
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

def fmt_num(val: Any) -> str:
    try:
        if val is None:
            return "None"
        return "{:,.2f}".format(float(val))
    except:
        return str(val)


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
    """
    Build list of risk drivers from rules that HIT
    using risk_impact defined in policy.
    """
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
    """
    Pick highest priority impact from drivers.
    """
    if not drivers:
        return "LOW"

    impacts = [d["impact"] for d in drivers]

    for p in RISK_PRIORITY:
        if p in impacts:
            return p

    return "LOW"


def apply_threshold_safety_net(
    current_risk: str,
    amount: float,
    policy: Dict
) -> str:
    """
    Apply thresholds + safety net from policy.config / policy.thresholds
    """
    risk = current_risk

    # amount thresholds
    thresholds = policy.get("thresholds", {}).get("amount", {})
    high_th = thresholds.get("high")
    med_th = thresholds.get("medium")

    if high_th is not None and amount >= high_th:
        risk = "HIGH"
    elif med_th is not None and amount >= med_th:
        if risk == "LOW":
            risk = "MEDIUM"

    # safety net
    config = policy.get("config", {})
    force_th = config.get("high_risk_threshold")
    force_level = config.get("force_risk_level", "HIGH")

    try:
        if force_th is not None and amount > float(force_th):
            risk = force_level
    except:
        pass

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
    vendor_raw = payload.get("vendor_name") or payload.get("vendor_id") or ""
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
    # 4. Pack Inputs (CANONICAL CONTRACT)
    # -------------------------------------------------
    inputs = {
        "amount_total": amount,
        "amount": amount,  # backward compatibility
        "hours_to_sla": payload.get("hours_to_sla", 48),
        "vendor_status": vendor_status,
        "vendor_rating": vendor_rating,
        "budget_remaining": budget_remaining,
        "po_count_24h": po_count_24h,
        "total_spend_24h": total_spend_24h,
        "vendor_name": vendor_raw,
        "line_items": payload.get("line_items", []),
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

        rr["matched"] = conditions_to_check

        for m in conditions_to_check:
            field = m.get("field")
            operator = m.get("operator")
            expected = m.get("expected")
            actual = m.get("actual")

            act_str = fmt_num(actual)
            exp_str = fmt_num(expected)

            is_true = False
            try:
                a = float(actual)
                b = float(expected)
                if operator == ">": is_true = a > b
                elif operator == "<": is_true = a < b
                elif operator == ">=": is_true = a >= b
                elif operator == "<=": is_true = a <= b
                elif operator == "==": is_true = a == b
                elif operator == "!=": is_true = a != b
            except:
                if operator == "==": is_true = str(actual) == str(expected)
                elif operator == "!=": is_true = str(actual) != str(expected)

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
    # 10. Sync back to Case (SYSTEM OF RECORD)
    # -------------------------------------------------
    payload["risk_level"] = new_risk
    payload["last_decision"] = decision_val
    payload["evaluated_at"] = datetime.utcnow().isoformat()
    payload["last_rule_results"] = result["rule_results"]

    new_status = "EVALUATED"
    if decision_val == "REJECT":
        new_status = "REJECTED"
    elif decision_val == "APPROVE":
        new_status = "APPROVED"

    try:
        repo = SupabaseCaseRepository()
        case["status"] = new_status
        case["updated_at"] = datetime.utcnow().isoformat()
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
    case = repo.get_case(req.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="CASE_NOT_FOUND")

    try:
        policy = load_policy_yaml(req.policy_id, req.policy_version)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    execution = execute_decision_run(
        case=case,
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
    if not case:
        raise HTTPException(status_code=404, detail="CASE_NOT_FOUND")

    policy_id = case.get("policy_id") or "PROCUREMENT-001"
    policy_version = case.get("policy_version") or "v3.1"

    case["policy_id"] = policy_id
    case["policy_version"] = policy_version
    repo.save_case(case)

    try:
        policy = load_policy_yaml(policy_id, policy_version)
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail="Policy NOT FOUND")

    execution = execute_decision_run(
        case=case,
        policy=policy,
        policy_id=policy_id,
        policy_version=policy_version,
    )

    return {"status": "ok", "case_id": case_id, "run": execution}
