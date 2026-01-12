import pytest
from app.services.decision_engine import DecisionEngine

# -------------------------------------------------
# Shared mock policy (with risk_impact)
# -------------------------------------------------

MOCK_POLICY = {
    "rules": [
        {
            "id": "HIGH_AMOUNT_ESCALATION",
            "description": "High value procurement (>200k) must be escalated",
            "risk_impact": "HIGH",
            "when": [
                {"field": "amount_total", "operator": ">", "value": 200000}
            ]
        },
        {
            "id": "VENDOR_BLACKLIST_CHECK",
            "description": "Critical: Vendor is flagged as BLACKLISTED",
            "risk_impact": "CRITICAL",
            "when": [
                {"field": "vendor_status", "operator": "==", "value": "BLACKLISTED"}
            ]
        }
    ],
    "thresholds": {
        "amount": {
            "medium": 200000,
            "high": 500000
        }
    },
    "config": {
        "high_risk_threshold": 200000,
        "force_risk_level": "HIGH"
    },
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
# Helpers (same logic as API layer)
# -------------------------------------------------

RISK_PRIORITY = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]


def collect_risk_drivers(policy, rule_results):
    drivers = []
    for r in rule_results:
        if not r.get("hit"):
            continue

        rule_def = next(
            (x for x in policy.get("rules", []) if x.get("id") == r.get("rule_id")),
            None
        )
        if rule_def and rule_def.get("risk_impact"):
            drivers.append({
                "rule_id": r["rule_id"],
                "impact": rule_def["risk_impact"],
            })
    return drivers


def derive_risk_from_drivers(drivers):
    if not drivers:
        return "LOW"

    impacts = [d["impact"] for d in drivers]
    for p in RISK_PRIORITY:
        if p in impacts:
            return p
    return "LOW"


def apply_threshold_safety_net(current_risk, amount, policy):
    risk = current_risk

    thresholds = policy.get("thresholds", {}).get("amount", {})
    high_th = thresholds.get("high")
    med_th = thresholds.get("medium")

    if high_th is not None and amount >= high_th:
        risk = "HIGH"
    elif med_th is not None and amount >= med_th:
        if risk == "LOW":
            risk = "MEDIUM"

    config = policy.get("config", {})
    force_th = config.get("high_risk_threshold")
    force_level = config.get("force_risk_level", "HIGH")

    if force_th is not None and amount > force_th:
        risk = force_level

    return risk


def derive_risk(policy, decision, amount, rule_results):
    drivers = collect_risk_drivers(policy, rule_results)
    base = derive_risk_from_drivers(drivers)
    final = apply_threshold_safety_net(base, amount, policy)
    return final, drivers


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

    # --- rule ---
    rule = next(r for r in result["rule_results"]
                if r["rule_id"] == "HIGH_AMOUNT_ESCALATION")

    assert rule["hit"] is False
    assert rule["matched"] == []

    # --- decision ---
    decision = result["recommendation"]["decision"]
    assert decision in ["APPROVE", "REVIEW"]

    # --- risk ---
    risk, drivers = derive_risk(
        MOCK_POLICY,
        decision,
        inputs["amount_total"],
        result["rule_results"]
    )

    assert risk == "LOW"
    assert drivers == []


# =================================================
# TEST 2 — RISK (HIGH)
# =================================================

def test_risk_case_high_amount():
    inputs = {
        "amount_total": 387500,
        "vendor_status": "ACTIVE",
        "vendor_name": "Good Supplier Ltd.",
    }

    result = run_engine(inputs)

    # --- rule ---
    rule = next(r for r in result["rule_results"]
                if r["rule_id"] == "HIGH_AMOUNT_ESCALATION")

    assert rule["hit"] is True
    assert rule["matched"][0]["field"] == "amount_total"
    assert rule["matched"][0]["actual"] == 387500

    # --- decision ---
    decision = result["recommendation"]["decision"]
    assert decision == "ESCALATE"

    # --- risk ---
    risk, drivers = derive_risk(
        MOCK_POLICY,
        decision,
        inputs["amount_total"],
        result["rule_results"]
    )

    assert risk == "HIGH"
    assert drivers[0]["rule_id"] == "HIGH_AMOUNT_ESCALATION"
    assert drivers[0]["impact"] == "HIGH"


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

    # --- rule ---
    rule = next(r for r in result["rule_results"]
                if r["rule_id"] == "VENDOR_BLACKLIST_CHECK")

    assert rule["hit"] is True
    assert rule["matched"][0]["field"] == "vendor_status"
    assert rule["matched"][0]["actual"] == "BLACKLISTED"

    # --- decision ---
    decision = result["recommendation"]["decision"]
    assert decision == "REJECT"

    # --- risk ---
    risk, drivers = derive_risk(
        MOCK_POLICY,
        decision,
        inputs["amount_total"],
        result["rule_results"]
    )

    assert risk == "CRITICAL"
    assert drivers[0]["rule_id"] == "VENDOR_BLACKLIST_CHECK"
    assert drivers[0]["impact"] == "CRITICAL"
