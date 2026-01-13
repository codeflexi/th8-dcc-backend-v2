# test_copilot_run.py
import asyncio
import os
from dotenv import load_dotenv

# Import Service ที่เราเพิ่งแก้
from app.services.copilot_service import CopilotService 

# Load .env เพื่อให้มีค่า OPENAI_API_KEY, SUPABASE_URL
load_dotenv()

async def test_workflow():
    print("🚀 Starting Copilot Test...")
    
    # 1. Init Service
    service = CopilotService()
    
    # 2. Mock Input (ใช้ Case ID ที่มีจริงใน DB ของคุณ)
    case_id = "CASE-PO-2026-1057" 
    user_query = "ราคานี้ผิดปกติไหมเมื่อเทียบกับสัญญา?"

    print(f"🔎 Testing Case: {case_id}")
    print(f"❓ Query: {user_query}\n")
    print("-" * 50)

    # 3. Run Workflow (Simulate Streaming)
    try:
        async for chunk in service.run_workflow(user_query, case_id):
            # chunk ที่ได้จะเป็น JSON String บรรทัดเดียว
            print(chunk.strip()) 
            
            # (Optional) ถ้าอยากเห็น Text ที่ AI ตอบแบบต่อกัน
            # import json
            # data = json.loads(chunk)
            # if data['type'] == 'message_chunk':
            #     print(data['data']['text'], end="", flush=True)

    except Exception as e:
        print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_workflow())