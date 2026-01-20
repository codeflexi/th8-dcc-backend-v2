import os
import httpx
from typing import List, Optional
from dotenv import load_dotenv

# Import Base Class และ Supabase Client
from app.repositories.base import CaseRepository
from app.db.supabase_client import supabase 

load_dotenv()

class CopilotRepository(CaseRepository):
    """
    Hybrid Repository for AI Copilot:
    - Uses Async HTTP Client to fetch enriched data from internal API (avoiding deadlocks).
    - Falls back to Direct DB calls if API fails.
    - Uses Direct DB calls for Vector Search.
    """

    def __init__(self):
        # อ่าน URL จาก .env (ถ้าไม่มีให้ใช้ default localhost)
        self.api_base_url = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api")

    # ---------------------------------------------------------
    # 1. Get Case (Async API Call)
    # ---------------------------------------------------------
    async def get_case(self, case_id: str) -> Optional[dict]:
        """
        ดึงข้อมูล Case + Story Analysis จาก Internal API
        ใช้ Async เพื่อป้องกันการ Block Server Thread
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(f"{self.api_base_url}/cases/{case_id}")
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"[Repo] API Error (get_case): Status {response.status_code}")
                return None
        except Exception as e:
            print(f"[Repo] Connection Error (get_case): {e}")
            return None

    # ---------------------------------------------------------
    # 2. Get Audit Logs (Async API Call + DB Fallback)
    # ---------------------------------------------------------
    async def get_audit_logs(self, case_id: str) -> List[dict]:
        """
        พยายามดึง Audit จาก API ก่อน ถ้าไม่ได้ให้ดึงจาก DB ตรงๆ
        """
        # 1. Try API First
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.api_base_url}/cases/{case_id}/audit")
                
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"[Repo] Audit API Failed ({e}), switching to DB fallback...")

        # 2. Fallback to DB (Direct Supabase)
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
            print(f"[Repo] Audit DB Fallback Failed: {e}")
            return []

    # ---------------------------------------------------------
    # 3. Vector Search (Direct DB Call)
    # ---------------------------------------------------------
    def search_evidence(self, query_embedding: List[float], match_count: int = 3) -> List[dict]:
        """
        ค้นหา Vector Similarity (RAG) ผ่าน RPC ของ Supabase
        (Library นี้เป็น Sync แต่ยิงออก External Network ไม่กระทบ Localhost Deadlock)
        """
        try:
            params = {
                "query_embedding": query_embedding,
                "match_count": match_count,
                "filter_policy_id": None
            }
            res = supabase.rpc("match_evidence", params).execute()
            return res.data or []
        except Exception as e:
            print(f"[Repo] Vector Search Error: {e}")
            return []

    # ---------------------------------------------------------
    # Abstract Methods Implementation (Unused by Copilot)
    # ---------------------------------------------------------
    def list_cases(self) -> List[dict]:
        return []

    def save_case(self, case: dict) -> None:
        pass

    def update_case_status(self, case_id: str, status: str) -> None:
        pass