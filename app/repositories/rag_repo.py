from typing import List, Dict, Any
from app.db.supabase_client import supabase


class CopilotRepositoryAgent:
    """
    Minimal RAG Repository
    ใช้ให้ CopilotOrchestrator ทำงานได้ทันที
    """

    def rag_search_chunks(
        self,
        embedding: List[float],
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        try:
            res = supabase.rpc(
                "rag_search_chunks",
                {
                    "query_embedding": embedding,
                    "match_count": top_k,
                },
            ).execute()

            rows = res.data or []

            results = []
            for r in rows:
                citation = r.get("citation") or {}
                results.append(
                    {
                        "chunk_id": r.get("chunk_id"),
                        "content": r.get("content"),
                        "similarity": r.get("similarity"),
                        "citation": citation,
                    }
                )

            return results

        except Exception as e:
            print("[RAG_REPO] error:", e)
            return []
