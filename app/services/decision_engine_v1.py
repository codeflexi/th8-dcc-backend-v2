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
        
        # 1. ดึง Config จาก YAML
        contract_config = policy.get("contract_compliance", {})
        max_variance = contract_config.get("max_allowed_variance_pct", 0.0)
        
        # 2. ดึงข้อมูล Contract ที่เตรียมมา (จากการ RAG/DB)
        # inputs['contract'] ควรหน้าตาประมาณ:
        # { 'is_active': True, 'prices': {'SKU-001': 100.00}, 'doc_id': '...' }
        contract_data = inputs.get("contract")
        line_items = inputs.get("line_items", [])

        print("🔍 Evaluating Print Input...")
        print(f"   - Inputs: {inputs}" )
        print(f"🔍 Evaluating Contract Compliance: config={contract_config}, contract_data={contract_data}, line_items={line_items}")
      
      
        # -----------------------------------------
        # Check 3: No Contract Reference (Rule 9) 🆕
        # -----------------------------------------
        # ถ้าไม่มีข้อมูลสัญญา หรือไม่มี Doc ID -> ถือว่าหาไม่เจอ
        if not contract_data or not contract_data.get("doc_id"):
            ctx["rule_results"].append({
                "rule_id": "NO_CONTRACT_REFERENCE",
                "description": "Item purchased without active contract reference",
                "hit": True,
                "matched": [{
                    "field": "contract_id",
                    "operator": "exists",
                    "expected": "Valid Contract",
                    "actual": "None/Missing"
                }]
            })
            ctx["_hit_rules"].append("NO_CONTRACT_REFERENCE")
            
            # ถ้าไม่มีสัญญา ก็ไม่ต้องเช็ควันหมดอายุหรือราคาต่อ -> จบ Node เลย
            return ctx
        
        
        # -----------------------------------------
        # Check 1: Contract Validity (วันหมดอายุ)
        # -----------------------------------------
        if contract_config.get("validity_check") and not contract_data.get("is_active", True):
            # สร้าง Result แบบเดียวกับ Rule ปกติ
            ctx["rule_results"].append({
                "rule_id": "CONTRACT_EXPIRED",
                "description": "Contract is expired or inactive",
                "hit": True,
                "matched": [{
                    "field": "contract_status",
                    "operator": "is_active",
                    "expected": "ACTIVE",
                    "actual": "EXPIRED/INACTIVE"
                }]
            })
            ctx["_hit_rules"].append("CONTRACT_EXPIRED")

        # -----------------------------------------
        # Check 2: Price Variance (รายสินค้า)
        # -----------------------------------------
        if contract_config.get("price_check"):
            variance_hits = []
            
            for item in line_items:
                sku = item.get("sku")
                po_price = float(item.get("unit_price", 0))
                contract_price = contract_data.get("prices", {}).get(sku)

                # ถ้าเจอราคาสัญญา
                if contract_price is not None and contract_price > 0:
                    contract_price = float(contract_price)
                    diff = po_price - contract_price
                    diff_percent = (diff / contract_price) * 100

                    # ถ้าราคาแพงกว่าเกณฑ์ที่กำหนด (เช่น 5%)
                    if diff_percent > max_variance:
                        variance_hits.append({
                            "field": f"price_{sku}",
                            "operator": f"< {max_variance}% variance",
                            "expected": contract_price,
                            "actual": f"{po_price} (+{diff_percent:.2f}%)"
                        })

            # ถ้ามีสินค้าตัวไหนผิดเงื่อนไขแม้แต่ตัวเดียว -> Trigger Rule
            if variance_hits:
                ctx["rule_results"].append({
                    "rule_id": "CONTRACT_PRICE_VARIANCE",
                    "doc_reference": contract_data.get("doc_id"), # ✅ ฝัง ID สัญญาลงไปเลย
                    "description": f"Items Unit price exceeds contract agreement by > {max_variance}%",
                    "hit": True,
                    "matched": variance_hits # ส่งรายการที่ผิดปกติออกไปให้ UI/Copilot ดู
                    
                    
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
