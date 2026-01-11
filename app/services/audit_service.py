from datetime import datetime
from typing import List

from app.db.supabase_client import supabase



class AuditService:
    """
    Append-only audit log writer (Supabase-backed)

    Table: audit_events
    - event_id (uuid, pk)
    - case_id
    - event_type
    - actor
    - payload (jsonb)
    - created_at
    """

    @staticmethod
    def write(
        event_type: str,
        payload: dict,
        actor: str = "SYSTEM",
    ) -> dict:
        """
        Persist audit event to Supabase

        Note:
        - Supabase Python SDK v2+ throws exception on failure
        - No `result.error` attribute anymore
        """

        record = {
            "case_id": payload.get("case_id"),
            "event_type": event_type,
            "actor": actor,
            "payload": payload,
            "created_at": datetime.utcnow().isoformat(),
        }

        result = (
            supabase
            .table("audit_events")
            .insert(record)
            .execute()
        )

        # If no exception was raised, insert succeeded
        # result.data usually contains inserted row(s)
        if result.data:
            return result.data[0]

        # Fallback (should rarely happen)
        return record

    @staticmethod
    def list_by_case(case_id: str) -> List[dict]:
        """
        Read audit timeline for a case
        """

        result = (
            supabase
            .table("audit_events")
            .select("*")
            .eq("case_id", case_id)
            .order("created_at", desc=False)
            .execute()
        )

        # Supabase SDK v2+: return empty list if no data
        return result.data or []
    
