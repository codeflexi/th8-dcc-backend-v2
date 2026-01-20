import logging
import json
import sys

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_obj = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno
        }
        # ถ้ามี extra data ให้ใส่ไปด้วย
        if hasattr(record, "props"):
            log_obj.update(record.props)
            
        return json.dumps(log_obj)

def get_logger(name: str):
    logger = logging.getLogger(name)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


# app/services/case_service.py
from app.utils.time_utils import get_current_utc, calculate_sla_hours
from app.utils.currency_utils import calculate_variance_pct
from app.utils.logger import get_logger

# logger = get_logger(__name__)

# def process_case(raw_data):
#     logger.info(f"Processing case...", extra={"props": {"case_id": raw_data.id}})
    
#     # ใช้ Utility คำนวณ SLA
#     sla_hours = calculate_sla_hours(raw_data.created_at)
    
#     # ใช้ Utility คำนวณเงิน
#     variance = calculate_variance_pct(raw_data.actual_price, raw_data.contract_price)
    
#     return {
#         "sla": sla_hours,
#         "variance": variance
#     }