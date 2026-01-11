from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from openai import OpenAI

from app.services.evidence_retriever import EvidenceRetriever
from app.services.audit_service import AuditService


# ======================
# OpenAI client (lazy)
# ======================

def get_openai_client() -> OpenAI:
    # client ถูกสร้างตอนเรียกใช้งานจริง
    return OpenAI()


router = APIRouter(tags=["evidence"])


# ============================================================
# Schemas — Suggest Evidence
# ============================================================

class EvidenceSuggestRequest(BaseModel):
    query: str
    policy_id: Optional[str] = None
    limit: int = 5


class EvidenceItem(BaseModel):
    doc_id: str
    title: str
    uri: str
    page_start: int
    page_end: int
    clause_id: Optional[str]
    section_path: Optional[str]
    content: str
    score: float


class EvidenceSuggestResponse(BaseModel):
    query: str
    items: List[EvidenceItem]


# ============================================================
# Endpoint — /evidence/suggest  (เดิม / ห้ามกระทบ)
# ============================================================

@router.post("/suggest", response_model=EvidenceSuggestResponse)
def suggest_evidence(req: EvidenceSuggestRequest):
    client = get_openai_client()

    emb = client.embeddings.create(
        model="text-embedding-3-small",  # ต้องตรงกับ vector(1536)
        input=req.query,
    ).data[0].embedding

    # Vector search
    retriever = EvidenceRetriever()
    rows = retriever.search(
        query_embedding=emb,
        policy_id=req.policy_id,
        limit=req.limit,
    )

    # Shape response for UI
    items = []
    for r in rows:
        items.append({
            "doc_id": r["doc_id"],
            "title": r["title"],
            "uri": r["uri"],
            "page_start": r["page_start"],
            "page_end": r["page_end"],
            "clause_id": r.get("clause_id"),
            "section_path": r.get("section_path"),
            "content": r["content"],
            "score": r.get("similarity", 0),
        })

    return {
        "query": req.query,
        "items": items,
    }


# ============================================================
# Schemas — Attach Evidence (Phase C1)
# ============================================================

class EvidenceAttachItem(BaseModel):
    doc_id: str
    title: str
    uri: str
    page_start: int
    page_end: int
    clause_id: Optional[str] = None
    section_path: Optional[str] = None
    score: Optional[float] = None


class EvidenceAttachRequest(BaseModel):
    case_id: str
    policy_id: str
    source: str  # e.g. "vector_search"
    evidence: List[EvidenceAttachItem]


class EvidenceAttachResponse(BaseModel):
    status: str
    event_type: str
    case_id: str
    evidence_count: int


# ============================================================
# Endpoint — /evidence/attach  (ใหม่ / backend-only)
# ============================================================

@router.post("/attach", response_model=EvidenceAttachResponse)
def attach_evidence(req: EvidenceAttachRequest):
    if not req.evidence:
        raise HTTPException(status_code=400, detail="NO_EVIDENCE_PROVIDED")

    # Audit only — immutable fact
    AuditService.write(
        event_type="EVIDENCE_ATTACHED",
        actor="SYSTEM",
        payload={
            "case_id": req.case_id,
            "policy_id": req.policy_id,
            "source": req.source,
            "evidence": [e.dict() for e in req.evidence],
        },
    )

    return {
        "status": "ok",
        "event_type": "EVIDENCE_ATTACHED",
        "case_id": req.case_id,
        "evidence_count": len(req.evidence),
    }
