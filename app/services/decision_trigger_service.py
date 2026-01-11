from datetime import datetime
import uuid

from app.services.policy_loader import PolicyLoader
from app.services.audit_service import AuditService
from app.services.evidence_service import EvidenceService


class DecisionTriggerService:
    """
    Responsibility:
    - Orchestrate decision lifecycle
    - Bind case + policy + context
    - Produce explainable, deterministic decision output
    - Bind supporting evidence (RAG-as-Evidence)
    - Write immutable audit trail
    """

    @staticmethod
    def trigger(case: dict, policy_ref: dict) -> dict:
        """
        case: normalized case context (must include case_id)
        policy_ref: { policy_id, version }
        """

        # ---- Load Policy (immutable binding) ----
        policy = PolicyLoader.load(
            policy_id=policy_ref["policy_id"],
            version=policy_ref["version"],
        )

        decision_id = f"DEC-{uuid.uuid4().hex[:8]}"
        evaluated_at = datetime.utcnow().isoformat()

        decision = {
            "decision_id": decision_id,
            "case_id": case.get("case_id"),
            "decision_required": False,
            "recommended_decision": "NO_ACTION",
            "required_role": None,
            "rule_hits": [],
            "policy_id": policy["policy_id"],
            "policy_version": policy["version"],
            "evaluated_at": evaluated_at,
            "evidence": [],  # will be populated below
        }

        # ---- Evaluate rules deterministically ----
        for rule in policy.get("rules", []):
            if DecisionTriggerService._match_rule(case, rule.get("when", [])):
                decision["decision_required"] = True
                decision["recommended_decision"] = rule["then"]["decision"]
                decision["rule_hits"].append(rule["id"])

        # ---- Resolve authority (who must decide) ----
        decision["required_role"] = DecisionTriggerService._resolve_authority(
            case, policy
        )

        # ---- Retrieve Evidence (RAG-as-Evidence) ----
        evidence = EvidenceService.find_evidence(case, policy)
        decision["evidence"] = evidence

        # ---- Write audit log (immutable) ----
        AuditService.write(
            event_type="DECISION_RECOMMENDED",
            payload={
                "case_id": decision["case_id"],
                "decision_id": decision_id,
                "policy_id": decision["policy_id"],
                "policy_version": decision["policy_version"],
                "recommended_decision": decision["recommended_decision"],
                "required_role": decision["required_role"],
                "rule_hits": decision["rule_hits"],
                "evidence": decision["evidence"],
                "evaluated_at": evaluated_at,
            },
            actor="SYSTEM",
        )

        return decision

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _match_rule(case: dict, conditions: list) -> bool:
        """
        All conditions must match (AND logic)
        """
        for cond in conditions:
            field = cond["field"]
            op = cond["operator"]
            value = cond["value"]

            case_value = case.get(field)
            if case_value is None:
                return False

            if op == ">" and not case_value > value:
                return False
            if op == "<" and not case_value < value:
                return False
            if op == "==" and not case_value == value:
                return False

        return True

    @staticmethod
    def _resolve_authority(case: dict, policy: dict) -> str:
        """
        Determine required role based on authority rules.
        First match wins.
        """
        for rule in policy.get("authority", {}).get("rules", []):
            condition = rule.get("condition")
            try:
                if condition and eval(condition, {}, case):
                    return rule["required_role"]
            except Exception:
                continue

        return "SYSTEM"
