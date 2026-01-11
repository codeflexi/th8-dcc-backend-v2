class EvidenceService:
    """
    Mock RAG-as-Evidence Service

    Responsibility:
    - Retrieve supporting evidence (documents / clauses)
      to justify a decision
    - Evidence is NOT a decision, only supporting facts

    Design principles:
    - Deterministic (same input -> same evidence)
    - Explainable (why this evidence was selected)
    - Replaceable (vector DB / SQL / MCP in future)
    """

    @staticmethod
    def find_evidence(case: dict, policy: dict) -> list:
        """
        Input:
        - case: normalized case context
        - policy: loaded policy config

        Output:
        - list of evidence objects
        """

        evidence = []

        decision_type = policy.get("scope", {}).get("decision_type")

        # --------------------------------------------------
        # Pricing / Contract Evidence
        # --------------------------------------------------
        if decision_type == "PRICING":
            discount = case.get("discount_percent")
            max_discount = policy.get("thresholds", {}).get("max_discount_percent")

            if discount is not None and max_discount is not None:
                if discount > max_discount:
                    evidence.append({
                        "evidence_type": "CONTRACT_CLAUSE",
                        "document_id": "contract_CON-2024-01.pdf",
                        "clause": "4.1",
                        "excerpt": "Discount beyond 8% requires CFO approval",
                        "matched_reason": f"discount_percent {discount} > policy limit {max_discount}",
                        "confidence": 0.92,
                    })

        # --------------------------------------------------
        # Procurement Evidence
        # --------------------------------------------------
        if decision_type == "PROCUREMENT":
            amount = case.get("amount")
            medium_threshold = policy.get("thresholds", {}).get("amount", {}).get("medium")

            if amount is not None and medium_threshold is not None:
                if amount > medium_threshold:
                    evidence.append({
                        "evidence_type": "PROCUREMENT_POLICY",
                        "document_id": "procurement_policy.pdf",
                        "clause": "2.3",
                        "excerpt": "High-value procurement must be escalated",
                        "matched_reason": f"amount {amount} > policy medium threshold {medium_threshold}",
                        "confidence": 0.88,
                    })

        # --------------------------------------------------
        # Credit Evidence
        # --------------------------------------------------
        if decision_type == "CREDIT":
            credit_days = case.get("credit_days")
            max_days = policy.get("thresholds", {}).get("max_credit_days")

            if credit_days is not None and max_days is not None:
                if credit_days > max_days:
                    evidence.append({
                        "evidence_type": "CREDIT_POLICY",
                        "document_id": "credit_policy.pdf",
                        "clause": "3.2",
                        "excerpt": "Credit term exceeding 60 days requires CFO approval",
                        "matched_reason": f"credit_days {credit_days} > policy limit {max_days}",
                        "confidence": 0.9,
                    })

        return evidence
