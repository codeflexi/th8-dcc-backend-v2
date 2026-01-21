import os
from fastapi import UploadFile
from app.db.supabase_client import supabase

BUCKET_NAME = "raw_documents"  # อย่าลืมไปสร้าง Bucket ใน Supabase Dashboard และตั้งเป็น Private

async def upload_file_to_supabase(file: UploadFile, file_content: bytes) -> str:
    """
    Upload file to Supabase Storage and return the storage path
    """
    file_ext = os.path.splitext(file.filename)[1]
    # ตั้งชื่อไฟล์ใน Bucket (ควร Unique) เช่น 2026/01/uuid.pdf
    # แต่อย่างง่ายใช้ filename ไปก่อน หรือจะใช้ hash ก็ดี
    storage_path = f"raw_uploads/{file.filename}" 

    try:
        # Upload
        res = supabase.storage.from_(BUCKET_NAME).upload(
            path=storage_path,
            file=file_content,
            file_options={"content-type": file.content_type, "x-upsert": "true"}
        )
        # return path ที่แท้จริงกลับไป (ไม่ใช่ URL)
        return storage_path

    except Exception as e:
        print(f"❌ Storage Upload Error: {e}")
        raise e

def get_signed_url(storage_path: str, expiry_seconds: int = 3600) -> str:
    """
    สร้าง URL ชั่วคราวสำหรับเปิดไฟล์ (ใช้ตอน Frontend จะเปิดดู)
    """
    try:
        res = supabase.storage.from_(BUCKET_NAME).create_signed_url(
            path=storage_path, 
            expires_in=expiry_seconds
        )
        return res['signedURL'] # หรือ res if version เก่า
    except Exception as e:
        print(f"❌ Signed URL Error: {e}")
        return None