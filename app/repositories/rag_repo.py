from typing import List, Dict, Any
from app.db.supabase_client import supabase

# ชื่อ Bucket ที่คุณใช้เก็บไฟล์จริง (จาก screenshot ของคุณคือ raw_documents)
BUCKET_NAME = "raw_documents"

class CopilotRepositoryAgent:
    """
    Minimal RAG Repository
    ทำหน้าที่ดึงข้อมูลจาก 2 แหล่ง และแปะลิงก์เปิดไฟล์ (Signed URL)
    """

    def _generate_open_url(self, file_path: str, page: str = None) -> str:
        """Helper: สร้าง Signed URL สำหรับเปิดไฟล์ พร้อมระบุเลขหน้า"""
        try:
            if not file_path:
                return None
            
            # ขอ Signed URL อายุ 1 ชั่วโมง (3600 วินาที)
            # หมายเหตุ: ใช้ from_ (มี underscore) ตาม version ใหม่ของ supabase-py
            res = supabase.storage.from_(BUCKET_NAME).create_signed_url(file_path, 3600)
            
            # ดึง URL ออกมา (รองรับทั้ง format เก่าและใหม่)
            url = res.get("signedURL") if isinstance(res, dict) else res
            
            if not url:
                return None

            # ถ้ามีเลขหน้า ให้ต่อท้ายด้วย #page=X (มาตรฐาน Browser PDF Viewer)
            if page:
                url += f"#page={page}"
                
            return url
        except Exception as e:
            print(f"[REPO] Gen URL Error: {e}")
            return None

    def rag_search_chunks(
        self,
        query_text: str,
        embedding: List[float],
        top_k: int = 5,
        min_similarity: float = 0.25,
    ) -> List[Dict[str, Any]]:
        """
        ค้นหาเนื้อหาเอกสาร (Unstructured Text)
        """
        print(f"DEBUG REPO: Calling rag_search_hybrid")
        
        try:
            # เรียกใช้ RPC function (Hybrid Search)
            res = supabase.rpc(
                "rag_search_hybrid_v1",
                {
                    "query_embedding": embedding,
                    "match_threshold": min_similarity,
                    "match_count": top_k,
                    "query_text": query_text,
                },
            ).execute()

            rows = res.data or []
            results = []

            for r in rows:
                # 1. เตรียม Metadata
                doc_info = {
                    "file_name": r.get("file_name"),
                    "vendor": r.get("vendor_id"),
                    "contract_id": r.get("doc_contract_id"),
                }

                citation = r.get("citation") or {}
                # ดึงเลขหน้า (อาจเก็บใน key 'page', 'page_label', หรือ 'page_number')
                page_label = citation.get("page_label") or citation.get("page") or "1"

                # 2. หา Path ของไฟล์
                # พยายามดึงจาก DB ก่อน ถ้าไม่มี ให้เดาว่าอยู่ใน folder 'raw_uploads/' ตาม ingestion
                file_path = r.get("file_path") 
                if not file_path and r.get("file_name"):
                    file_path = f"raw_uploads/{r.get('file_name')}"

                # 3. สร้าง Link เปิดไฟล์ (✅ เพิ่มตรงนี้)
                open_url = self._generate_open_url(file_path, page_label)

                results.append(
                    {
                        "chunk_id": r.get("chunk_id"),
                        "content": r.get("content"),
                        "similarity": r.get("similarity"),
                        "citation": citation,
                        "metadata": {
                            "document_info": doc_info,
                            "source_type": "text_chunk"
                        },
                        "file_name": r.get("file_name"),
                        "open_url": open_url  # <-- ส่งค่านี้กลับไป
                    }
                )

            print(f"[RAG_REPO] Found {len(results)} chunks")
            return results

        except Exception as e:
            print(f"[RAG_REPO] Chunk Search Error: {e}")
            return []

    def rag_search_products(
        self,
        query_text: str,
        embedding: List[float],
        top_k: int = 5,
        min_similarity: float = 0.50
    ) -> List[Dict[str, Any]]:
        """
        ค้นหารายการสินค้า (Structured Items)
        """
        try:
            res = supabase.rpc(
                "rag_search_items",
                {
                    "query_embedding": embedding,
                    "match_threshold": min_similarity,
                    "match_count": top_k
                },
            ).execute()

            rows = res.data or []
            results = []

            for r in rows:
                item_code = r.get("item_code", "N/A")
                desc = r.get("description", "N/A")
                price = r.get("unit_price", 0)
                
                content_str = f"Product Item: {item_code} | Description: {desc} | Unit Price: {price:,.2f}"
                
                # สินค้าอาจจะไม่มี path ชัดเจนใน item table แต่ถ้ามี file_name ก็ลองเจนดู
                file_path = r.get("file_path")
                if not file_path and r.get("file_name"):
                     file_path = f"raw_uploads/{r.get('file_name')}"
                
                open_url = self._generate_open_url(file_path)

                results.append({
                    "chunk_id": r.get("item_id"),
                    "content": content_str,
                    "similarity": r.get("similarity"),
                    "citation": {"page": "Table", "source_uri": r.get("file_name")}, 
                    "metadata": {
                        "document_info": {"file_name": r.get("file_name"), "vendor": r.get("vendor_id")},
                        "price_info": {
                            "item_code": item_code,
                            "description": desc,
                            "price": price,
                            "raw_data": r.get("raw_data")
                        },
                        "source_type": "product_item"
                    },
                    "file_name": r.get("file_name"),
                    "item_code": item_code,
                    "open_url": open_url # <-- ส่งค่านี้กลับไป
                })

            return results

        except Exception as e:
            print(f"[RAG_REPO] Product Search Error: {e}")
            return []