from pydantic import BaseModel
from typing import List, Optional, Dict , Any


from datetime import datetime

class AuditEvent(BaseModel):
    event_id: Optional[str]
    case_id: str
    event_type: str
    actor: str = "SYSTEM"
    actor_role: Optional[str]
    timestamp: Optional[str]
    message: Optional[str]
    
    # ✅ New: Generic Context for UI
    # Structure: [{ "label": "Vendor", "value": "Siam Makro", "type": "text", "highlight": true }]
    context: List[Dict[str, Any]] = []
    
    details: Dict[str, Any] = {}

class AuditRun(BaseModel):
    run_id: str
    started_at: Optional[str]
    completed_at: Optional[str]
    events: List[AuditEvent]
