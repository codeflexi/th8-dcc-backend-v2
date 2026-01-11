from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4
from typing import Optional, Dict


@dataclass
class DecisionRunContext:
    """
    Represents ONE decision attempt (audit-grade).
    - Immutable identity (run_id)
    - Append-only usage (no overwrite)
    """
    run_id: str
    case_id: str
    policy_id: str
    policy_version: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    decision: Optional[str] = None
    required_role: Optional[str] = None

    # Optional metadata (safe extension point)
    meta: Dict = None

    @classmethod
    def start(
        cls,
        *,
        case_id: str,
        policy_id: str,
        policy_version: str,
        meta: Optional[Dict] = None,
    ) -> "DecisionRunContext":
        return cls(
            run_id=str(uuid4()),
            case_id=case_id,
            policy_id=policy_id,
            policy_version=policy_version,
            started_at=datetime.utcnow(),
            meta=meta or {},
        )

    def complete(
        self,
        *,
        decision: str,
        required_role: Optional[str] = None,
    ) -> None:
        """
        Mark run as completed (in-memory only).
        Audit persistence is handled elsewhere.
        """
        self.decision = decision
        self.required_role = required_role
        self.ended_at = datetime.utcnow()
