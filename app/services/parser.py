import os
from llama_parse import LlamaParse
from app.core.config import settings
from typing import List, Dict, Any

# สร้าง Class ง่ายๆ เพื่อห่อข้อมูล
class ParsedDocument:
    def __init__(self, text: str, metadata: Dict[str, Any]):
        self.text = text
        self.metadata = metadata

async def parse_pdf_with_metadata(file_path: str) -> List[ParsedDocument]:
    """
    ใช้ LlamaParse แต่รอบนี้ขอ Metadata (เลขหน้า) กลับมาด้วย
    """
    try:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        print(f"🦙 LlamaParsing with Metadata: {file_path}...")

        parser = LlamaParse(
            api_key=settings.LLAMA_CLOUD_API_KEY,
            result_type="markdown", 
            verbose=True,
            language="en",
        )

        # LlamaParse คืนค่ามาเป็น List[Document] โดย 1 Document = 1 หน้า (โดยประมาณ)
        llama_docs = await parser.aload_data(file_path)
        
        results = []
        for doc in llama_docs:
            # ดึง Text และ Metadata ที่ LlamaParse ให้มา
            # Metadata ปกติจะมี 'page_label' หรือ 'file_name' ติดมา
            results.append(ParsedDocument(
                text=doc.text,
                metadata=doc.metadata  # นี่คือพระเอกของเรา! จะมีเลขหน้าอยู่ในนี้
            ))
            
        return results

    except Exception as e:
        print(f"❌ LlamaParse Error: {str(e)}")
        raise e