import os
from openai import OpenAI
from app.db.supabase_client import supabase

class RAGQueryService:
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.embedding_model = "text-embedding-3-small"

    def search(self, query: str, top_k: int = 5):
        emb = self.client.embeddings.create(
            model=self.embedding_model,
            input=query
        ).data[0].embedding

        res = supabase.rpc(
            "rag_search_chunks",
            {
                "query_embedding": emb,
                "match_count": top_k
            }
        ).execute()

        return res.data or []
