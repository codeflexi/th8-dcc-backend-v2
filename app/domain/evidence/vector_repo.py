# STEP 4: Vector Evidence Repository (Mock Supabase)

class VectorEvidenceRepo:
    def search_clauses(self, contract_id: str, query: str):
        # Real system:
        # 1. Embed query
        # 2. Similarity search via pgvector
        # 3. Filter by metadata.contract_id

        return [{
            "evidence_id": "EV-CL-01",
            "source": "vector",
            "document_id": contract_id,
            "clause_id": "C-7.2",
            "content": "Advance payment is not allowed under this contract.",
            "score": 0.91
        }]
