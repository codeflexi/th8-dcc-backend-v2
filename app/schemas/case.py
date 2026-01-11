# Case detail schema
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from app.schemas.decision import DecisionSummary

class Violation(BaseModel):
    rule_id: str
    rule_name: str
    severity: str
    delta_pct: Optional[float] = None
    delta_amount: Optional[float] = None
    amount: Optional[float] = None

class CaseDetail(BaseModel):
    id: str
    domain: str

    vendor_id: Optional[str]
    amount_total: float

    status: str
    pending_reason: Optional[str]

    priority_score: Optional[int] = None
    priority_reason: Optional[str] = None

    violations: List[Violation] = []

        # 🔹 ADD THIS (Phase 4 read-only)
    decision_summary: Optional[DecisionSummary] = None

    created_at: str
    evaluated_at: Optional[str]

    raw: Optional[Dict[str, Any]] = None

class CaseCreate(BaseModel):
    case_id: str
    domain: Optional[str] = "procurement"
    vendor_id: Optional[str]
    amount_total: Optional[float]
    status: Optional[str] = "Pending"
    pending_reason: Optional[str]
    priority_score: Optional[int]
    priority_reason: Optional[str]