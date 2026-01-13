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

# ✅ เพิ่ม Schema สำหรับ Story
class StoryEvidence(BaseModel):
    title: str
    subtitle: str
    description: str
    source_code: str # e.g. doc_id=...
    
# ✅ 2. เพิ่ม Schema หลักสำหรับ Story (ต้องอยู่ก่อน CaseDetail)
class CaseStory(BaseModel):
    headline: str            # e.g. "Why this case is CRITICAL"
    risk_drivers: List[dict] # { "label": "Vendor Blacklisted", "detail": "...", "color": "red" }
    business_impact: List[str]
    suggested_action: dict   # { "title": "Hold & Escalate", "description": "..." }
    evidence_list: List[StoryEvidence]
    
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
    story: Optional[CaseStory] = None  # <-- เพิ่มบรรทัดนี้

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