from pydantic import BaseModel, Field
from typing import Literal, Any, Optional, List


# -------------------------
# Enums / Literals
# -------------------------
Severity = Literal["Low", "Medium", "High"]
Domain = Literal["procurement", "invoice"]

Decision = Literal[
    "APPROVE",
    "REJECT",
    "APPROVE_WITH_EXCEPTION",
    "REQUEST_MORE_INFO",
]

CaseStatus = Literal[
    "Pending",          # rule fail / waiting human
    "Passed",           # rule pass (auto)
    "Approved",         # human approve
    "Rejected",         # human reject
    "PendingInfo",      # request more info
    "Closed",
]


# -------------------------
# Evidence / Violation
# -------------------------
class EvidenceRef(BaseModel):
    doc_id: str
    doc_name: str
    page: Optional[int] = None
    snippet: Optional[str] = None
    url: Optional[str] = None


class Violation(BaseModel):
    rule_id: str
    severity: Severity
    title: str
    pending_reason: str

    # optional quantitative info
    delta_pct: Optional[float] = None
    delta_amount: Optional[float] = None

    evidence: Optional[EvidenceRef] = None


# -------------------------
# Core Case Model
# -------------------------
class CaseItem(BaseModel):
    case_id: str
    domain: Domain
    external_id: str              # PO-..., INV-...
    status: CaseStatus = "Pending"

    severity: Severity
    amount_total: float
    currency: str = "THB"

    created_at: str
    sla_hours: int = 8

    violations: List[Violation] = Field(default_factory=list)

    # decision (filled after human action)
    decision: Optional["DecisionResult"] = None


# -------------------------
# Decision Input (API)
# -------------------------
class DecisionPayload(BaseModel):
    decision: Decision
    reason: str = Field(..., min_length=5)   # ✅ mandatory
    exception_type: Optional[str] = None


# -------------------------
# Decision Output / Stored Result
# -------------------------
class DecisionResult(BaseModel):
    case_id: str
    status: CaseStatus

    decided_by: str
    decided_at: str

    decision: Decision
    reason: str
    exception_type: Optional[str] = None


# -------------------------
# Executive KPI (Phase 3 ready)
# -------------------------
class KPIExecutive(BaseModel):
    amount_at_risk: float
    prevented_leakage: float
    pending_decisions: int
    decision_sla_pct: float

    formula_notes: dict[str, str] = Field(default_factory=dict)


# -------------------------
# Audit Trail (Phase 3 ready)
# -------------------------
class AuditEvent(BaseModel):
    event_id: str
    case_id: str
    event_type: str
    time: str
    actor: str

    payload: dict[str, Any] = Field(default_factory=dict)


# -------------------------
# Document Model
# -------------------------
class DocumentItem(BaseModel):
    doc_id: str
    name: str
    doc_type: Literal["contract", "policy", "invoice", "po", "other"]

    vendor: Optional[str] = None
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None

    status: Literal["Active", "Archived"] = "Active"
    pages: Optional[int] = None
    tags: List[str] = Field(default_factory=list)
