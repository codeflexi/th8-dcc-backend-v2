from typing import List, Optional, Dict, Any
from datetime import datetime
from uuid import UUID


# Import Base Class เดิม (สำหรับ Case)
from app.repositories.base import CaseRepository

# ✅ Import Interface ใหม่สำหรับ Ingestion (เพื่อให้เป็น Clean Architecture)
from app.repositories.base_ingestion import IngestionRepository

# Import Global Supabase Client
from app.db.supabase_client import supabase


class SupabaseCaseRepository(CaseRepository):
    """
    Supabase (Postgres) implementation of CaseRepository
    Used for Case Management, Decision Engine, and Audit Logs.
    """

    # -------------------------
    # List cases (portfolio)
    # -------------------------
    def list_cases(self) -> List[dict]:
        res = (
            supabase
            .table("cases")
            .select("case_id, domain, status, created_at, payload")
            .execute()
        )

        items: List[dict] = []

        for r in (res.data or []):
            payload = r.get("payload") or {}

            # Ensure required metadata exists in payload
            payload.setdefault("case_id", r.get("case_id"))
            payload.setdefault("domain", r.get("domain"))
            payload.setdefault("status", r.get("status"))
            payload.setdefault("created_at", r.get("created_at"))
            payload.setdefault("risk_level", r.get("risk_level"))

            items.append(payload)

        return items

    # -------------------------
    # Get single case
    # -------------------------
    def get_case(self, case_id: str) -> Optional[dict]:
        res = (
            supabase
            .table("cases")
            .select("payload")
            .eq("case_id", case_id)
            .maybe_single()
            .execute()
        )

        if not res or not res.data:
            return None

        return res.data.get("payload")

    # -------------------------
    # Get Metadata (Safe & Layered)
    # -------------------------
    def get_case_metadata(self, case_id: str) -> dict:
        """
        ดึง Metadata ที่จำเป็น (รวม Policy) เพื่อไม่ให้ข้อมูลหายตอน Save ทับ
        """
        try:
            # ใช้ supabase global แทน self.client เพื่อป้องกัน Error
            res = (
                supabase 
                .table("cases")
                .select("case_id, domain, created_at, status, payload->policy_id, payload->policy_version")
                .eq("case_id", case_id)
                .maybe_single()
                .execute()
            )
            return res.data or {}
        except Exception as e:
            print(f"Repo Error (Get Metadata): {e}")
            return {}
        
    # -------------------------
    # Save / upsert case
    # -------------------------
    def save_case(self, case: dict) -> None:
        now = datetime.utcnow().isoformat()

        supabase.table("cases").upsert(
            {
                "case_id": case["case_id"],
                "domain": case.get("domain"),
                "status": case.get("status"),
                "payload": case,
                "updated_at": now,
            }
        ).execute()

    # -------------------------
    # Update case status (Phase 5)
    # -------------------------
    def update_case_status(self, case_id: str, status: str) -> None:
        now = datetime.utcnow().isoformat()

        res = (
            supabase
            .table("cases")
            .update(
                {
                    "status": status,
                    # IMPORTANT: payload is source of truth
                    "payload": {
                        "status": status,
                        "updated_at": now,
                    },
                    "updated_at": now,
                }
            )
            .eq("case_id", case_id)
            .execute()
        )

        if not res.data:
            raise RuntimeError(f"Failed to update case status for case_id={case_id}")

    # ---------------------------------------------------------
    # Audit Logs
    # ---------------------------------------------------------
    def get_audit_logs(self, case_id: str) -> List[dict]:
        try:
            res = (
                supabase.table("audit_events")
                .select("*")
                .eq("case_id", case_id)
                .order("created_at", desc=False)
                .execute()
            )
            return res.data or []
        except Exception as e:
            print(f"Repo Error (Audit): {e}")
            return []

    # ---------------------------------------------------------
    # Vector Search (RAG)
    # ---------------------------------------------------------
    def search_evidence(self, query_embedding: List[float], match_count: int = 3) -> List[dict]:
        try:
            params = {
                "query_embedding": query_embedding,
                "match_count": match_count,
                "filter_policy_id": None
            }
            res = supabase.rpc("match_evidence", params).execute()
            return res.data or []
        except Exception as e:
            print(f"Repo Error (Vector): {e}")
            return []
        
    # ---------------------------------------------------------
    # Save Evaluation Result
    # ---------------------------------------------------------
    def save_evaluation_result(self, case_id: str, analysis_result: dict, decision: dict) -> None:
        now = datetime.utcnow().isoformat()
        
        # 1. ดึงข้อมูลเดิมมาก่อน
        current_case = self.get_case(case_id)
        if not current_case:
            raise ValueError(f"Case {case_id} not found")

        # 2. อัปเดต Payload
        payload = current_case
        
        payload["status"] = "EVALUATED"
        payload["risk_level"] = decision.get("risk_level", "HIGH")
        payload["evaluated_at"] = now
        payload["last_rule_results"] = analysis_result.get("rule_results", [])
        
        payload["decision_summary"] = {
            "risk_level": decision.get("risk_level"),
            "recommended_action": decision.get("decision"),
            "reason": decision.get("reason_codes", [])
        }

        # 3. บันทึก Case ลง DB
        supabase.table("cases").update({
            "status": "EVALUATED",
            "risk_level": decision.get("risk_level"),
            "payload": payload,
            "updated_at": now
        }).eq("case_id", case_id).execute()

        # 4. สร้าง Audit Log
        audit_payload = {
            "case_id": case_id,
            "event_type": "RULE_EVALUATED",
            "actor": {"id": "system", "name": "Decision Engine"},
            "action": "RE-EVALUATED",
            "payload": {
                "risk_level": decision.get("risk_level"),
                "recommendation": decision.get("decision"),
                "violated_rules": len(decision.get("reason_codes", [])),
                "timestamp": now
            },
            "created_at": now
        }
        
        supabase.table("audit_events").insert(audit_payload).execute()


