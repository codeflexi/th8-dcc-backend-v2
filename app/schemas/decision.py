from typing import List, Optional
from pydantic import BaseModel


class DecisionSummary(BaseModel):
    """
    Phase 4:
    - Read-only
    - Used only for UI explanation
    - No action / mutation
    """

    decision_required: bool
    decision_reason: Optional[str] = None

    violated_rules: List[str] = []
    risk_level: Optional[str] = None  # LOW | MEDIUM | HIGH

    recommended_action: Optional[str] = None  # APPROVE | REJECT | REVIEW
