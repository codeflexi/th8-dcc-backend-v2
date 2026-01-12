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
            if rule.get("type") == "llm_semantic_check":
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
