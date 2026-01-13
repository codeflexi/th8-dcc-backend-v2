import json
import os
import asyncio
from typing import AsyncGenerator, List
from dotenv import load_dotenv
from openai import OpenAI

# Import Repository ที่เราสร้างไว้
from app.repositories.supabase_repo import SupabaseCaseRepository

load_dotenv()

class CopilotAgent:
    def __init__(self):
        # 1. Init Repository
        self.repo = SupabaseCaseRepository()
        
        # 2. Init OpenAI Client
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model_name = "gpt-4o" # หรือ gpt-3.5-turbo
        self.embedding_model = "text-embedding-3-small"

    async def run_workflow(self, user_query: str, case_id: str) -> AsyncGenerator[str, None]:
        """
        Real Workflow:
        1. Load Case Context (SQL)
        2. RAG Search (Vector) -> Send Evidence
        3. LLM Generation (Stream)
        """
        
        # --- STEP 1: Context Gathering (Case Data) ---
        yield self._format_event("trace", {
            "step_id": 1, "title": "Analyzing Context", 
            "status": "active", "desc": f"Loading case data for {case_id}..."
        })
        
        # เรียกข้อมูลจาก Repo (Case + Audit Logs)
        case_data = self.repo.get_case(case_id)
        audit_logs = self.repo.get_audit_logs(case_id)
        
        if not case_data:
            yield self._format_event("trace", {
                "step_id": 1, "title": "Context Error", 
                "status": "failed", "desc": "Case ID not found in database."
            })
            yield self._format_event("message_chunk", {"text": "ขออภัยครับ ไม่พบข้อมูล Case ID นี้ในระบบ"})
            return

        # สร้าง Context String สำหรับ Prompt
        case_context_str = self._build_case_context(case_data, audit_logs)
        
        yield self._format_event("trace", {
            "step_id": 1, "title": "Analyzing Context", 
            "status": "completed", "desc": "Case context loaded successfully."
        })

        # --- STEP 2: RAG Knowledge Search ---
        yield self._format_event("trace", {
            "step_id": 2, "title": "Policy Search", 
            "status": "active", "desc": "Scanning policy documents (Vector DB)..."
        })

        # 2.1 Generate Embedding จากคำถาม
        embedding_resp = self.client.embeddings.create(
            input=user_query,
            model=self.embedding_model
        )
        query_embedding = embedding_resp.data[0].embedding

        # 2.2 Search Vector ใน Supabase
        matches = self.repo.search_evidence(query_embedding, match_count=3)
        
        rag_context_str = ""
        found_evidence = False

        if matches:
            found_evidence = True
            rag_context_str = "=== RELEVANT POLICIES ===\n"
            
            for idx, doc in enumerate(matches):
                # กรองความแม่นยำ (Threshold)
                score = doc.get('similarity', 0) * 100
                if score < 60: continue # ถ้าคะแนนต่ำกว่า 60% ไม่เอา

                # ส่ง Evidence ไปโชว์ที่หน้า UI (Highlight สีส้ม)
                yield self._format_event("evidence_reveal", {
                    "file_id": doc.get('doc_id', f"doc_{idx}"),
                    "file_name": doc.get('title', 'Unknown Policy'),
                    "highlight_text": doc.get('content', '')[:200] + "...", # ตัดให้สั้นหน่อยสำหรับการโชว์
                    "score": int(score)
                })

                # เก็บใส่ Prompt
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
        You are an expert Procurement Copilot (AI Assistant).
        Analyze the provided CASE DATA and POLICY EVIDENCE to answer the user's question.

        RULES:
        - Answer in Thai language (Natural & Professional).
        - Base your answer primarily on the 'Case Data' and 'Policy Evidence'.
        - If finding a violation, clearly state the rule/clause ID.
        - Be concise but helpful.

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
            full_response = ""
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    text_chunk = chunk.choices[0].delta.content
                    full_response += text_chunk
                    yield self._format_event("message_chunk", {"text": text_chunk})
                    # await asyncio.sleep(0.01) # Optional: Smooth out valid chunking if needed

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

    def _build_case_context(self, case: dict, audits: List[dict]) -> str:
        """Convert dict data to readable string for LLM"""
        # แกะข้อมูลเบื้องต้น
        status = case.get('status', 'Unknown')
        vendor = case.get('vendor_name', case.get('vendor', 'Unknown'))
        total = case.get('amount_total', case.get('total_amount', 0))
        desc = case.get('description', '-')
        
        # แกะรายการสินค้า
        items_str = ""
        items = case.get('line_items', [])
        for i in items:
            items_str += f"- {i.get('item_desc')} (Qty: {i.get('quantity')}, Price: {i.get('unit_price')})\n"

        # แกะ Audit Log (ประวัติความเสี่ยง)
        audit_str = ""
        for a in audits:
            if a.get('event_type') == 'RULE_EVALUATED':
                payload = a.get('payload', {})
                rule_id = payload.get('rule', {}).get('id', 'Unknown')
                hit = payload.get('hit', False)
                icon = "RISK DETECTED" if hit else "PASS"
                audit_str += f"- [{icon}] Rule: {rule_id}\n"

        return f"""
        === CASE DATA ===
        ID: {case.get('case_id')}
        Status: {status}
        Vendor: {vendor}
        Total Amount: {total:,.2f}
        Description: {desc}

        [Items]
        {items_str}

        [System Checks / History]
        {audit_str if audit_str else "No audit logs available."}
        =================
        """