from __future__ import annotations
from typing import Dict, List, TypedDict, Optional, Any


# ============================================================
# Context Objects
# ============================================================

class DecisionContext(TypedDict):
    policy: Dict
    inputs: Dict
    rule_results: List[Dict]
    recommendation: Optional[Dict]
    _hit_rules: List[str]   # internal only


# ============================================================
# Node Interface
# ============================================================

class Node:
    name: str

    @staticmethod
    def run(ctx: DecisionContext) -> DecisionContext:
        raise NotImplementedError


# ============================================================
# Node 1 — Evaluate Rules (Deterministic)
# ============================================================

class EvaluateRulesNode(Node):
    name = "evaluate_rules"

    @staticmethod
    def run(ctx: DecisionContext) -> DecisionContext:
        policy = ctx["policy"]
        inputs = ctx["inputs"]

        rule_results: List[Dict] = []
        hit_rules: List[str] = []

        for rule in policy.get("rules", []):
            if rule.get("is_active") is False:
                continue
            if rule.get("type") in ["llm_semantic_check", "contract_check"]:
                continue

            rule_id = rule["id"]
            description = rule.get("description")

            hit = True
            matched: List[Dict] = []

            for cond in rule.get("when", []):
                field = cond["field"]
                operator = cond["operator"]
                expected = cond["value"]

                actual = inputs.get(field)

                ok = _safe_compare(actual, operator, expected)

                if ok:
                    matched.append({
                        "field": field,
                        "operator": operator,
                        "expected": expected,
                        "actual": actual,
                    })
                else:
                    hit = False

            rule_results.append({
                "rule_id": rule_id,
                "description": description,
                "hit": hit,
                "matched": matched if hit else [],
            })

            if hit:
                hit_rules.append(rule_id)

        ctx["rule_results"] = rule_results
        ctx["_hit_rules"] = hit_rules
        return ctx


# ============================================================
# Node 2 — Evaluate LLM Rules (Semantic)
# ============================================================

class EvaluateLLMNode(Node):
    name = "evaluate_llm_rules"

    @staticmethod
    def run(ctx: DecisionContext) -> DecisionContext:
        policy = ctx["policy"]
        inputs = ctx["inputs"]

        llm_rules = [r for r in policy.get("rules", []) if r.get("type") == "llm_semantic_check"]

        for rule in llm_rules:
            # mock semantic result
            response = {"violation": False, "reason": "Items align with vendor nature"}

            hit = bool(response.get("violation"))

            semantic_matched = [{
                "field": "llm_semantic_check",
                "operator": "violation",
                "expected": True,
                "actual": hit
            }]

            ctx["rule_results"].append({
                "rule_id": rule["id"],
                "description": rule["description"],
                "hit": hit,
                "ai_reason": response.get("reason"),
                "matched": semantic_matched,
            })

            if hit:
                ctx["_hit_rules"].append(rule["id"])

        return ctx
    
# ... (Imports และ Nodes เดิม 1-2) ...

# ============================================================
# Node 2.5 — Evaluate Contract Compliance (NEW ✅)
# ============================================================

