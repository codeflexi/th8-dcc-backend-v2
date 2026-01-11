from typing import List, Dict, Optional
from supabase import create_client
import os

class EvidenceRetriever:
    """
    Phase B:
    - Vector-only retrieval
    - No audit
    - No attachment
    """

    def __init__(self):
        self.supabase = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )

    def search(
        self,
        *,
        query_embedding: List[float],
        policy_id: Optional[str] = None,
        limit: int = 5,
    ) -> List[Dict]:
        """
        Call Supabase SQL function: match_evidence
        """
        params = {
            "query_embedding": query_embedding,
            "match_count": limit,
            "filter_policy_id": policy_id,
        }

        resp = self.supabase.rpc("match_evidence", params).execute()

        return resp.data or []
