from __future__ import annotations
from typing import List, Dict, Any
from app.db.supabase_client import supabase


class CopilotRAGRepository:
    """
    RAG-only Repository สำหรับ Copilot Workstation
    ใช้เฉพาะ Vector Search + Evidence
    """

    def rag_search_chunks(
        self,
        embedding: List[float],
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        MUST return schema ที่ frontend ใช้จริง
        """

        try:
            res = supabase.rpc(
                "rag_search_chunks",
                {
                    "query_embedding": embedding,
                    "match_count": top_k,
                },
            ).execute()

            rows = res.data or []
            results: List[Dict[str, Any]] = []

            for r in rows:
                citation = r.get("citation") or {}

                results.append(
                    {
                        "chunk_id": r.get("chunk_id"),
                        "content": r.get("content"),
                        "similarity": float(r.get("similarity", 0)),
                        "citation": {
                            "contract_id": citation.get("contract_id"),
                            "clause_id": citation.get("clause_id"),
                            "page": citation.get("page"),
                            "source_uri": citation.get("source_uri"),
                        },
                    }
                )

            return results

        except Exception as e:
            print(f"[CopilotRAGRepository] error: {e}")
            return []
