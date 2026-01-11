from typing import List, Optional
from app.repositories.base import CaseRepository


class MemoryCaseRepository(CaseRepository):

    def __init__(self, db: dict):
        self.db = db

    def list_cases(self) -> List[dict]:
        return [c for c in self.db.get("cases", []) if c.get("case_id")]

    def get_case(self, case_id: str) -> Optional[dict]:
        return next(
            (c for c in self.db.get("cases", []) if c.get("case_id") == case_id),
            None,
        )

    def save_case(self, case: dict) -> None:
        # in-memory: object is mutated in place
        return
