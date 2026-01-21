import io
import re
import pandas as pd
from typing import Optional, Dict, Any, List
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Config & Schemas
from app.core.config import settings
from app.schemas.dynamic import get_dynamic_model, DOMAIN_CONFIG 

# Parser
from app.services.parser import parse_pdf_with_metadata 

# Repositories
from app.repositories.base_ingestion import IngestionRepository
from app.repositories.supabase_repo import SupabaseIngestionRepository

class IngestionService:
    def __init__(self, repo: IngestionRepository = None):
        self.repo = repo or SupabaseIngestionRepository()
        
        self.llm = ChatOpenAI(
            model="gpt-4o", 
            api_key=settings.openai_api_key, 
            temperature=0
        )
        self.embeddings_model = OpenAIEmbeddings(
            api_key=settings.openai_api_key
        )

    def _extract_markdown_table(self, text: str) -> Optional[str]:
        if not text: return None
        lines = text.split('\n')
        # กรองเอาเฉพาะบรรทัดที่เป็นตาราง และตัดบรรทัด separator (---) ออก
        table_lines = [line for line in lines if '|' in line and set(line.strip()) != {'|', '-', ' '}]
        
        if len(table_lines) < 2: 
            return None 
        return "\n".join(table_lines)

    def _clean_price(self, value: Any) -> float:
        try:
            if value is None: return 0.0
            val_str = str(value)
            if not val_str.strip(): return 0.0
            
            clean_str = re.sub(r'[^\d.-]', '', val_str)
            return float(clean_str) if clean_str else 0.0
        except Exception:
            return 0.0

    async def run_pipeline(
        self, 
        file_bytes: bytes, 
        filename: str, 
        file_path: str, 
        file_hash: str,
        storage_path: str = None
    ) -> Dict[str, Any]:
        """
        Main Pipeline:
        1. Check Duplicate -> 2. Create Record -> 3. Parse -> 4. Classify 
        -> 5. Metadata -> 6. Vector -> 7. Table (Smart Header & Unit Price) -> 8. Finish
        """
        
        final_storage_path = storage_path or file_path

        # 1. Check Duplicate
        existing = self.repo.check_duplicate(file_hash)
        if existing:
            return {
                "status": "exists", 
                "message": "File already processed", 
                "doc_id": existing['id'],
                "domain": existing.get('domain'),
                "data": existing.get('metadata')
            }

        # 2. Create Initial Record
        doc_id = self.repo.create_document(filename, file_hash, final_storage_path)

        try:
            # 3. Parse PDF
            print(f"📄 Parsing PDF with Metadata: {filename}...")
            parsed_docs = await parse_pdf_with_metadata(file_path)
            
            if not parsed_docs:
                raise ValueError("Parsed document is empty.")

            full_markdown_text = "\n\n".join([d.text for d in parsed_docs])
            
            # 4. Router
            domains_list = ", ".join(DOMAIN_CONFIG.keys())
            router_prompt = f"Classify this document based on the text below. Options: [{domains_list}]. Return ONLY the domain name (lowercase)."
            
            domain_result = self.llm.invoke(router_prompt + f"\n\nText Snippet:\n{full_markdown_text[:2000]}")
            domain = domain_result.content.strip().lower()
            
            if domain not in DOMAIN_CONFIG: 
                domain = "general"

            self.repo.update_document_domain(doc_id, domain)

            # 5. Metadata
            DynamicSchema = get_dynamic_model(domain)
            structured_llm = self.llm.with_structured_output(DynamicSchema)
            metadata = structured_llm.invoke(full_markdown_text[:4000]).dict()

            # 6. Vector DB
            print("🔪 Chunking text with metadata...")
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=1000,
                chunk_overlap=200
            )

            for p_doc in parsed_docs:
                page_chunks = text_splitter.split_text(p_doc.text)
                
                for chunk_text in page_chunks:
                    combined_metadata = metadata.copy()
                    combined_metadata.update(p_doc.metadata)

                    vector = self.embeddings_model.embed_query(chunk_text)
                    self.repo.insert_chunk(doc_id, chunk_text, vector, combined_metadata)

            # 7. Relational DB (Universal Items) - Table Extraction Logic
            try:
                print("📊 Attempting to extract table...")
                clean_table_text = self._extract_markdown_table(full_markdown_text)
                
                if clean_table_text:
                    # ใช้ header=0 เพื่อเอาบรรทัดแรกเป็นชื่อ Column
                    df = pd.read_csv(io.StringIO(clean_table_text), sep="|", skipinitialspace=True, header=0, dtype=str)
                    
                    # Clean Column Names
                    df.columns = [c.strip() if isinstance(c, str) else str(c) for c in df.columns]
                    df = df.loc[:, ~df.columns.str.contains('^Unnamed')]
                    df = df.dropna(axis=1, how='all')
                    
                    items = df.to_dict(orient="records")
                    batch_items_data = []
                    texts_to_embed = []

                    CURRENCY_KEYWORDS = ["THB", "USD", "BAHT", "BATH", "LAK", "MMK", "EUR", "JPY"]

                    for idx, item in enumerate(items):
                        clean_item = {k: str(v).strip() for k, v in item.items() if v is not None and str(v).strip() != ""}
                        
                        if clean_item:
                            # 🛡️ Safe Loop
                            for k, v in list(clean_item.items()):
                                val_upper = str(v).upper()
                                # -------------------------------------------------------
                                # ✅ Logic 1: ตรวจจับว่าเป็นสกุลเงินหรือไม่
                                # -------------------------------------------------------
                                if any(curr in val_upper for curr in CURRENCY_KEYWORDS):
                                    clean_val = self._clean_price(v)
                                    if clean_val > 0:
                                        # 1.1 เก็บค่า _numeric ตามชื่อ Header เดิม (เผื่อไว้ Trace)
                                        clean_item[f"{k}_numeric"] = clean_val
                                        
                                        # -------------------------------------------------------
                                        # ✅ Logic 2: สร้าง Standard Key "unit_price"
                                        # -------------------------------------------------------
                                        header_upper = str(k).upper()
                                        
                                        # Heuristic: ถ้า Header มีคำว่า Price/Cost/Rate และไม่ใช่ Total ให้ถือว่าเป็น Unit Price
                                        is_likely_unit_price = (
                                            ("PRICE" in header_upper or "COST" in header_upper or "RATE" in header_upper) 
                                            and ("TOTAL" not in header_upper)
                                        )
                                        
                                        # ถ้าเข้าเงื่อนไข หรือยังไม่มี unit_price มาก่อนเลย (ให้เอาอันแรกที่เจอ)
                                        if is_likely_unit_price or "unit_price" not in clean_item:
                                            clean_item["unit_price"] = clean_val

                            # Create text for embedding
                            item_full_text = " ".join([f"{k}: {v}" for k, v in clean_item.items()])
                            
                            batch_items_data.append({
                                "document_id": doc_id,
                                "doc_type": domain, 
                                "item_index": idx,
                                "item_data": clean_item
                            })
                            texts_to_embed.append(item_full_text)
                    
                    if batch_items_data:
                        print(f"🧠 Generating embeddings for {len(texts_to_embed)} items...")
                        item_vectors = self.embeddings_model.embed_documents(texts_to_embed)

                        for i, record in enumerate(batch_items_data):
                            record["item_embedding"] = item_vectors[i]

                        self.repo.insert_universal_items(batch_items_data)
                        print(f"✅ Table extracted & Embedded: {len(batch_items_data)} rows")
                else:
                    print("⚠️ No table structure found.")

            except Exception as e:
                print(f"❌ Table Extraction Warning: {str(e)}")

            # 8. Finalize
            self.repo.update_document_status(doc_id, "completed", metadata=metadata)
            return {
                "status": "success", 
                "doc_id": doc_id, 
                "domain": domain, 
                "data": metadata
            }

        except Exception as e:
            print(f"🔥 Critical Ingestion Error: {str(e)}")
            self.repo.update_document_status(doc_id, "failed", error_message=str(e))
            raise e