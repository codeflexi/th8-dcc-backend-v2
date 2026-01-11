from abc import ABC, abstractmethod
from typing import List


class AuditRepository(ABC):

    @abstractmethod
    def append_event(
        self,
        case_id: str,
        event_type: str,
        actor: str,
        payload: dict,
    ) -> None:
        ...

    @abstractmethod
    def list_events(self, case_id: str) -> List[dict]:
        ...