class EvaluateContractNode(Node):
    name = "evaluate_contract"

    @staticmethod
    def run(ctx: DecisionContext) -> DecisionContext:
        policy = ctx["policy"]
        inputs = ctx["inputs"]
        
        # 1. Config
        contract_config = policy.get("contract_compliance", {})
        max_variance = contract_config.get("max_allowed_variance_pct", 0.0)
        
        # 2. Data Preparation
        contract_data = inputs.get("contract")
        
        
        line_items = inputs.get("line_items", [])

        # -----------------------------------------
        # Check 3: No Contract Reference (Rule 9)
        # -----------------------------------------
        if not contract_data or not contract_data.get("doc_id"):
            ctx["rule_results"].append({
                "rule_id": "NO_CONTRACT_REFERENCE",
                "description": "Item purchased without active contract reference",
                "hit": True,
                "severity": "HIGH", # 🔴 เพิ่ม Severity
                "matched": [{
                    "field": "contract_id",
                    "operator": "exists",
                    "expected": "Valid Contract",
                    "actual": "None/Missing"
                }],
                # 📸 Snapshot: บันทึกว่าตอนนั้น Vendor คือใคร
                "inputs_snapshot": {
                    "vendor_id": inputs.get("vendor_id"),
                    "po_items_count": len(line_items)
                }
            })
            ctx["_hit_rules"].append("NO_CONTRACT_REFERENCE")
            return ctx
        
        # เก็บ Doc ID ไว้ใช้ซ้ำ
        doc_id = contract_data.get("doc_id")
        

        # -----------------------------------------
        # Check 1: Contract Validity
        # -----------------------------------------
        if contract_config.get("validity_check") and not contract_data.get("is_active", True):
            ctx["rule_results"].append({
                "rule_id": "CONTRACT_EXPIRED",
                "description": f"Contract {doc_id} is expired or inactive",
                "hit": True,
                "severity": "CRITICAL", # 🔴
                "doc_reference": doc_id, # ✅ ระบุเอกสารที่ผิด
                "matched": [{
                    "field": "contract_status",
                    "operator": "is_active",
                    "expected": "ACTIVE",
                    "actual": "EXPIRED/INACTIVE"
                }],
                # 📸 Snapshot: วันที่หมดอายุ vs วันที่สั่งซื้อ
                "inputs_snapshot": {
                    "doc_id": doc_id,
                    "contract_end_date": contract_data.get("end_date"),
                    "po_date": inputs.get("created_at")
                }
            })
            ctx["_hit_rules"].append("CONTRACT_EXPIRED")

        # -----------------------------------------
        # Check 2: Price Variance (หัวใจสำคัญ)
        # -----------------------------------------
        if contract_config.get("price_check"):
            variance_hits = []
            snapshot_items = {} # เก็บข้อมูลดิบรายตัว
           
            
            for item in line_items:
                sku = item.get("sku")
                po_price = float(item.get("unit_price", 0))
                
               
                # สมมติ contract_data['prices'] เก็บราคามาตรฐานไว้
                item_data = contract_data["contract_items"].get(sku)
                
            if item_data :
                contract_price = item_data.get("price") if item_data else None # ดึงราคาจากสัญญา
                # page_num = item_data["evidence"]["page"]
                # score = item_data["evidence"]["score"]
                

                if contract_price is not None and contract_price > 0:
                    contract_price = float(contract_price)
                    diff = po_price - contract_price
                    diff_percent = (diff / contract_price) * 100

                    # ถ้าราคาสูงเกินเกณฑ์
                    if diff_percent > max_variance:
                        # 1. สร้างรายการที่ Match ผิดปกติ (สำหรับแสดงผลย่อๆ)
                        variance_hits.append({
                            "field": f"price_{sku}",
                            "operator": f"variance > {max_variance}%",
                            "expected": contract_price,
                            "actual": po_price,
                            "variance_pct": round(diff_percent, 2),
                            "note": f"(>{round(diff_percent, 2)}%)"
                        })

                        # 2. เก็บ Snapshot รายตัว (สำคัญมากสำหรับ Audit/Copilot)
                        # เพื่อให้ Copilot ตอบได้ว่า "SKU A ราคา 120 (Contract 100)"
                        snapshot_items[sku] = {
                            "po_price": po_price,
                            "contract_price": contract_price,
                            "currency": item.get("currency", "THB"),
                            "evidence_meta": item_data.get("evidence", {}) # (ถ้ามี),
                            
                            #"clause_ref": contract_data.get("clause_map", {}).get(sku) # (ถ้ามี)
                        }

            if variance_hits:
                ctx["rule_results"].append({
                    "rule_id": "CONTRACT_PRICE_VARIANCE",
                    "doc_reference": doc_id,
                    "description": f"Items Unit price exceeds contract agreement by > {max_variance}%",
                    "hit": True,
                    "severity": "CRITICAL", # 🔴
                    "matched": variance_hits,
                    
                    # 📸 Snapshot: รวมข้อมูลทั้งหมดที่ใช้ตัดสินใจใน Rule นี้
                    "inputs_snapshot": {
                        "doc_id": doc_id,
                        "max_variance_allowed": max_variance,
                        "failed_items": snapshot_items # <-- ใส่ข้อมูลละเอียดที่นี่
                    }
                })
                ctx["_hit_rules"].append("CONTRACT_PRICE_VARIANCE")

        return ctx


