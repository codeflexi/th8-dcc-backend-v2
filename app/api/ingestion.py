import hashlib
import os
from app.schemas.ingestion import DocumentResponse
from typing import List
from fastapi import APIRouter, UploadFile, File, HTTPException
from typing import Optional
from uuid import UUID
# Import Service และ Schema
from app.services.ingestion_service import IngestionService
from app.schemas.ingestion import IngestionResponse

# Import Storage Service (ที่เราตกลงกันว่าจะสร้างไว้ใน app/services/storage.py)
from app.services.storage import upload_file_to_supabase

# ✅ เอา tags ออก เพื่อไม่ให้ซ้ำกับตัวแม่ (app/api/router.py)
router = APIRouter()

# Helper: คำนวณ Hash ของไฟล์
def calculate_file_hash(file_content: bytes) -> str:
    sha256_hash = hashlib.sha256()
    sha256_hash.update(file_content)
    return sha256_hash.hexdigest()

# Helper: Save ไฟล์ลงเครื่องชั่วคราว (Temp) เพื่อให้ LlamaParse อ่าน
UPLOAD_DIR = "uploads_temp"
os.makedirs(UPLOAD_DIR, exist_ok=True)

async def save_temp_file(upload_file: UploadFile, file_content: bytes) -> str:
    file_path = os.path.join(UPLOAD_DIR, upload_file.filename)
    with open(file_path, "wb") as f:
        f.write(file_content)
    return file_path

@router.post("/ingest", response_model=IngestionResponse)
async def ingest_document(file: UploadFile = File(...)):
    """
    Endpoint สำหรับอัปโหลดและประมวลผลเอกสาร (PDF)
    Process: Upload Cloud -> Save Temp -> Parse -> DB -> Cleanup Temp
    """
    # 1. Validate File Type
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    temp_path = None
    
    try:
        # 2. Read Content & Calculate Hash
        content = await file.read()
        file_hash = calculate_file_hash(content)
        
        # 3. Upload to Supabase Storage (เก็บไฟล์จริง)
        # จะได้ Path กลับมา เช่น "raw_uploads/contract_2026.pdf"
        storage_path = await upload_file_to_supabase(file, content)
        
        # 4. Save to Local Temp (เก็บชั่วคราวให้ LlamaParse)
        temp_path = await save_temp_file(file, content)
        
        # 5. Initialize Service
        service = IngestionService() 
        
        # 6. Run Pipeline
        # ส่ง temp_path ไปให้แกะเนื้อหา
        # ส่ง storage_path ไปบันทึกลง Database
        result = await service.run_pipeline(
            file_bytes=content,
            filename=file.filename,
            file_path=temp_path,     # Path เครื่อง (ใช้แล้วทิ้ง)
            file_hash=file_hash,
            storage_path=storage_path # Path Cloud (เก็บถาวร)
        )
        
        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    finally:
        # 7. Clean up (ลบไฟล์ Temp ทิ้งเสมอ ไม่ว่าจะ Error หรือไม่)
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                print(f"🧹 Cleaned up temp file: {temp_path}")
            except Exception as cleanup_error:
                print(f"⚠️ Failed to cleanup temp file: {cleanup_error}")
                
                
# ✅ เพิ่ม Route GET
@router.get("/", response_model=List[DocumentResponse])
async def list_documents():
    service = IngestionService()
    return service.get_knowledge_base()

@router.get("/{doc_id}/url")
async def get_document_view_url(doc_id: UUID):
    """
    Generate presigned URL for viewing/downloading the file
    """
    try:
        service = IngestionService()
        return service.get_document_url(doc_id)
    except Exception as e:
        # ✅ เพิ่มบรรทัดนี้เพื่อดู Error จริงใน Terminal
        import traceback
        print(f"🔥 DEBUG URL ERROR: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=404, detail=str(e))