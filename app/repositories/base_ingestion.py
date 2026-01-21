from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional

class IngestionRepository(ABC):
    """
    Interface กลางที่กำหนดว่า Repository ต้องมีฟังก์ชันอะไรบ้าง
    (Database ตัวไหนจะมาใช้ ต้องทำตามกฎนี้)
    """

    @abstractmethod
    def create_document(self, filename: str, file_hash: str, file_path: str) -> str:
        pass

    @abstractmethod
    def update_document_status(self, doc_id: str, status: str, error_message: Optional[str] = None, metadata: Optional[Dict] = None):
        pass

    @abstractmethod
    def update_document_domain(self, doc_id: str, domain: str):
        pass

    @abstractmethod
    def insert_chunk(self, doc_id: str, content: str, embedding: List[float], metadata: Dict):
        pass

    @abstractmethod
    def insert_universal_items(self, items: List[Dict]):
        pass

    @abstractmethod
    def check_duplicate(self, file_hash: str) -> Optional[Dict]:
        pass
    
    # ✅ เพิ่ม Method นี้
    @abstractmethod
    def get_all_documents(self) -> List[Dict[str, Any]]:
        pass