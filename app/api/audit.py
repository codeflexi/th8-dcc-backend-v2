# app/api/audit.py

from fastapi import APIRouter, Query, Path
from typing import List, Dict, DefaultDict, Any
from collections import defaultdict

from app.schemas.audit import AuditEvent
from app.services.audit_service import AuditService

router = APIRouter(tags=["audit"])


# =================================================
# 🧠 SMART CONTEXT BUILDER (Universal Engine)
# =================================================
def _build_context(event_type: str, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    ctx = []

    # --- 1. CASE INGESTED ---
    if event_type == "CASE_INGESTED":
        # ดึงค่าแบบกันเหนียว (Fallback)
        vendor = payload.get("vendor") or payload.get("vendor_name") or "-"
        po = payload.get("po_number") or payload.get("po") or "-"
        amt = payload.get("amount") or payload.get("amount_total") or 0

        ctx.append({"label": "Vendor", "value": vendor, "highlight": True})
        ctx.append({"label": "PO No.", "value": po, "type": "mono"})
        ctx.append({
            "label": "Amount", 
            "value": f"{amt:,.2f} THB", 
            "type": "currency", 
            "fullWidth": True
        })

    # --- 2. RULE EVALUATED ---
    elif event_type == "RULE_EVALUATED":
        rule = payload.get("rule", {})
        inputs = payload.get("inputs", {})
        hit = payload.get("hit", False)

        # ชื่อกฎ
        ctx.append({
            "label": "Rule", 
            "value": rule.get("description") or rule.get("id"),
            "fullWidth": True
        })
        
        # ผลลัพธ์ (Badge)
        ctx.append({
            "label": "Status", 
            "value": "RISK DETECTED" if hit else "PASSED", 
            "type": "badge",
            "badgeColor": "red" if hit else "green"
        })

        # Logic Inputs (สำคัญมาก: บอกว่าทำไมถึงผ่าน/ไม่ผ่าน)
        if inputs:
            kv_pairs = []
            for k, v in inputs.items():
                # ✅ Filter: กรอง field ที่ไม่จำเป็นออก เพื่อไม่ให้รก Timeline
                if v is not None and k not in ["vendor_name", "line_items", "description"]:
                    kv_pairs.append(f"{k}={v}")
            
            if kv_pairs:
                ctx.append({
                    "label": "Evaluation Logic", 
                    "value": " | ".join(kv_pairs), 
                    "type": "mono", 
                    "fullWidth": True
                })

    # --- 3. DECISION RECOMMENDED ---
    elif event_type == "DECISION_RECOMMENDED":
        rec = payload.get("recommendation", {})
        ctx.append({"label": "AI Decision", "value": rec.get("decision"), "type": "badge", "badgeColor": "purple"})
        ctx.append({"label": "Role Required", "value": rec.get("required_role")})

    # --- 4. GENERIC FALLBACK ---
    else:
        for k in ["reason", "action", "source"]:
            if val := payload.get(k):
                ctx.append({"label": k.title(), "value": str(val)})

    return ctx


def _build_audit_events(case_id: str) -> List[AuditEvent]:
    """
    Transform raw audit_events rows into AuditEvent schema
    """
    raw_events = AuditService.list_by_case(case_id)
    results: List[AuditEvent] = []

    for e in raw_events:
        payload = e.get("payload") or {}
        event_type = e.get("event_type", "SYSTEM_NOTE")
        
        # ✅ สร้าง UI Context
        context_data = _build_context(event_type, payload)

        # สร้างข้อความย่อ (Fallback Message)
        message = payload.get("message") or payload.get("reason") or event_type

        results.append(
            AuditEvent(
                event_id=e.get("event_id"),
                case_id=e.get("case_id"),
                event_type=event_type,
                actor=e.get("actor", "SYSTEM"),
                actor_role=payload.get("actor_role"),
                timestamp=e.get("created_at"),
                message=message,
                
                # ✅ ส่ง Context ที่สร้างเสร็จแล้วออกไป
                context=context_data,
                
                details=payload,
            )
        )

    return results


def _group_events_by_run(events: List[AuditEvent]) -> List[Dict]:
    """
    Group audit events by run_id (Audit API v2 behavior)
    """
    runs: DefaultDict[str, List[AuditEvent]] = defaultdict(list)
    for e in events:
        run_id = (e.details or {}).get("run_id") or "__NO_RUN__"
        runs[run_id].append(e)

    grouped: List[Dict] = []
    for run_id, evts in runs.items():
        evts_sorted = sorted(evts, key=lambda x: x.timestamp)
        started = next((e.timestamp for e in evts_sorted if e.event_type == "DECISION_RUN_STARTED"), None)
        completed = next((e.timestamp for e in evts_sorted if e.event_type == "DECISION_RUN_COMPLETED"), None)
        grouped.append({
            "run_id": run_id,
            "started_at": started,
            "completed_at": completed,
            "events": evts_sorted,
        })
    grouped.sort(key=lambda r: r.get("started_at") or "", reverse=True)
    return grouped


# =================================================
# Endpoints
# =================================================
@router.get("/audit-events", response_model=List[AuditEvent])
def get_audit_events(case_id: str = Query(..., description="Case ID")):
    return _build_audit_events(case_id)

@router.get("/audit/case/{case_id}", response_model=List[AuditEvent])
def get_audit_events_by_case(case_id: str = Path(..., description="Case ID")):
    return _build_audit_events(case_id)

@router.get("/cases/{case_id}/audit")
def get_case_audit_v2(
    case_id: str = Path(...),
    group: str = Query("flat"),
):
    events = _build_audit_events(case_id)
    if group == "run":
        return _group_events_by_run(events)
    return events