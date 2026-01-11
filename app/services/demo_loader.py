import json
from pathlib import Path
from typing import Any, Optional
from datetime import datetime

from app.services.decision_engine import DecisionEngine
from app.repositories.supabase_repo import SupabaseCaseRepository
from app.repositories.supabase_audit_repo import SupabaseAuditRepository

# -------------------------
# Policy (Phase 4)
# -------------------------
POLICY_V1 = {
    "price_deviation": {"tolerance_pct": 1.0, "high_pct": 5.0},
    "amount_threshold": {"cfo_approval": 500_000},
}

# -------------------------
# Demo data dir
# -------------------------
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "demo"


def load_json(filename: str) -> list[dict]:
    path = DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Demo data not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def seed_demo_data() -> None:
    """
    Seed demo cases + audit events into Supabase.
    Safe to re-run (upsert).
    """

    case_repo = SupabaseCaseRepository()
    audit_repo = SupabaseAuditRepository()

    engine = DecisionEngine(POLICY_V1, audit_repo=audit_repo)

    # -------------------------
    # Load demo datasets
    # -------------------------
    po_rows = load_json("ovaltine_procurement.json")
    contract_rows = load_json("ovaltine_documents.json")

    default_contract = contract_rows[0] if contract_rows else {}

    print(f"[DEMO] Seeding {len(po_rows)} procurement cases")

    for po in po_rows:
        case_id = po.get("case_id") or po.get("external_id")
        if not case_id:
            continue

        case = {
            "case_id": case_id,
            "domain": "PROCUREMENT",
            "vendor_id": po.get("vendor_id"),
            "amount_total": float(po.get("amount_total", 0)),
            "po_date": po.get("po_date"),
            "po": {
                "unit_price": float(po.get("unit_price", 0)),
                "quantity": int(po.get("quantity", 0)),
            },
            "contract": {
                "vendor_id": default_contract.get("vendor_id"),
                "unit_price": float(default_contract.get("unit_price", 0)),
                "valid_from": default_contract.get("valid_from"),
                "valid_to": default_contract.get("valid_to"),
            },
            "created_at": datetime.utcnow().isoformat(),
        }

        # -------------------------
        # Decision evaluation
        # (RULE_EVALUATED / CASE_PENDING audit emitted here)
        # -------------------------
        case = engine.evaluate(case)

        # -------------------------
        # Optional demo-only fields
        # -------------------------
        if case.get("status") == "PENDING":
            case["priority_score"] = 80
            case["priority_reason"] = "Policy violation requires human review"
        else:
            case["priority_score"] = 10
            case["priority_reason"] = "Low risk"

        # -------------------------
        # Persist case
        # -------------------------
        case_repo.save_case(case)

        # -------------------------
        # Audit: CASE_CREATED (explicit)
        # -------------------------
        audit_repo.append_event(
            case_id=case["case_id"],
            event_type="CASE_CREATED",
            actor="system",
            payload={
                "source": "demo_loader",
                "domain": case.get("domain"),
            },
        )

        print(f"  ✔ Seeded case {case['case_id']} [{case['status']}]")

    print("[DEMO] Seed completed")


if __name__ == "__main__":
    seed_demo_data()
