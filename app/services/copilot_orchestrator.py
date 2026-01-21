from __future__ import annotations
import json
from typing import AsyncGenerator, List, Dict, Any
from openai import OpenAI

# Import Supabase client เพื่อใช้บันทึก Audit Log
from app.db.supabase_client import supabase
# ตรวจสอบ path ให้ตรงกับที่คุณเก็บไฟล์ repository
from app.repositories.rag_repo import CopilotRepositoryAgent


class CopilotOrchestrator:
    """
    Enterprise-grade RAG-first Copilot Orchestrator

    Steps:
      1. SEARCH   (Embedding)
      2. RAG      (Vector search: Products + Contract Chunks)
      3. LLM      (Grounded reasoning, streaming)
      4. FINAL    (Confidence / coverage + audit explanation)
    """

    def __init__(self):
        self.repo = CopilotRepositoryAgent()
        self.client = OpenAI()

        self.llm_model = "gpt-4o"
        self.embedding_model = "text-embedding-3-small"

    # =========================================================
    # Public entry (used by FastAPI StreamingResponse)
    # =========================================================
    async def run(self, question: str) -> AsyncGenerator[str, None]:

        used_chunks: List[Dict[str, Any]] = []
        # ตัวแปรสำหรับเก็บ History การทำงานเพื่อบันทึกลง DB
        trace_history: List[Dict[str, Any]] = [] 
        llm_started = False
        full_answer = ""

        try:
            # =====================================================
            # STEP 1 — SEARCH (Embedding)
            # =====================================================
            yield self._trace(
                step_id=1,
                title="SEARCH",
                status="active",
                desc="Embedding user question",
                history_log=trace_history
            )

            embedding = self._embed(question)

            yield self._trace(
                step_id=1,
                title="SEARCH",
                status="completed",
                desc="Embedding completed",
                history_log=trace_history
            )

            # =====================================================
            # STEP 2 — RAG (Vector search)
            # =====================================================
            yield self._trace(
                step_id=2,
                title="RAG",
                status="active",
                desc="Searching contracts & product database",
                history_log=trace_history
            )
            
            # Debug log
            print(f"DEBUG ORCHESTRATOR: Searching for '{question}'")
            
            # 2.1 Search Products (Structured Data)
            products = self.repo.rag_search_products(
                query_text=question,
                embedding=embedding,
                top_k=3
            )

            # 2.2 Search Contracts (Unstructured Text)
            chunks = self.repo.rag_search_chunks(
                query_text=question,
                embedding=embedding,
                top_k=5
            )

            # รวมผลลัพธ์
            all_results = products + chunks

            for c in all_results:
                used_chunks.append(c)

                # Evidence event → frontend
                yield self._event(
                    "evidence_reveal",
                    {
                        "chunk_id": c.get("chunk_id"),
                        "content": c.get("content"),
                        "citation": c.get("citation"),
                        "similarity": round(float(c.get("similarity", 0)), 3),
                        "metadata": c.get("metadata"),
                        "type": c.get("type", "text_chunk"),
                        # ✅ เพิ่ม open_url ส่งไปให้ Frontend
                        "open_url": c.get("open_url")
                    },
                )

            yield self._trace(
                step_id=2,
                title="RAG",
                status="completed",
                desc=f"Found {len(products)} products, {len(chunks)} text chunks",
                history_log=trace_history
            )

            # =====================================================
            # STEP 3 — LLM (Streaming reasoning)
            # =====================================================
            yield self._trace(
                step_id=3,
                title="LLM",
                status="active",
                desc="Generating grounded answer",
                history_log=trace_history
            )
            llm_started = True

            # Build context
            rag_context = self._build_rag_context(used_chunks)
            system_prompt = self._build_system_prompt(rag_context)

            stream = self.client.chat.completions.create(
                model=self.llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question},
                ],
                temperature=0.2,
                stream=True,
            )

            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    text = delta.content
                    full_answer += text
                    yield self._event("message_chunk", {"text": text})

            yield self._trace(
                step_id=3,
                title="LLM",
                status="completed",
                desc="Answer generated",
                history_log=trace_history
            )

            # =====================================================
            # STEP 4 — FINAL (Confidence / Coverage + Audit)
            # =====================================================
            confidence = self._estimate_confidence(used_chunks)
            coverage = min(len(used_chunks) / 5, 1.0)

            # 🔥 เพิ่ม: บันทึกลง Database (Audit Log) ก่อนส่ง Final Event
            await self._save_audit_log(
                question=question,
                answer=full_answer,
                evidence=used_chunks,
                confidence=confidence,
                traces=trace_history
            )

            yield self._trace(
                step_id=4,
                title="FINAL",
                status="completed",
                desc=f"Confidence {confidence:.2f}, Coverage {coverage:.2f}",
                history_log=trace_history
            )

            yield self._event(
                "final",
                {
                    "confidence": round(confidence, 2),
                    "coverage": round(coverage, 2),
                    "why_this_answer": self._build_why_this_answer(used_chunks),
                },
            )

        except Exception as e:
            print(f"ORCHESTRATOR ERROR: {str(e)}")
            yield self._trace(
                step_id=99,
                title="ERROR",
                status="completed",
                desc=str(e),
                history_log=trace_history
            )
            raise

        finally:
            if llm_started:
                yield self._trace(
                    step_id=3,
                    title="LLM",
                    status="completed",
                    desc="LLM stream closed",
                )

    # =========================================================
    # Helpers: Core Logic
    # =========================================================
    def _embed(self, text: str) -> List[float]:
        res = self.client.embeddings.create(
            model=self.embedding_model,
            input=text,
        )
        return res.data[0].embedding

    def _build_rag_context(self, chunks: List[Dict[str, Any]]) -> str:
        blocks = []
        for i, c in enumerate(chunks, start=1):
            citation = c.get("citation") or {}
            meta = c.get("metadata") or {}
            doc_info = meta.get("document_info") or {}
            
            vendor = doc_info.get("vendor") or "Unknown Vendor"
            file_name = doc_info.get("file_name") or c.get("file_name") or "Unknown File"
            
            price_info = meta.get("price_info")
            price_str = ""
            if price_info:
                price_str = f"""
[DATA: PRICE RECORD]
Item Code: {price_info.get('item_code', 'N/A')}
Description: {price_info.get('description', 'N/A')}
Unit Price: {price_info.get('price', 'N/A')} {price_info.get('currency', '')}
UOM: {price_info.get('unit', '')}
Tier: {price_info.get('tier', 'Standard')}
"""

            blocks.append(
                f"""
[Evidence {i}]
[Source: {file_name}]
[Vendor: {vendor}]
{price_str}
Content:
{c.get("content")}

Citation:
{json.dumps(citation, ensure_ascii=False)}
Similarity: {round(float(c.get("similarity", 0)), 3)}
-----------------------------------
"""
            )

        return "\n".join(blocks)

    def _build_system_prompt(self, rag_context: str) -> str:
        return f"""
You are an Enterprise Contract Copilot for executives and auditors.

ROLE:
- Answer the user's question in clear, concise Thai (2–5 sentences).
- If the user asks for PRICE or ITEM details, use the [DATA: PRICE RECORD] section explicitly.
- Identify the vendor or contract name if relevant.
- Summarize contract clauses. Do NOT copy long text verbatim.
- Use professional business language.

IMPORTANT INSTRUCTIONS FOR EVIDENCE ANALYSIS:
1. **Look for Metadata/Header fields:** The evidence might be formatted as key-value pairs (e.g., "**Validity:** 2026-01-01"). You MUST use this information to answer questions about dates, validity, or contract IDs.
2. **Cross-Language Understanding:** The user asks in THAI, but the documents might be in ENGLISH. You must translate and interpret the English evidence (like "Validity", "Effective Date", "Term") to answer the Thai question correctly.
3. **Low Similarity Handling:** Even if the relevance score is low, if you see the EXACT answer in the text (like a specific date or price), USE IT.

CITATION RULES:
- Add inline citation numbers like [1] [2] in the answer where relevant.
- Do NOT repeat full evidence text in the answer.

WHEN EVIDENCE IS WEAK:
- Only say "Not found in documents" if the information is TRULY missing from the provided context chunks.
- If you found the date/price but are unsure if it applies, state the value and mention "According to the retrieved document snippet...".

EVIDENCE (Contract & Price Database):
{rag_context}
"""

    def _estimate_confidence(self, chunks: List[Dict[str, Any]]) -> float:
        if not chunks:
            return 0.0
        scores = [float(c.get("similarity", 0)) for c in chunks]
        return sum(scores) / len(scores)

    def _build_why_this_answer(self, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        reasons = []
        for c in chunks:
            citation = c.get("citation") or {}
            meta = c.get("metadata") or {}
            doc_info = meta.get("document_info") or {}
            
            reasons.append(
                {
                    "chunk_id": c.get("chunk_id"),
                    "contract_id": citation.get("contract_id"),
                    "clause_id": citation.get("clause_id"),
                    "page": citation.get("page"),
                    "source_uri": citation.get("source_uri"),
                    "vendor": doc_info.get("vendor"),
                    "file_name": doc_info.get("file_name"),
                    "similarity": round(float(c.get("similarity", 0)), 3),
                    "type": c.get("type", "text"),
                    # ✅ เพิ่ม open_url ในส่วนสรุปด้วย
                    "open_url": c.get("open_url")
                }
            )
        return reasons

    # =========================================================
    # Helpers: Audit Log & Events
    # =========================================================
    async def _save_audit_log(self, question: str, answer: str, evidence: List[Dict], confidence: float, traces: List[Dict] = None):
        """
        บันทึกประวัติการใช้งานลง Supabase
        """
        try:
            # Minify evidence เพื่อประหยัดพื้นที่ DB
            minified_evidence = [{
                "id": e.get("chunk_id"), 
                "source": e.get("file_name"),
                "type": e.get("type"),
                "similarity": e.get("similarity")
            } for e in evidence]

            supabase.table("copilot_audit_logs").insert({
                "user_question": question,
                "ai_answer": answer,
                "used_evidence": minified_evidence,
                "confidence_score": confidence,
                "trace_logs": traces
            }).execute()
            
            print("✅ Audit log saved successfully")
        except Exception as e:
            print(f"⚠️ Failed to save audit log: {e}")

    def _trace(self, step_id: int, title: str, status: str, desc: str, history_log: List = None) -> str:
        data = {
            "step_id": step_id,
            "title": title,
            "status": status,
            "desc": desc,
        }
        
        # เก็บลง history ถ้ามีการส่ง list เข้ามา
        if history_log is not None:
            history_log.append(data)
            
        return self._event("trace", data)

    def _event(self, event_type: str, data: dict) -> str:
        return json.dumps(
            {
                "type": event_type,
                "data": data,
            },
            ensure_ascii=False,
        ) + "\n"