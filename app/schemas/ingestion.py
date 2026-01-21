from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from datetime import datetime
from uuid import UUID

# ============================================================
# 1. Internal / DB Schemas (ใช้ภายใน Service/Repo)
# ============================================================

class DocumentChunk(BaseModel):
    """Schema สำหรับท่อนข้อความ (Chunk) ที่จะถูก Embed"""
    content: str
    embedding: List[float]
    metadata: Dict[str, Any] = {}

class UniversalItem(BaseModel):
    """Schema สำหรับรายการสินค้าในตาราง (Table Items)"""
    item_index: int
    item_data: Dict[str, Any] # e.g. {"col_0": "ITEM-A", "col_1": "100"}
    item_embedding: Optional[List[float]] = None

# ============================================================
# 2. Read Schemas (สำหรับแสดงผลข้อมูลเอกสาร)
# ============================================================

class DocumentDetail(BaseModel):
    """
    Schema หลักสำหรับแสดงรายละเอียดเอกสาร (คล้าย CaseDetail)
    Map กับตาราง 'sense_documents'
    """
    id: str
    filename: str
    file_hash: str
    file_path: str
    
    status: str  # processing, completed, failed
    domain: Optional[str] = None
    
    metadata: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

# ============================================================
# 3. API Response Schemas (สำหรับ Return กลับไปหน้าบ้าน)
# ============================================================

class IngestionResponse(BaseModel):
    """
    Response ที่ส่งกลับหลังจาก Upload & Ingest เสร็จสิ้น
    """
    status: str          # "success", "exists", "failed"
    doc_id: str
    domain: Optional[str] = "general"
    data: Optional[Dict[str, Any]] = None # Metadata ที่ AI แกะได้
    message: Optional[str] = None         # e.g. "File already processed"
    
# ✅ เพิ่ม Class นี้
class DocumentResponse(BaseModel):
    id: UUID
    file_name: str
    file_path: Optional[str] = None
    domain: str
    status: str
    created_at: datetime
    
    vector_count: int
    metadata: Dict[str, Any] = {} # ✅ รองรับ Metadata

    class Config:
        from_attributes = True