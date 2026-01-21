from typing import List, Optional, Dict, Type
from pydantic import BaseModel, create_model, Field

# =========================================================
# 1. Configuration: กำหนด Field ที่ต้องการของแต่ละ Domain
# =========================================================
DOMAIN_CONFIG = {
    "procurement": {
        "description": "Contracts related to purchasing, vendors, and supplies.",
        "fields": {
            "contract_id": (str, Field(..., description="Unique contract identifier or number")),
            "vendor_name": (str, Field(..., description="Name of the vendor or supplier")),
            "total_value": (Optional[float], Field(None, description="Total contract value amount")),
            "currency": (str, Field("THB", description="Currency code e.g. THB, USD")),
            "start_date": (Optional[str], Field(None, description="Contract start date (YYYY-MM-DD)")),
            "end_date": (Optional[str], Field(None, description="Contract end date (YYYY-MM-DD)")),
            "payment_terms": (Optional[str], Field(None, description="Summary of payment terms (e.g., Net 30)"))
        }
    },
    "legal": {
        "description": "Legal agreements, NDAs, and MOU.",
        "fields": {
            "agreement_type": (str, Field(..., description="Type of agreement (NDA, MOU, Service Agreement)")),
            "parties": (List[str], Field(default_factory=list, description="List of parties involved")),
            "effective_date": (Optional[str], Field(None, description="Date the agreement becomes effective")),
            "jurisdiction": (Optional[str], Field(None, description="Governing law or jurisdiction"))
        }
    },
    "general": {
        "description": "General documents.",
        "fields": {
            "summary": (str, Field(..., description="Brief summary of the document content")),
            "keywords": (List[str], Field(default_factory=list, description="Key topics or tags"))
        }
    }
}

# =========================================================
# 2. Dynamic Model Generator
# =========================================================
def get_dynamic_model(domain: str) -> Type[BaseModel]:
    """
    สร้าง Pydantic Class ขึ้นมาใหม่แบบสดๆ ตาม Domain ที่ส่งมา
    เพื่อให้ OpenAI Structured Output ทำงานได้ตรงตามประเภทเอกสาร
    """
    domain = domain.lower()
    if domain not in DOMAIN_CONFIG:
        domain = "general"
        
    config = DOMAIN_CONFIG[domain]
    
    # create_model(ModelName, **fields)
    return create_model(
        f"{domain.capitalize()}Metadata",
        **config["fields"]
    )