# ==============================================================================
# ✅ NEW CLASS: SupabaseIngestionRepository
# แยกออกมาเพื่อให้จัดการเรื่อง Document Ingestion โดยเฉพาะ ไม่ปนกับ Case Logic
# สืบทอดจาก IngestionRepository (Interface) เพื่อให้รองรับ Clean Architecture
# ==============================================================================

class SupabaseIngestionRepository(IngestionRepository):
    """
    Supabase implementation for Ingestion Pipeline.
    Handles: sense_documents, sense_document_chunks, sense_universal_document_items
    """

    # -------------------------
    # 1. Document Management
    # -------------------------
    def check_duplicate(self, file_hash: str) -> Optional[Dict[str, Any]]:
        """Check if file already exists and is completed"""
        try:
            res = (
                supabase.table("sense_documents")
                .select("*")
                .eq("file_hash", file_hash)
                .eq("status", "completed")
                .execute()
            )
            if res.data:
                return res.data[0]
            return None
        except Exception as e:
            print(f"Repo Error (Check Duplicate): {e}")
            return None

    def create_document(self, filename: str, file_hash: str, file_path: str) -> str:
        """Create initial document record returning doc_id"""
        res = supabase.table("sense_documents").insert({
            "filename": filename,
            "file_hash": file_hash,
            "file_path": file_path,
            "status": "processing"
        }).execute()
        return res.data[0]['id']

    def update_document_domain(self, doc_id: str, domain: str) -> None:
        """Update classified domain"""
        supabase.table("sense_documents").update({
            "domain": domain
        }).eq("id", doc_id).execute()

    def update_document_status(
        self, 
        doc_id: str, 
        status: str, 
        error_message: Optional[str] = None, 
        metadata: Optional[Dict] = None
    ) -> None:
        """Update final status, error message, and extracted metadata"""
        data = {"status": status}
        if error_message:
            data["error_message"] = error_message
        if metadata:
            data["metadata"] = metadata
            
        supabase.table("sense_documents").update(data).eq("id", doc_id).execute()

    # -------------------------
    # 2. Vector & Chunks
    # -------------------------
    def insert_chunk(self, doc_id: str, content: str, embedding: List[float], metadata: Dict) -> None:
        """Insert a single vector chunk"""
        supabase.table("sense_document_chunks").insert({
            "document_id": doc_id,
            "content": content,
            "embedding": embedding,
            "metadata": metadata
        }).execute()

    # -------------------------
    # 3. Structured Items (Table)
    # -------------------------
    def insert_universal_items(self, items: List[Dict]) -> None:
        """Batch insert extracted table items"""
        if not items:
            return
        
        supabase.table("sense_universal_document_items").insert(items).execute()
        
    # Get All Documents (✅ เพิ่ม Method นี้)
    # ✅ เพิ่ม implementation นี้
    def get_all_documents(self) -> List[Dict[str, Any]]:
        try:
            # ดึงเอกสาร + นับจำนวน Chunk (Vectors)
            response = supabase.table("sense_documents") \
                .select("*, sense_document_chunks(count)") \
                .order("created_at", desc=True) \
                .execute()
          
            # response = supabase.table("sense_documents") \
            #     .select("*, sense_document_chunks(count)") \
            #     .order("created_at", desc=True) \
            #     .execute()
            
            data = response.data or []
            
            formatted_docs = []
            for doc in data:
                chunks = doc.get("sense_document_chunks")
                chunk_count = chunks[0]["count"] if chunks and len(chunks) > 0 else 0
                
                formatted_docs.append({
                    "id": doc.get("id"),
                    
                    # ✅ แก้ตรงนี้: ถ้า file_name เป็น None ให้ใช้ค่า Default
                    "file_name": doc.get("filename") or "Untitled Document", 
                    
                    "file_path": doc.get("file_path"),
                    "status": doc.get("status", "pending"),
                    "domain": doc.get("domain") or "general",
                    "created_at": doc.get("created_at"),
                    "vector_count": chunk_count,
                    "metadata": doc.get("metadata") or {}
                })
                
            return formatted_docs

        except Exception as e:
            print(f"🔥 CRITICAL REPO ERROR: {str(e)}")
            # คืนค่า list ว่างไปเลยเพื่อกัน API พัง 500
            return []
        
    def get_document_path(self, doc_id: UUID) -> Optional[str]:
        """ดึง file_path จาก database โดยใช้ ID"""
        try:
            response = supabase.table("sense_documents") \
                .select("file_path") \
                .eq("id", str(doc_id)) \
                .single() \
                .execute()
            
            if response.data:
                return response.data.get("file_path")
            return None
        except Exception as e:
            print(f"❌ Repo Error (get_document_path): {e}")
            return None