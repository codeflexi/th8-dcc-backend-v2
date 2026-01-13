from typing import List, Optional
from datetime import datetime

from app.repositories.base import CaseRepository
from app.db.supabase_client import supabase


class SupabaseCaseRepository(CaseRepository):
    """
    Supabase (Postgres) implementation of CaseRepository

    Phase 4 notes:
    - payload is the source of truth
    - repository returns raw dicts
    - API layer is responsible for schema mapping
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

        # 🔧 FIX: defensive handling for Supabase edge case
        if not res or not res.data:
            return None

        return res.data.get("payload")

    
    # -------------------------
    # ✅ NEW: Get Metadata (Safe & Layered)
    # -------------------------
    def get_case_metadata(self, case_id: str) -> dict:
        """
        ดึง Metadata ที่จำเป็น (รวม Policy) เพื่อไม่ให้ข้อมูลหายตอน Save ทับ
        """
        try:
            res = (
                self.client  # ใช้ client ของ repo เอง
                .table("cases")
                .select("case_id, domain, created_at, status, payload.policy_id, policy_version")
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
    # Update case status (Phase 5 only)
    # -------------------------
    def update_case_status(self, case_id: str, status: str) -> None:
        """
        Phase 5:
        - Controlled status update for decision execution
        - Keep payload as source of truth
        - Minimal write, no schema change
        """

        now = datetime.utcnow().isoformat()

        res = (
            supabase
            .table("cases")
            .update(
                {
                    "status": status,
                    # IMPORTANT: payload is source of truth for Phase 4 APIs
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
    # ✅ เพิ่มส่วนใหม่: Audit Logs (จำเป็นสำหรับ AI เพื่อดูประวัติ)
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
    # ✅ เพิ่มส่วนใหม่: Vector Search (สำหรับ RAG)
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
    # ✅ FIX: Save Evaluation Result (บันทึกผลหลังรัน Engine)
    # ---------------------------------------------------------
    def save_evaluation_result(self, case_id: str, analysis_result: dict, decision: dict) -> None:
        """
        updates case payload with new rule results and adds an audit log
        """
        now = datetime.utcnow().isoformat()
        
        # 1. ดึงข้อมูลเดิมมาก่อน (เพื่อไม่ให้ field อื่นหาย)
        current_case = self.get_case(case_id)
        if not current_case:
            raise ValueError(f"Case {case_id} not found")

        # 2. อัปเดต Payload ด้วยผลลัพธ์ใหม่
        payload = current_case  # get_case ของคุณ return payload อยู่แล้ว
        
        # อัปเดตค่าสำคัญ
        payload["status"] = "EVALUATED"
        payload["risk_level"] = decision.get("risk_level", "HIGH")
        payload["evaluated_at"] = now
        payload["last_rule_results"] = analysis_result.get("rule_results", [])
        
        # อัปเดต Decision Summary
        payload["decision_summary"] = {
            "risk_level": decision.get("risk_level"),
            "recommended_action": decision.get("decision"),
            "reason": decision.get("reason_codes", [])
        }

        # 3. บันทึก Case ลง DB (Update)
        supabase.table("cases").update({
            "status": "EVALUATED",
            "risk_level": decision.get("risk_level"), # ถ้ามี column นี้แยก
            "payload": payload,
            "updated_at": now
        }).eq("case_id", case_id).execute()

        # 4. ✅ สร้าง Audit Log ใหม่ (เพื่อให้ Timeline ขยับ)
        audit_payload = {
            "case_id": case_id,
            "event_type": "RULE_EVALUATED",
            "actor": {"id": "system", "name": "Decision Engine"},
            "action": "RE-EVALUATED",  # ใช้ชื่อให้รู้ว่ารันใหม่
            "payload": {
                "risk_level": decision.get("risk_level"),
                "recommendation": decision.get("decision"),
                "violated_rules": len(decision.get("reason_codes", [])),
                "timestamp": now
            },
            "created_at": now
        }
        
        supabase.table("audit_events").insert(audit_payload).execute()    