# ============================================================
# Node 3 — Recommend Decision (ROBUST)
# ============================================================

class RecommendDecisionNode(Node):
    name = "recommend_decision"

    @staticmethod
    def run(ctx: DecisionContext) -> DecisionContext:
        policy = ctx["policy"]
        inputs = ctx["inputs"]
        hit_rules = ctx["_hit_rules"]

        # -----------------------------------------
        # 1) Build rule → decision map from policy
        # -----------------------------------------
        rule_decision_map: Dict[str, str] = {}

        for r in policy.get("rules", []):
            rid = r.get("id")
            dec = r.get("then", {}).get("decision")
            if rid and dec:
                rule_decision_map[rid] = dec

        # -----------------------------------------
        # 2) Collect decisions from HIT rules
        # -----------------------------------------
        hit_decisions: List[str] = []

        for rid in hit_rules:
            # 2.1 policy-driven
            if rid in rule_decision_map:
                hit_decisions.append(rule_decision_map[rid])
                continue

            # 2.2 fallback convention (for old policies / tests)
            if rid.startswith(("VENDOR_", "BUDGET_")):
                hit_decisions.append("REJECT")
            elif rid.startswith(("HIGH_", "POTENTIAL_")):
                hit_decisions.append("ESCALATE")
            elif rid.startswith(("SLA_",)):
                hit_decisions.append("REVIEW")

        # -----------------------------------------
        # 3) Decision Priority
        # -----------------------------------------
        # REJECT > ESCALATE > REVIEW > APPROVE
        if "REJECT" in hit_decisions:
            decision = "REJECT"
        elif "ESCALATE" in hit_decisions:
            decision = "ESCALATE"
        elif "REVIEW" in hit_decisions:
            decision = "REVIEW"
        else:
            decision = "APPROVE"

        # -----------------------------------------
        # 4) Authority
        # -----------------------------------------
        required_role = _derive_required_role(policy, inputs)

        # -----------------------------------------
        # 5) Risk context (safe extension)
        # -----------------------------------------
        risk_factors = []
        if decision == "ESCALATE":
            risk_factors.append("RULE_ESCALATION")
        if decision == "REJECT":
            risk_factors.append("RULE_REJECTION")

        ctx["recommendation"] = {
            "decision": decision,
            "required_role": required_role,
            "reason_codes": hit_rules,
            "risk_factors": risk_factors,
        }

        return ctx


# ============================================================
# Decision Engine
# ============================================================

class DecisionEngine:
    NODES = [
        EvaluateRulesNode,
        EvaluateLLMNode,
        EvaluateContractNode,
        RecommendDecisionNode,
    ]

    @classmethod
    def evaluate(cls, *, policy: Dict, inputs: Dict) -> Dict:
        ctx: DecisionContext = {
            "policy": policy,
            "inputs": inputs,
            "rule_results": [],
            "recommendation": None,
            "_hit_rules": [],
        }

        for node in cls.NODES:
            ctx = node.run(ctx)

        return {
            "rule_results": ctx["rule_results"],
            "recommendation": ctx["recommendation"],
        }


# ============================================================
# Helpers
# ============================================================

def _safe_compare(actual: Any, operator: str, expected: Any) -> bool:
    if actual is None:
        return False

    try:
        if operator == ">":
            return actual > expected
        if operator == ">=":
            return actual >= expected
        if operator == "<":
            return actual < expected
        if operator == "<=":
            return actual <= expected
        if operator == "==":
            return actual == expected
        if operator == "!=":
            return actual != expected
        if operator == "in":
            return actual in expected
        if operator == "not_in":
            return actual not in expected
        if operator == "contains":
            return expected in actual
    except TypeError:
        return False

    return False


def _derive_required_role(policy: Dict, inputs: Dict) -> str:
    for rule in policy.get("authority", {}).get("rules", []):
        condition = rule["condition"]
        role = rule["required_role"]

        field, operator, value = condition.split()
        actual = inputs.get(field)

        if actual is None:
            continue

        try:
            value = float(value)
        except ValueError:
            continue

        if _safe_compare(actual, operator, value):
            return role

    return "Procurement_Manager"
