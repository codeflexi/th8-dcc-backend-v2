from typing import Dict, Any, List, Optional
from app.db.supabase_client import supabase
# Import Interface ที่เราสร้างไว้
from app.repositories.base_ingestion import IngestionRepository 

class SupabaseIngestionRepository(IngestionRepository):
    """
    Implementation จริงโดยใช้ Supabase
    """

    def create_document(self, filename: str, file_hash: str, file_path: str) -> str:
        res = supabase.table("sense_documents").insert({
            "filename": filename,
            "file_hash": file_hash,
            "file_path": file_path,
            "status": "processing"
        }).execute()
        return res.data[0]['id']

    def update_document_status(self, doc_id: str, status: str, error_message: Optional[str] = None, metadata: Optional[Dict] = None):
        data = {"status": status}
        if error_message:
            data["error_message"] = error_message
        if metadata:
            data["metadata"] = metadata
        supabase.table("sense_documents").update(data).eq("id", doc_id).execute()

    def update_document_domain(self, doc_id: str, domain: str):
        supabase.table("sense_documents").update({"domain": domain}).eq("id", doc_id).execute()

    def insert_chunk(self, doc_id: str, content: str, embedding: List[float], metadata: Dict):
        supabase.table("sense_document_chunks").insert({
            "document_id": doc_id,
            "content": content,
            "embedding": embedding,
            "metadata": metadata
        }).execute()

    def insert_universal_items(self, items: List[Dict]):
        if not items:
            return
        supabase.table("sense_universal_document_items").insert(items).execute()
        
    def check_duplicate(self, file_hash: str) -> Optional[Dict]:
        res = supabase.table("sense_documents").select("*").eq("file_hash", file_hash).eq("status", "completed").execute()
        if res.data:
            return res.data[0]
        return None