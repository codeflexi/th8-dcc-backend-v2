from __future__ import annotations
import json
from typing import AsyncGenerator, List, Dict, Any
from openai import OpenAI

# from app.repositories.copilot_repo import CopilotRepository
from app.repositories.rag_repo import CopilotRepositoryAgent




class CopilotOrchestrator:
    """
    Enterprise-grade RAG-first Copilot Orchestrator

    Steps:
      1. SEARCH   (Embedding)
      2. RAG      (Vector search + evidence)
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
        llm_started = False

        try:
            # =====================================================
            # STEP 1 — SEARCH (Embedding)
            # =====================================================
            yield self._trace(
                step_id=1,
                title="SEARCH",
                status="active",
                desc="Embedding user question",
            )

            embedding = self._embed(question)

            yield self._trace(
                step_id=1,
                title="SEARCH",
                status="completed",
                desc="Embedding completed",
            )

            # =====================================================
            # STEP 2 — RAG (Vector search)
            # =====================================================
            yield self._trace(
                step_id=2,
                title="RAG",
                status="active",
                desc="Searching contract & policy knowledge base",
            )

            chunks = self.repo.rag_search_chunks(
                embedding=embedding,
                top_k=5,
            )

            for c in chunks:
                used_chunks.append(c)

                # Evidence event → frontend (PDF jump / highlight)
                yield self._event(
                    "evidence_reveal",
                    {
                        "chunk_id": c.get("chunk_id"),
                        "content": c.get("content"),
                        "citation": c.get("citation"),
                        "similarity": round(float(c.get("similarity", 0)), 3),
                    },
                )

            yield self._trace(
                step_id=2,
                title="RAG",
                status="completed",
                desc=f"Found {len(used_chunks)} relevant chunks",
            )

            # =====================================================
            # STEP 3 — LLM (Streaming reasoning)
            # =====================================================
            yield self._trace(
                step_id=3,
                title="LLM",
                status="active",
                desc="Generating grounded answer",
            )
            llm_started = True

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

            full_answer = ""

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
            )

            # =====================================================
            # STEP 4 — FINAL (Confidence / Coverage + Audit)
            # =====================================================
            confidence = self._estimate_confidence(used_chunks)
            coverage = min(len(used_chunks) / 5, 1.0)

            yield self._trace(
                step_id=4,
                title="FINAL",
                status="completed",
                desc=f"Confidence {confidence:.2f}, Coverage {coverage:.2f}",
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
            yield self._trace(
                step_id=99,
                title="ERROR",
                status="completed",
                desc=str(e),
            )
            raise

        finally:
            # 🔒 ป้องกัน workflow ค้าง (สำคัญมาก)
            if llm_started:
                yield self._trace(
                    step_id=3,
                    title="LLM",
                    status="completed",
                    desc="LLM stream closed",
                )

    # =========================================================
    # Helpers
    # =========================================================
    def _embed(self, text: str) -> List[float]:
        res = self.client.embeddings.create(
            model=self.embedding_model,
            input=text,
        )
        return res.data[0].embedding

    def _build_rag_context(self, chunks: List[Dict[str, Any]]) -> str:
        """
        Build evidence block for LLM (enterprise, citation-first)
        """
        blocks = []

        for i, c in enumerate(chunks, start=1):
            citation = c.get("citation") or {}

            blocks.append(
                f"""
[Evidence {i}]
Content:
{c.get("content")}

Citation:
{json.dumps(citation, ensure_ascii=False)}
Similarity: {round(float(c.get("similarity", 0)), 3)}
"""
            )

        return "\n".join(blocks)

    def _build_system_prompt(self, rag_context: str) -> str:
        return f"""
You are an Enterprise Contract Copilot for executives and auditors.

ROLE:
- First, answer the user's question in clear, concise Thai (2–5 sentences).
- Summarize the meaning. Do NOT copy long clauses.
- Use business language suitable for executives.

CITATION RULES:
- Add inline citation numbers like ¹ ² ³ in the answer where relevant.
- Do NOT repeat full evidence text in the answer.
- Evidence is shown separately to the user.

WHEN EVIDENCE IS WEAK:
- Say clearly that the answer is based on limited evidence.

EVIDENCE (for grounding only):
{rag_context}
"""


    def _estimate_confidence(self, chunks: List[Dict[str, Any]]) -> float:
        if not chunks:
            return 0.0
        scores = [float(c.get("similarity", 0)) for c in chunks]
        return sum(scores) / len(scores)

    def _build_why_this_answer(self, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Explanation for auditor: why this answer is trustworthy
        """
        reasons = []

        for c in chunks:
            citation = c.get("citation") or {}
            reasons.append(
                {
                    "chunk_id": c.get("chunk_id"),
                    "contract_id": citation.get("contract_id"),
                    "clause_id": citation.get("clause_id"),
                    "page": citation.get("page"),
                    "source_uri": citation.get("source_uri"),
                    "similarity": round(float(c.get("similarity", 0)), 3),
                }
            )

        return reasons

    # =========================================================
    # SSE helpers
    # =========================================================
    def _trace(self, step_id: int, title: str, status: str, desc: str) -> str:
        return self._event(
            "trace",
            {
                "step_id": step_id,
                "title": title,
                "status": status,
                "desc": desc,
            },
        )

    def _event(self, event_type: str, data: dict) -> str:
        return json.dumps(
            {
                "type": event_type,
                "data": data,
            },
            ensure_ascii=False,
        ) + "\n"
