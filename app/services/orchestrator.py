from app.domain.decisions.run_context import DecisionRunContext

from app.services.audit_service import AuditService
from app.services.decision_engine import DecisionEngine
from app.services.evidence_service import EvidenceService


class DecisionOrchestrator:
    """
    Orchestrates a full decision run (audit-grade, append-only)
    """

    def __init__(self):
        self.decision_engine = DecisionEngine()
        self.evidence_service = EvidenceService()

    def run_decision(self, *, case: dict, policy: dict) -> dict:
        """
        Execute a single decision run

        Returns:
        {
            run_id,
            decision,
            required_role
        }
        """

        # 1️⃣ Start run context (no side effects)
        run = DecisionRunContext.start(
            case_id=case["id"],
            policy_id=policy["policy_id"],
            policy_version=policy["version"],
        )

        AuditService.write(
            event_type="DECISION_RUN_STARTED",
            payload={
                "case_id": case["id"],
                "run_id": run.run_id,
                "policy_id": run.policy_id,
                "policy_version": run.policy_version,
            },
        )

        # 2️⃣ Rule evaluation
        rule_results = self.decision_engine.evaluate(case, policy)

        for r in rule_results:
            AuditService.write(
                event_type="RULE_EVALUATED",
                payload={
                    "case_id": case["id"],
                    "run_id": run.run_id,
                    "rule_id": r.rule_id,
                    "description": r.description,
                    "inputs": r.inputs,
                    "hit": r.hit,
                },
            )

        # 3️⃣ Recommendation
        recommendation = self.decision_engine.recommend(rule_results)

        AuditService.write(
            event_type="DECISION_RECOMMENDED",
            payload={
                "case_id": case["id"],
                "run_id": run.run_id,
                "decision": recommendation.decision,
                "required_role": recommendation.required_role,
                "reason_codes": recommendation.reason_codes,
                "policy": {
                    "policy_id": run.policy_id,
                    "version": run.policy_version,
                },
            },
        )

        # 4️⃣ Evidence attachment (RAG-as-evidence)
        evidences = self.evidence_service.retrieve(case, policy)

        if evidences:
            AuditService.write(
                event_type="EVIDENCE_ATTACHED",
                payload={
                    "case_id": case["id"],
                    "run_id": run.run_id,
                    "source": "vector_search",
                    "policy_id": run.policy_id,
                    "evidence": evidences,
                },
            )

        # 5️⃣ Complete run (in-memory only)
        run.complete(
            decision=recommendation.decision,
            required_role=recommendation.required_role,
        )

        AuditService.write(
            event_type="DECISION_RUN_COMPLETED",
            payload={
                "case_id": case["id"],
                "run_id": run.run_id,
                "decision": run.decision,
                "required_role": run.required_role,
            },
        )

        return {
            "run_id": run.run_id,
            "decision": run.decision,
            "required_role": run.required_role,
        }
