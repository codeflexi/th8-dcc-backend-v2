import random
import string
from datetime import datetime

def generate_case_id(domain_prefix: str = "PO") -> str:
    """
    Generate ID: CASE-{PREFIX}-{YEAR}-{RUNNING/RANDOM}
    Ex: CASE-PO-2026-6096
    """
    year = datetime.now().year
    # ใน Production ควรใช้ Sequence จาก DB หรือ Redis เพื่อไม่ให้ซ้ำ
    # อันนี้แบบ Mock Random
    suffix = ''.join(random.choices(string.digits, k=4))
    return f"CASE-{domain_prefix}-{year}-{suffix}"

def generate_uuid() -> str:
    import uuid
    return str(uuid.uuid4())