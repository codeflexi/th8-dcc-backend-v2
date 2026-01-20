# app/utils/pdf_utils.py

def normalize_box_coordinates(box: dict, page_w: float, page_h: float) -> dict:
    """
    แปลง Pixel -> Percentage (%)
    Input: {x:100, y:100, w:50, h:20}, page: 1000x2000
    Output: {x:10.0, y:5.0, w:5.0, h:1.0}
    """
    if page_w == 0 or page_h == 0: return box
    
    return {
        "x": round((box['x'] / page_w) * 100, 2),
        "y": round((box['y'] / page_h) * 100, 2),
        "w": round((box['w'] / page_w) * 100, 2),
        "h": round((box['h'] / page_h) * 100, 2),
        "page": box.get("page", 1)
    }

def build_pdf_view_url(source_uri: str, page: int | None = None) -> str:
    """
    Convert supabase://bucket/path.pdf → https://...#page=12
    """
    # ตัวอย่าง (ปรับตาม infra คุณ)
    base_url = source_uri.replace(
        "supabase://",
        "https://YOUR_PROJECT_ID.supabase.co/storage/v1/object/public/"
    )
    if page:
        return f"{base_url}#page={page}"
    return base_url
    
    
#     # app/services/case_service.py
# from app.utils.pdf_utils import normalize_box_coordinates

# def process_evidence(raw_evidence):
#     # สมมติเรารู้ขนาดกระดาษ A4 (หรือดึงจาก Metadata PDF)
#     PAGE_WIDTH = 595.0
#     PAGE_HEIGHT = 842.0
    
#     raw_box = raw_evidence['highlight_box'] # {x: 50, y: 100...}
    
#     # 🔥 เรียก Utility แปลงค่า
#     web_ready_box = normalize_box_coordinates(raw_box, PAGE_WIDTH, PAGE_HEIGHT)
    
#     return {
#         "snippet": raw_evidence['text'],
#         "highlight_box": web_ready_box # ส่งค่า % ไปให้ Frontend
#     }