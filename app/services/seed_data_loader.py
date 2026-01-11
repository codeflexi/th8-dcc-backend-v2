from datetime import datetime, timezone

from app.repositories.supabase_repo import SupabaseCaseRepository
from app.repositories.supabase_audit_repo import SupabaseAuditRepository


NOW = datetime.now(timezone.utc).isoformat()


def seed_demo_data():
    case_repo = SupabaseCaseRepository()
    audit_repo = SupabaseAuditRepository()

    cases = [
        # =========================
        # CASE A — High Risk (CFO)
        # =========================
        {
            "case_id": "CASE-PO-OVT-2025-002",
            "domain": "procurement",
            "vendor_id": "VENDOR-OVT-TH-01",
            "amount_total": 1_850_000,
            "status": "PENDING",
            "pending_reason": "ราคาสูงกว่าสัญญา / มูลค่าเกิน threshold",
            "priority_score": 92,
            "priority_reason": "High financial impact + contract deviation",
            "violations": [
                {
                    "rule_id": "R-01",
                    "rule_name": "Price deviation vs contract",
                    "severity": "HIGH",
                    "delta_pct": 18.5,
                    "delta_amount": 285000,
                },
                {
                    "rule_id": "R-02",
                    "rule_name": "Amount exceeds approval threshold",
                    "severity": "MEDIUM",
                    "amount": 1850000,
                },
            ],
            "created_at": NOW,
            "evaluated_at": NOW,
        },

        # =========================
        # CASE B — Compliance Risk
        # =========================
        {
            "case_id": "CASE-PO-OVT-2025-003",
            "domain": "procurement",
            "vendor_id": "VENDOR-OVT-TH-02",
            "amount_total": 420_000,
            "status": "PENDING",
            "pending_reason": "Vendor ไม่ตรงกับสัญญา",
            "priority_score": 68,
            "priority_reason": "Compliance risk",
            "violations": [
                {
                    "rule_id": "R-03",
                    "rule_name": "Vendor mismatch",
                    "severity": "HIGH",
                }
            ],
            "created_at": NOW,
            "evaluated_at": NOW,
        },

        # =========================
        # CASE C — Clean Pass
        # =========================
        {
            "case_id": "CASE-PO-OVT-2025-004",
            "domain": "procurement",
            "vendor_id": "VENDOR-OVT-TH-01",
            "amount_total": 215_000,
            "status": "PASS",
            "pending_reason": None,
            "priority_score": 15,
            "priority_reason": "Low risk / within policy",
            "violations": [],
            "created_at": NOW,
            "evaluated_at": NOW,
        },
    ]

    for case in cases:
        # ---- save case ----
        case_repo.save_case(case)

        # ---- audit timeline ----
        audit_repo.append_event(
            case_id=case["case_id"],
            event_type="CASE_CREATED",
            actor="system",
            payload={
                "domain": case["domain"],
                "message": "Case created from demo seed",
            },
        )

        audit_repo.append_event(
            case_id=case["case_id"],
            event_type="CASE_EVALUATED",
            actor="system",
            payload={
                "status": case["status"],
                "violations": case["violations"],
                "message": "Case evaluated by policy engine",
            },
        )

        if case["status"] == "PENDING":
            audit_repo.append_event(
                case_id=case["case_id"],
                event_type="CASE_PENDING",
                actor="system",
                payload={
                    "reason": case["pending_reason"],
                    "priority_score": case["priority_score"],
                    "message": "Case requires human decision",
                },
            )

        print(f"✔ Seeded {case['case_id']} [{case['status']}]")

    print("✅ Phase 4 Enterprise Demo Dataset loaded")


if __name__ == "__main__":
    seed_demo_data()
