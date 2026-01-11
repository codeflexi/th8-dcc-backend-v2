import pytest
from app.services.decision_engine import DecisionEngine


# -------------------------------------------------
# Shared mock policy (minimal)
# -------------------------------------------------

MOCK_POLICY = {
    "rules": [
        {
            "id": "HIGH_AMOUNT_ESCALATION",
            "description": "High value procurement (>200k) must be escalated",
            "when": [
                {"field": "amount_total", "operator": ">", "value": 200000}
            ]
        },
        {
            "id": "VENDOR_BLACKLIST_CHECK",
            "description": "Critical: Vendor is flagged as BLACKLISTED",
            "when": [
                {"field": "vendor_status", "operator": "==", "value": "BLACKLISTED"}
            ]
        }
    ],
    "authority": {
        "rules": [
            {
                "condition": "amount_total > 200000",
                "required_role": "Finance_Director"
            }
        ]
    }
}


# -------------------------------------------------
# Helper to run engine
# -------------------------------------------------

def run_engine(inputs):
    return DecisionEngine.evaluate(policy=MOCK_POLICY, inputs=inputs)


# =================================================
# TEST 1 — PASS
# =================================================

def test_pass_case():
    inputs = {
        "amount_total": 150000,
        "vendor_status": "ACTIVE",
        "vendor_name": "Good Supplier Ltd.",
    }

    result = run_engine(inputs)

    rule = next(r for r in result["rule_results"]
                if r["rule_id"] == "HIGH_AMOUNT_ESCALATION")

    assert rule["hit"] is False
    assert rule["matched"] == []


# =================================================
# TEST 2 — RISK
# =================================================

def test_risk_case_high_amount():
    inputs = {
        "amount_total": 387500,
        "vendor_status": "ACTIVE",
        "vendor_name": "Good Supplier Ltd.",
    }

    result = run_engine(inputs)

    rule = next(r for r in result["rule_results"]
                if r["rule_id"] == "HIGH_AMOUNT_ESCALATION")

    assert rule["hit"] is True
    assert rule["matched"][0]["field"] == "amount_total"
    assert rule["matched"][0]["actual"] == 387500


# =================================================
# TEST 3 — CRITICAL
# =================================================

def test_critical_case_blacklisted_vendor():
    inputs = {
        "amount_total": 120000,
        "vendor_status": "BLACKLISTED",
        "vendor_name": "Bad Supplier Ltd.",
    }

    result = run_engine(inputs)

    rule = next(r for r in result["rule_results"]
                if r["rule_id"] == "VENDOR_BLACKLIST_CHECK")

    assert rule["hit"] is True
    assert rule["matched"][0]["field"] == "vendor_status"
    assert rule["matched"][0]["actual"] == "BLACKLISTED"
