from abc import ABC, abstractmethod
from typing import List, Optional, Any

class CaseRepository(ABC):
    """
    Abstract Base Class for Case Management Data Access
    Now includes methods for Audit Logs and Vector Search (RAG)
    """

    # -------------------------
    # Core Case Management
    # -------------------------
    @abstractmethod
    def list_cases(self) -> List[dict]:
        """List all cases for the portfolio view."""
        pass

    @abstractmethod
    def get_case(self, case_id: str) -> Optional[dict]:
        """Retrieve a single case payload by ID."""
        pass

    @abstractmethod
    def save_case(self, case: dict) -> None:
        """Create or Upsert a case payload."""
        pass

    @abstractmethod
    def update_case_status(self, case_id: str, status: str) -> None:
        """Update only the status of a case (Phase 5 requirement)."""
        pass

    # -------------------------
    # AI Copilot & Compliance Support
    # -------------------------
    @abstractmethod
    def get_audit_logs(self, case_id: str) -> List[dict]:
        """
        Retrieve the audit trail/timeline for a specific case.
        Used by AI to understand the history of events/decisions.
        """
        pass

    @abstractmethod
    def search_evidence(self, query_embedding: List[float], match_count: int = 3) -> List[dict]:
        """
        Search for relevant policy documents/evidence using vector similarity.
        Used by RAG system to find reference rules.
        """
        pass