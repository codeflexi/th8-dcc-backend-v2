import os, json
from openai import OpenAI
from app.repositories.copilot_repo import CopilotRepository

class CopilotStreamService:
    def __init__(self):
        self.repo = CopilotRepository()
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = "gpt-4o"

    async def stream(self, question: str):
        # Step 1: Vector Search
        yield self._evt("step", {"step": "RAG_SEARCH", "status": "STARTED"})

        chunks = self.repo.search_knowledge(question)

        yield self._evt("step", {
            "step": "RAG_SEARCH",
            "status": "COMPLETED",
            "found": len(chunks)
        })

        # Step 2: Evidence
        for c in chunks:
            yield self._evt("evidence", {
                "document_id": c["document_id"],
                "contract_id": c["contract_id"],
                "page": c.get("page"),
                "section": c.get("section"),
                "content": c["content"][:300],
                "similarity": round(c["similarity"], 3)
            })

        # Step 3: LLM Streaming
        yield self._evt("step", {"step": "LLM", "status": "STARTED"})

        context = "\n\n".join(
            f"[Contract {c['contract_id']} | Page {c.get('page')}]\n{c['content']}"
            for c in chunks
        )

        prompt = f"""
You are an Enterprise Contract Copilot.
Answer ONLY from evidence below.

{context}
"""

        stream = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": question}
            ],
            temperature=0.2,
            stream=True
        )

        for ch in stream:
            if ch.choices[0].delta.content:
                yield self._evt("token", {"text": ch.choices[0].delta.content})

        # Step 4: Confidence
        confidence = sum(c["similarity"] for c in chunks) / max(len(chunks), 1)
        coverage = min(1.0, len(chunks) / 5)

        yield self._evt("final", {
            "confidence": round(confidence, 2),
            "coverage": round(coverage, 2)
        })

    def _evt(self, t: str, data: dict):
        return json.dumps({"type": t, "data": data}) + "\n"
