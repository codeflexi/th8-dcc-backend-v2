from typing import List, Dict


class DecisionStatusService:
    """
    Derive decision status from audit events.
    No state stored. Fully deterministic.
    """

    @staticmethod
    def derive(audit_events: List[Dict]) -> Dict:
        """
        Returns:
        {
          status: str,
          decided_at: Optional[str],
          decided_by: Optional[str],
          reason: Optional[str]
        }
        """

        status = "NO_DECISION"
        decided_at = None
        decided_by = None
        reason = None

        for ev in audit_events:
            et = ev["event_type"]
            payload = ev["payload"]

            if et == "DECISION_RECOMMENDED":
                status = "PENDING"

            elif et == "DECISION_APPROVED":
                status = "APPROVED"
                decided_at = ev["timestamp"]
                decided_by = payload.get("actor_role")
                reason = payload.get("reason")

            elif et == "DECISION_REJECTED":
                status = "REJECTED"
                decided_at = ev["timestamp"]
                decided_by = payload.get("actor_role")
                reason = payload.get("reason")

            elif et == "DECISION_OVERRIDDEN":
                status = "OVERRIDDEN"
                decided_at = ev["timestamp"]
                decided_by = payload.get("actor_role")
                reason = payload.get("reason")

        return {
            "status": status,
            "decided_at": decided_at,
            "decided_by": decided_by,
            "reason": reason,
        }
