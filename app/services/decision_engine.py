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
# Node 1 — Evaluate Rules
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
# Node 2 — Recommend Decision
# ============================================================

class RecommendDecisionNode(Node):
    name = "recommend_decision"

    @staticmethod
    def run(ctx: DecisionContext) -> DecisionContext:
        policy = ctx["policy"]
        inputs = ctx["inputs"]
        hit_rules = ctx["_hit_rules"]

        decision = "ESCALATE" if hit_rules else "APPROVE"
        reason_codes = hit_rules

        required_role = _derive_required_role(policy, inputs)

        ctx["recommendation"] = {
            "decision": decision,
            "required_role": required_role,
            "reason_codes": reason_codes,
        }

        return ctx

class EvaluateLLMNode(Node):
    name = "evaluate_llm_rules"

    @staticmethod
    def run(ctx: DecisionContext) -> DecisionContext:
        policy = ctx["policy"]
        inputs = ctx["inputs"]
        
        # 1. หา Rule ที่เป็น type: llm_semantic_check
        llm_rules = [r for r in policy.get("rules", []) if r.get("type") == "llm_semantic_check"]
        
        for rule in llm_rules:
            # 2. เตรียม Prompt
            prompt = f"""
            Analyze this procurement case:
            Vendor: {inputs.get('vendor_name')}
            Items: {inputs.get('line_items')}
            
            Rule: {rule['description']}
            
            Answer strictly in JSON: {{"violation": boolean, "reason": "string"}}
            """
            
            # 3. Call LLM Service (OpenAI / Local LLM)
            # response = LLMService.complete(prompt)
            # mock response for now:
            response = {"violation": False, "reason": "Items align with vendor nature"}
            
            # 4. Append Result
            ctx["rule_results"].append({
                "rule_id": rule["id"],
                "description": rule["description"],
                "hit": response["violation"],
                "ai_reason": response["reason"],
                "matched": []  # <--- ✅ ใส่บรรทัดนี้เพิ่มเข้าไปครับ
            })
            
            if response["violation"]:
                ctx["_hit_rules"].append(rule["id"])
                
        return ctx

# ============================================================
# Decision Engine (Graph-ready)
# ============================================================

class DecisionEngine:
    NODES = [
        EvaluateRulesNode,
        EvaluateLLMNode,
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
# Helper Functions (FAIL-SAFE)
# ============================================================

def _safe_compare(actual: Any, operator: str, expected: Any) -> bool:
    """
    Enterprise-safe comparison:
    - Never raises
    - Missing / invalid input → rule NOT hit
    """

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
    except TypeError:
        # type mismatch → rule not applicable
        return False

    # unknown operator → rule not applicable
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
