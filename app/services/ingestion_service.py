import io
import re
import pandas as pd
from typing import Optional, Dict, Any, List
from uuid import UUID  # ✅ 1. เพิ่ม Import UUID

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

# ✅ 2. เพิ่ม Import Client สำหรับสร้าง Signed URL
from supabase import create_client, Client

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
        
        # ✅ 3. Initialize Supabase Client (เพิ่มส่วนนี้)
        self.supabase: Client = create_client(settings.supabase_url, settings.supabase_key)

    def _extract_markdown_table(self, text: str) -> Optional[str]:
        if not text: return None
        lines = text.split('\n')
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
        
    def get_knowledge_base(self) -> List[Dict[str, Any]]:
        """ดึงรายการเอกสารทั้งหมด"""
        return self.repo.get_all_documents()

    # ✅ 4. เพิ่มฟังก์ชัน get_document_url (สำหรับเปิดไฟล์)
    def get_document_url(self, doc_id: UUID) -> Dict[str, str]:
        """
        สร้าง Signed URL สำหรับเปิดไฟล์จาก Supabase Storage
        """
        # 1. ดึง Path จาก DB (ต้องมั่นใจว่า Repo มีฟังก์ชัน get_document_path แล้ว)
        file_path = self.repo.get_document_path(doc_id)
        if not file_path:
            raise Exception(f"File path not found for document ID: {doc_id}")

        try:
            # 🚨🚨🚨 ตรวจสอบชื่อ Bucket ตรงนี้ครับ 🚨🚨🚨
            # ถ้าใน Supabase คุณชื่อ 'uploads' ให้แก้เป็น "uploads"
            BUCKET_NAME = "raw_documents" 

            print(f"🔍 Generating URL for: Bucket='{BUCKET_NAME}', Path='{file_path}'")
            
            # 2. สร้าง Signed URL (หมดอายุใน 60 วินาที)
            response = self.supabase.storage.from_(BUCKET_NAME).create_signed_url(file_path, 60)
            
            # Handle Response Format (รองรับทั้งแบบ dict และ object)
            if isinstance(response, dict) and "signedURL" in response:
                return {"url": response["signedURL"]}
            elif hasattr(response, 'signedURL'): 
                return {"url": response.signedURL}
            elif isinstance(response, str):
                 return {"url": response}
            else:
                 return {"url": str(response)}

        except Exception as e:
            print(f"❌ Storage Error: {e}")
            raise Exception(f"Could not generate URL: {str(e)}")

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
        -> 5. Metadata -> 6. Vector (Contextual) -> 7. Table (Smart Header & Unit Price) -> 8. Finish
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

            # 6. Vector DB (Contextual Embedding)
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

                    context_header = f"Filename: {filename}\n"
                    if metadata.get('vendor_name'):
                        context_header += f"Vendor: {metadata['vendor_name']}\n"
                    if metadata.get('contract_id'):
                        context_header += f"Contract ID: {metadata['contract_id']}\n"
                    
                    text_to_embed = f"{context_header}\n{chunk_text}"
                    vector = self.embeddings_model.embed_query(text_to_embed)
                    self.repo.insert_chunk(doc_id, chunk_text, vector, combined_metadata)

            # 7. Relational DB (Universal Items)
            try:
                print("📊 Attempting to extract table...")
                clean_table_text = self._extract_markdown_table(full_markdown_text)
                
                if clean_table_text:
                    df = pd.read_csv(io.StringIO(clean_table_text), sep="|", skipinitialspace=True, header=0, dtype=str)
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
                            for k, v in list(clean_item.items()):
                                val_upper = str(v).upper()
                                if any(curr in val_upper for curr in CURRENCY_KEYWORDS):
                                    clean_val = self._clean_price(v)
                                    if clean_val > 0:
                                        clean_item[f"{k}_numeric"] = clean_val
                                        header_upper = str(k).upper()
                                        is_likely_unit_price = (
                                            ("PRICE" in header_upper or "COST" in header_upper or "RATE" in header_upper) 
                                            and ("TOTAL" not in header_upper)
                                        )
                                        if is_likely_unit_price or "unit_price" not in clean_item:
                                            clean_item["unit_price"] = clean_val

                            item_full_text = " ".join([f"{k}: {v}" for k, v in clean_item.items()])
                            batch_items_data.append({
                                "document_id": doc_id, "doc_type": domain, "item_index": idx, "item_data": clean_item
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