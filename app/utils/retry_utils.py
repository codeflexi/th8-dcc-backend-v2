# app/utils/retry_utils.py
import time
import functools
import logging

logger = logging.getLogger(__name__)

def retry_with_backoff(retries=3, delay=1):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            attempts = 0
            while attempts < retries:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    attempts += 1
                    wait = delay * (2 ** (attempts - 1)) # 1s, 2s, 4s
                    logger.warning(f"⚠️ API Error: {e}. Retrying in {wait}s...")
                    time.sleep(wait)
            return func(*args, **kwargs) # ครั้งสุดท้ายถ้าพังก็ให้พังเลย
        return wrapper
    return decorator


# # app/services/erp_service.py
# from app.utils.retry_utils import retry_with_backoff
# import httpx

# class ERPService:
    
#     # 🔥 แปะ Decorator ไว้บนหัวฟังก์ชันที่เสี่ยง Error
#     @retry_with_backoff(retries=3, delay=2)
#     def check_budget_status(self, department_id: str):
#         print(f"Connecting to ERP... for {department_id}")
        
#         # สมมติ Code ยิง API
#         response = httpx.get(f"https://sap-erp.internal/budget/{department_id}")
#         response.raise_for_status()
        
#         return response.json()