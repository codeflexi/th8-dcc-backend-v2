from __future__ import annotations

import os
from dotenv import load_dotenv
from supabase import create_client
from openai import OpenAI

# -------------------------------------------------
# Load env (must be first)
# -------------------------------------------------
load_dotenv()

assert os.getenv("OPENAI_API_KEY"), "OPENAI_API_KEY not set"
assert os.getenv("SUPABASE_URL"), "SUPABASE_URL not set"
assert os.getenv("SUPABASE_SERVICE_KEY"), "SUPABASE_SERVICE_KEY not set"

# -------------------------------------------------
# Clients
# -------------------------------------------------
openai = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

supabase = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_KEY"],
)

# -------------------------------------------------
# Mock Evidence Data (Realistic)
# -------------------------------------------------
MOCK_EVIDENCE = [
    {
        "policy_id": "PROCUREMENT-001",
        "doc_id": "PROC-2024-STD",
        "title": "Procurement Policy 2024",
        "uri": "s3://policies/procurement_2024.pdf",
        "page_start": 12,
        "page_end": 13,
        "clause_id": "CL-4.2",
        "section_path": "4.Approval / 4.2 High Value Procurement",
        "content": "Any procurement with total value exceeding 200,000 THB must be escalated for COO approval.",
    },
    {
        "policy_id": "PROCUREMENT-001",
        "doc_id": "PROC-2024-STD",
        "title": "Procurement Policy 2024",
        "uri": "s3://policies/procurement_2024.pdf",
        "page_start": 9,
        "page_end": 9,
        "clause_id": "CL-3.1",
        "section_path": "3.Risk / 3.1 SLA Risk",
        "content": "Procurement requests approaching SLA deadline within 24 hours must be prioritized.",
    },
]

# -------------------------------------------------
# Insert
# -------------------------------------------------
def main():
    print("🔹 Inserting mock evidence with real embeddings...")

    for ev in MOCK_EVIDENCE:
        emb = openai.embeddings.create(
            model="text-embedding-3-small",
            input=ev["content"],
        ).data[0].embedding

        row = {
            **ev,
            "embedding": emb,
        }

        supabase.table("evidence_vectors").insert(row).execute()
        print(f"✔ Inserted {ev['clause_id']}")

    print("✅ Mock evidence ingestion completed")


if __name__ == "__main__":
    main()
