from abc import ABC, abstractmethod
from typing import List, Optional


class CaseRepository(ABC):

    @abstractmethod
    def list_cases(self) -> List[dict]:
        pass

    @abstractmethod
    def get_case(self, case_id: str) -> Optional[dict]:
        pass

    @abstractmethod
    def save_case(self, case: dict) -> None:
        pass
