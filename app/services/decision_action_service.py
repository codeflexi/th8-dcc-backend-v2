from datetime import datetime

from app.services.audit_service import AuditService


class DecisionActionService:
    """
    Handle human-in-the-loop actions:
    - Approve
    - Reject

    This service does NOT re-evaluate decision.
    It only records human action as audit events.
    """

    @staticmethod
    def approve(
        decision_id: str,
        case_id: str,
        actor_role: str,
        reason: str | None = None,
    ):
        return DecisionActionService._record_action(
            action="APPROVED",
            decision_id=decision_id,
            case_id=case_id,
            actor_role=actor_role,
            reason=reason,
        )

    @staticmethod
    def reject(
        decision_id: str,
        case_id: str,
        actor_role: str,
        reason: str,
    ):
        if not reason:
            raise ValueError("Reject action requires a reason")

        return DecisionActionService._record_action(
            action="REJECTED",
            decision_id=decision_id,
            case_id=case_id,
            actor_role=actor_role,
            reason=reason,
        )

    @staticmethod
    def _record_action(
        action: str,
        decision_id: str,
        case_id: str,
        actor_role: str,
        reason: str | None,
    ):
        payload = {
            "case_id": case_id,
            "decision_id": decision_id,
            "action": action,
            "actor_role": actor_role,
            "reason": reason,
            "acted_at": datetime.utcnow().isoformat(),
        }

        AuditService.write(
            event_type=f"DECISION_{action}",
            payload=payload,
            actor=actor_role,
        )

        return payload
