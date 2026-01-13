import json
import os
import asyncio
from typing import AsyncGenerator, List
from dotenv import load_dotenv
from openai import OpenAI

# ✅ ใช้ Repo ตัวใหม่ (ที่ยิง API + Async)
from app.repositories.copilot_repo import CopilotRepository

load_dotenv()

class CopilotAgent:
    def __init__(self):
        # 1. Init Repository
        self.repo = CopilotRepository()
        
        # 2. Init OpenAI Client
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model_name = "gpt-4o" 
        self.embedding_model = "text-embedding-3-small"

    async def run_workflow(self, user_query: str, case_id: str) -> AsyncGenerator[str, None]:
        """
        Real Workflow:
        1. Load Case Context (API -> SQL)
        2. RAG Search (Vector DB) -> Send Evidence
        3. LLM Generation (Stream)
        """
        
        # --- STEP 1: Context Gathering (Case Data) ---
        yield self._format_event("trace", {
            "step_id": 1, "title": "Analyzing Context", 
            "status": "active", "desc": f"Loading case data for {case_id}..."
        })
        
        # ✅ เรียกข้อมูลแบบ Async (แก้ Timeout)
        case_data = await self.repo.get_case(case_id)
        audit_logs = await self.repo.get_audit_logs(case_id)
        
        if not case_data:
            yield self._format_event("trace", {
                "step_id": 1, "title": "Context Error", 
                "status": "failed", "desc": "Case ID not found."
            })
            yield self._format_event("message_chunk", {"text": "ขออภัยครับ ไม่พบข้อมูล Case ID นี้ในระบบ"})
            return

        # ✅ สร้าง Context String แบบฉลาด (Robust & Dynamic)
        case_context_str = self._build_smart_context(case_data, audit_logs)
        
        yield self._format_event("trace", {
            "step_id": 1, "title": "Analyzing Context", 
            "status": "completed", "desc": "Full case snapshot & Risk analysis loaded."
        })

        # --- STEP 2: RAG Knowledge Search ---
        yield self._format_event("trace", {
            "step_id": 2, "title": "Policy Search", 
            "status": "active", "desc": "Scanning policy documents (Vector DB)..."
        })

        # 2.1 Generate Embedding
        try:
            embedding_resp = self.client.embeddings.create(
                input=user_query,
                model=self.embedding_model
            )
            query_embedding = embedding_resp.data[0].embedding

            # 2.2 Search Vector
            matches = self.repo.search_evidence(query_embedding, match_count=3)
        except Exception as e:
            print(f"Vector Search Error: {e}")
            matches = []
        
        rag_context_str = ""
        found_evidence = False

        if matches:
            found_evidence = True
            rag_context_str = "=== RELEVANT POLICIES (REFERENCE) ===\n"
            
            for idx, doc in enumerate(matches):
                score = doc.get('similarity', 0) * 100
                if score < 60: continue 

                # ส่ง Evidence ไปโชว์ที่หน้า UI
                yield self._format_event("evidence_reveal", {
                    "file_id": doc.get('doc_id', f"doc_{idx}"),
                    "file_name": doc.get('title', 'Unknown Policy'),
                    "highlight_text": doc.get('content', '')[:300] + "...", 
                    "score": int(score)
                })

                rag_context_str += f"[Ref ID: {doc.get('clause_id', 'N/A')}] {doc.get('content')}\nSource: {doc.get('title')}\n\n"
        
        else:
            rag_context_str = "No specific policy documents found related to this query."

        yield self._format_event("trace", {
            "step_id": 2, "title": "Policy Search", 
            "status": "completed", 
            "desc": f"Found {len(matches)} relevant references." if found_evidence else "No references found."
        })

        # --- STEP 3: Reasoning & Response (LLM) ---
        yield self._format_event("trace", {
            "step_id": 3, "title": "Final Reasoning", 
            "status": "active", "desc": "Synthesizing answer with GPT-4o..."
        })

        # 3.1 Construct System Prompt
        system_prompt = f"""
        You are an expert Decision Control Copilot (AI Assistant).
        Analyze the provided CASE DATA and POLICY EVIDENCE to answer the user's question.

        GOAL: Provide accurate, helpful answers based on the 'CASE SNAPSHOT', 'RISK ANALYSIS', and 'AUDIT LOGS'.

        RULES:
        - Answer in Thai language (Natural & Professional).
        - If the user asks for specific details (like PO Number, Vendor, Amount), look at the [CASE SNAPSHOT] section.
        - Use the [RISK ANALYSIS] to explain why a case is flagged.
        - If referencing policy, cite the source clearly.
        - Be concise.

        {case_context_str}

        {rag_context_str}
        """

        # 3.2 Call OpenAI Stream
        try:
            stream = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_query}
                ],
                temperature=0.3,
                stream=True
            )

            # 3.3 Streaming Response
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    text_chunk = chunk.choices[0].delta.content
                    yield self._format_event("message_chunk", {"text": text_chunk})

        except Exception as e:
            yield self._format_event("message_chunk", {"text": f"\n\n[System Error] LLM Processing failed: {str(e)}"})

        yield self._format_event("trace", {
            "step_id": 3, "title": "Final Reasoning", 
            "status": "completed", "desc": "Response generated."
        })

    # ------------------------------------------------------------------
    # Helper Methods
    # ------------------------------------------------------------------
    def _format_event(self, event_type: str, data: dict) -> str:
        """Format data as Server-Sent Events (JSON line)"""
        return json.dumps({"type": event_type, "data": data}) + "\n"

    def _build_smart_context(self, data: dict, audits: List[dict]) -> str:
        """
        แปลง JSON Structure (จาก API) ให้เป็น Text สวยๆ
        Features:
        - Robust Parsing: ป้องกัน Error ถ้า Data ไม่ครบ หรือ Type ผิด
        - Dynamic Snapshot: กวาดทุก Key ใน Payload มาแสดง (เช่น PO Number)
        - Reverse Audit: เรียง Log ใหม่เอาล่าสุดขึ้นก่อน
        """
        # 1. Handle Nested Structure (Safety Check)
        raw = data.get('raw', {})
        if not isinstance(raw, dict): raw = {}
        
        payload = raw.get('payload', {}) if isinstance(raw, dict) else {}
        # Fallback Logic: ถ้าไม่เจอใน raw ให้หาใน root
        if not payload and isinstance(data, dict) and 'payload' in data: 
             payload = data['payload']
        if not isinstance(payload, dict): payload = {}

        summary = data.get('decision_summary', {}) if isinstance(data.get('decision_summary'), dict) else {}
        story = data.get('story', {}) if isinstance(data.get('story'), dict) else {}

        # 2. Dynamic Snapshot (กวาดข้อมูล Metadata ทั้งหมด)
        snapshot_lines = []
        
        # ฟิลด์ที่ดึงแยกไปโชว์ที่อื่นแล้ว ไม่ต้องเอามาซ้ำใน Snapshot
        exclude_keys = ['line_items', 'last_rule_results', 'risk_drivers', 'description', 'payload', 'raw', 'story', 'decision_summary']
        
        # เพิ่ม ID และ Status หลักก่อน
        if data.get('id') or data.get('case_id'): 
            snapshot_lines.append(f"Case ID: {data.get('id') or data.get('case_id')}")
        if data.get('status'): 
            snapshot_lines.append(f"Status: {data.get('status')}")
            
        # วนลูปดึงข้อมูลใน Payload
        for key, val in payload.items():
            if key not in exclude_keys and not isinstance(val, (list, dict)):
                # จัด Format Key ให้อ่านง่าย (เช่น "po_number" -> "Po Number")
                readable_key = key.replace('_', ' ').title()
                snapshot_lines.append(f"{readable_key}: {val}")
        
        snapshot_txt = "\n".join(snapshot_lines)

        # 3. Extract Risk Story
        risk_drivers_txt = ""
        risk_drivers = story.get('risk_drivers', [])
        if isinstance(risk_drivers, list):
            for driver in risk_drivers:
                if isinstance(driver, dict):
                    risk_drivers_txt += f"- [RISK] {driver.get('label')}: {driver.get('detail')}\n"
            
        suggested_action = story.get('suggested_action', {}) if isinstance(story.get('suggested_action'), dict) else {}
        action_txt = f"Action: {suggested_action.get('title', '-')} ({suggested_action.get('description', '')})"

        # 4. Extract Line Items
        items_txt = ""
        line_items = payload.get('line_items', [])
        if isinstance(line_items, list) and line_items:
            for item in line_items:
                if isinstance(item, dict):
                    desc = item.get('item_desc') or item.get('description') or 'Item'
                    qty = item.get('quantity', 0)
                    price = item.get('total_price') or (item.get('unit_price', 0) * int(qty or 0))
                    items_txt += f"- {desc} (Qty: {qty}, Total: {price:,.2f})\n"
        else:
            items_txt = "- No items detail found."

        # 5. Extract Audit Logs (Safe Parsing & Sort)
        audit_txt = ""
        if isinstance(audits, list):
            # เรียงจาก ใหม่ -> เก่า (Reverse)
            sorted_audits = sorted(audits, key=lambda x: x.get('created_at', ''), reverse=True)
            
            for a in sorted_audits[:8]: # 8 รายการล่าสุด
                if not isinstance(a, dict): continue

                action = a.get('action') or a.get('event_type') or 'Unknown Event'
                
                # Check Actor Type (Dict or Str)
                actor_obj = a.get('actor')
                if isinstance(actor_obj, dict): 
                    actor = actor_obj.get('name', 'System')
                elif isinstance(actor_obj, str): 
                    actor = actor_obj
                else: 
                    actor = 'System'

                timestamp = str(a.get('created_at', ''))[:16].replace('T', ' ')
                audit_txt += f"- {timestamp}: {action} by {actor}\n"

        return f"""
        === CASE CONTEXT ===
        
        [CASE SNAPSHOT]
        {snapshot_txt}
        
        [RISK ANALYSIS]
        {risk_drivers_txt if risk_drivers_txt else "- No critical risk drivers identified."}
        
        [SUGGESTED ACTION]
        {action_txt}

        [LINE ITEMS]
        {items_txt}

        [LATEST AUDIT LOGS (Newest First)]
        {audit_txt if audit_txt else "- No audit history available."}
        ====================
        """