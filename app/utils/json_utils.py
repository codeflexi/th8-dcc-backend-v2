import collections.abc

import json
from typing import Any, List, Dict, Union, Optional
from datetime import datetime, date
from decimal import Decimal
from pydantic import BaseModel

def get_nested_value(data: Dict[str, Any], path: str, default: Any = None) -> Any:
    """
    พระเอกของงาน: ดึงค่าจาก Nested JSON ด้วย String Path อย่างปลอดภัย
    เหมือน Lodash.get() ใน JavaScript
    
    Usage:
        val = get_nested_value(case_data, "payload.line_items.0.total_price", 0)
    """
    if not path:
        return default

    # แยก path ด้วยจุด (รองรับ array index ด้วย)
    keys = path.split('.')
    current = data

    try:
        for key in keys:
            # กรณี current เป็น Dict
            if isinstance(current, dict):
                current = current.get(key)
            # กรณี current เป็น List และ key เป็นตัวเลข (เช่น '0')
            elif isinstance(current, list) and key.isdigit():
                idx = int(key)
                if 0 <= idx < len(current):
                    current = current[idx]
                else:
                    return default
            # ถ้าไม่ใช่ทั้ง Dict และ List แต่ยังมี key ต่อ
            else:
                return default

            # ถ้าค่าที่ได้เป็น None ระหว่างทาง ให้หยุดและคืน default
            if current is None:
                return default
                
        return current
    except Exception:
        return default

def json_serializer(obj: Any) -> Any:
    """
    ตัวช่วยเวลา Save JSON ลง Database เพื่อแก้ปัญหา
    TypeError: Object of type datetime is not JSON serializable
    """
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj) # หรือ str(obj) ถ้าต้องการความแม่นยำสูงมาก
    if isinstance(obj, BaseModel):
        return obj.model_dump()
    if hasattr(obj, '__dict__'):
        return obj.__dict__
    
    # ถ้ายังไม่รู้จัก ให้แปลงเป็น String ไปเลยกันตาย
    return str(obj)

def safe_json_loads(json_str: str, default: Any = None) -> Any:
    """
    กันเหนียวเวลา parse string ที่ได้มาจาก LLM หรือ API อื่น
    """
    if not json_str:
        return default
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return default

def deep_update(source, overrides):
    """
    ฟังก์ชันเทพสำหรับ Merge Dict ซ้อน Dict
    source: ของเก่า (Old Data)
    overrides: ของใหม่ (New Data)
    """
    for key, value in overrides.items():
        if isinstance(value, collections.abc.Mapping) and value:
            returned = deep_update(source.get(key, {}), value)
            source[key] = returned
        else:
            source[key] = overrides[key]
    return source



# # app/services/case_service.py
# from app.utils.json_utils import get_nested_value

# def resolve_display_schema(case_data: dict, schema_template: dict):
#     resolved_header = []
    
#     # สมมติ schema_template คือ:
#     # [{"label": "PO Number", "value_path": "payload.po_number"}, ...]

#     for field in schema_template.get("header_attributes", []):
#         path = field.get("value_path")
        
#         # 🔥 เรียกใช้ Utility ตรงนี้!
#         # ไม่ต้องกลัว error แม้ path จะลึกแค่ไหน หรือไม่มีอยู่จริง
#         actual_value = get_nested_value(case_data, path, default="-")
        
#         resolved_header.append({
#             "label": field["label"],
#             "value": actual_value, # ได้ค่าออกมาโชว์เลย
#             "type": field.get("type", "text")
#         })
        
#     return resolved_header

# import json
# from app.utils.json_utils import json_serializer

# async def save_case_to_db(case_obj: CaseModel):
#     # สมมติ case_obj มี field created_at เป็น datetime
    
#     # แปลงเป็น dict ก่อน
#     data_dict = case_obj.model_dump()
    
#     # ถ้าใช้ Driver ที่ไม่ฉลาด ต้อง dumps เป็น string เอง
#     # ใช้ default=json_serializer เพื่อจัดการ datetime/decimal
#     json_string = json.dumps(data_dict, default=json_serializer)
    
#     # ... code insert db ...