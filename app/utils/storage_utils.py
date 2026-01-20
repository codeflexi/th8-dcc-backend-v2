# app/utils/storage_utils.py
import boto3
from botocore.exceptions import ClientError

# สมมติว่า Config ไว้แล้ว
S3_BUCKET = "th8-sense-documents"

def generate_presigned_url(object_name: str, expiration=300) -> str:
    """สร้าง Link ชั่วคราว 5 นาที (300 วิ)"""
    s3 = boto3.client('s3') # ปกติควร Inject client เข้ามา
    try:
        response = s3.generate_presigned_url('get_object',
                                            Params={'Bucket': S3_BUCKET,
                                                    'Key': object_name},
                                            ExpiresIn=expiration)
        return response
    except ClientError:
        return None
    
    
#     # app/services/document_service.py
# from app.utils.storage_utils import generate_presigned_url

# def get_evidence_link(doc_id: str):
#     # สมมติว่า map doc_id กับ path ใน db แล้ว
#     file_path = f"contracts/2026/{doc_id}.pdf"
    
#     # 🔥 เรียก Utility
#     secure_link = generate_presigned_url(file_path)
    
#     return {
#         "doc_id": doc_id,
#         "url": secure_link, # Frontend เอาไปใส่ <iframe src="..."> ได้เลย
#         "expires_in": "5 minutes"
#     }