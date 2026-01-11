from typing import List, Optional
from app.db.supabase_client import supabase

from app.repositories.audit_base import AuditRepository


class SupabaseAuditRepository(AuditRepository):
    """
    Supabase-backed Audit Repository
    - audit_events table is the single source of truth
    - used by DecisionEngine, Orchestrator, Timeline API
    """

    # -------------------------
    # Write
    # -------------------------
    def append_event(
    self,
    case_id: Optional[str],
    event_type: str,
    actor: str,
    payload: dict,
) -> None:
     supabase.table("audit_events").insert(
        {
            "case_id": case_id,
            "event_type": event_type,
            "actor": actor,
            "payload": payload,
        }
    ).execute()



    # -------------------------
    # REQUIRED by AuditRepository
    # -------------------------
    def list_events(self, case_id: str) -> List[dict]:
        """
        Default timeline reader (required by interface)
        """
        return self.list_events_by_case(case_id)

    # -------------------------
    # Read – timeline by case
    # -------------------------
    def list_events_by_case(self, case_id: str) -> List[dict]:
        res = (
            supabase
            .table("audit_events")
            .select("*")
            .eq("case_id", case_id)
            .order("created_at", desc=False)
            .execute()
        )
        return res.data or []

    # -------------------------
    # Read – poll new events (Phase 6)
    # -------------------------
    def list_events_since(self, since_ts: str) -> List[dict]:
        """
        Return all events created AFTER since_ts
        Used by EmbeddedOrchestrator poll loop
        """
        res = (
            supabase
            .table("audit_events")
            .select("*")
            .gt("created_at", since_ts)
            .order("created_at", desc=False)
            .execute()
        )
        return res.data or []

    # -------------------------
    # Idempotency helper (Phase 6)
    # -------------------------
    def has_action_success(
        self,
        case_id: str,
        action_type: str,
        idempotency_key: str,
    ) -> bool:
        """
        Check if ACTION_SUCCEEDED already exists
        for (case_id, action_type, idempotency_key)

        This is the ONLY idempotency source of truth.
        """
        res = (
            supabase
            .table("audit_events")
            .select("id")
            .eq("case_id", case_id)
            .eq("event_type", "ACTION_SUCCEEDED")
            .eq("payload->>action_type", action_type)
            .eq("payload->>idempotency_key", idempotency_key)
            .limit(1)
            .execute()
        )
        return bool(res.data)
