# CaseList Portfolio item schema
from typing import Optional
from pydantic import BaseModel

class CasePortfolioItem(BaseModel):
    id: str
    domain: str

    vendor_id: Optional[str]
    amount_total: float

    status: str
    pending_reason: Optional[str]

    priority_score: Optional[int] = None   # 0–100
    priority_reason: Optional[str] = None

    created_at: str
