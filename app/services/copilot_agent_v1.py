import json
import os
import asyncio
from typing import AsyncGenerator, List, Dict
from dotenv import load_dotenv
from openai import OpenAI

# ✅ Use the new Async/API-based Repository
from app.repositories.copilot_repo import CopilotRepositoryAtgent

load_dotenv()

class CopilotAgent:
    def __init__(self):
        # 1. Init Repository
        self.repo = CopilotRepositoryAtgent()
        
        # 2. Init OpenAI Client
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model_name = "gpt-4o" 
        self.embedding_model = "text-embedding-3-small"

        # 3. Load Mock Contracts (Phase 1)
        self.mock_contracts = self._load_mock_contracts()
        if self.mock_contracts:
            print("🔹 Document initialized.")
            print(f"   - Contract: {self.mock_contracts}")

    def _load_mock_contracts(self) -> dict:
        """Loads mock contract data from a local JSON file."""
        try:
            # Ensure the directory exists or adjust path as needed
            # ถอยกลับไปที่ root project แล้วหา backend/data/mock_contracts.json
            file_path = os.path.join("app" , "data", "mock_contracts.json")
            
            if not os.path.exists(file_path):
                # Fallback path if running from deep directory
                file_path = os.path.join("backend","app", "data", "mock_contracts.json")
                
            
            if not os.path.exists(file_path):
                print(f"⚠️ Contract DB not found at: {file_path}")
                return {"contracts": {}}
            
            
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Failed to load mock contracts: {e}")
            return {"contracts": {}}

    async def run_workflow(self, user_query: str, case_id: str) -> AsyncGenerator[str, None]:
        """
        Real Workflow:
        1. Load Case Context (API -> SQL)
        2. Contract & Price Check (Logic Rule) -> Send Evidence
        3. RAG Search (Vector DB) -> Send Evidence
        4. LLM Generation (Stream)
        """
        
        # --- STEP 1: Context Gathering (Case Data) ---
        yield self._format_event("trace", {
            "step_id": 1, "title": "Analyzing Context", 
            "status": "active", "desc": f"Loading case data for {case_id}..."
        })
        
        # ✅ Async data fetching
        case_data = await self.repo.get_case(case_id)
        audit_logs = await self.repo.get_audit_logs(case_id)
        
        
        
        if not case_data:
            yield self._format_event("trace", {
                "step_id": 1, "title": "Context Error", 
                "status": "failed", "desc": "Case ID not found in database."
            })
            yield self._format_event("message_chunk", {"text": "ขออภัยครับ ไม่พบข้อมูล Case ID นี้ในระบบ"})
            return

        # Extract useful info for logic
        raw = case_data.get('raw', {})
        payload = raw.get('payload', {}) if isinstance(raw, dict) else {}
        if not payload and isinstance(case_data, dict) and 'payload' in case_data: 
             payload = case_data['payload']
        if not isinstance(payload, dict): payload = {}

        vendor_name = case_data.get('vendor_id') or payload.get('vendor_name') or payload.get('vendor') or "story 1" # Fallback
        line_items = payload.get('line_items', [])

        # --- STEP 2: Contract & Price Analysis (Logic Rule) ---
        yield self._format_event("trace", {
            "step_id": 2, "title": "Contract Check", 
            "status": "active", "desc": "Verifying prices against master agreement..."
        })

        # Run logic (Improved matching logic)
        contract_analysis = self._analyze_price_variance(line_items, vendor_name)
        
        # Send contract evidences to UI immediately
        if contract_analysis["evidences"]:
            for ev in contract_analysis["evidences"]:
                yield self._format_event("evidence_reveal", ev)
        
        yield self._format_event("trace", {
            "step_id": 2, "title": "Contract Check", 
            "status": "completed", "desc": "Price verification completed."
        })

        # ✅ Build Smart Context (Now includes Contract Analysis & Engine Results)
        case_context_str = self._build_smart_context(case_data, audit_logs, contract_analysis["report_text"])
        
        yield self._format_event("trace", {
            "step_id": 1, "title": "Analyzing Context", 
            "status": "completed", "desc": "Full context loaded."
        })

        # --- STEP 3: RAG Knowledge Search (Vector DB) ---
        yield self._format_event("trace", {
            "step_id": 3, "title": "Policy Search", 
            "status": "active", "desc": "Scanning policy documents (Vector DB)..."
        })

        try:
            embedding_resp = self.client.embeddings.create(
                input=user_query,
                model=self.embedding_model
            )
            query_embedding = embedding_resp.data[0].embedding

            matches = self.repo.search_evidence(query_embedding, match_count=3)
        except Exception as e:
            print(f"Vector Search Error: {e}")
            matches = []
        
        rag_context_str = ""
        found_evidence = False

        if matches:
            found_evidence = True
            rag_context_str = "=== RELEVANT POLICIES (REFERENCE) ===\n"
            
            for idx, doc in enumerate(matches):
                score = doc.get('similarity', 0) * 100
                if score < 60: continue 

                yield self._format_event("evidence_reveal", {
                    "file_id": doc.get('doc_id', f"doc_{idx}"),
                    "file_name": doc.get('title', 'Unknown Policy'),
                    "highlight_text": doc.get('content', '')[:300] + "...", 
                    "score": int(score)
                })

                rag_context_str += f"[Ref ID: {doc.get('clause_id', 'N/A')}] {doc.get('content')}\nSource: {doc.get('title')}\n\n"
        
        else:
            rag_context_str = "No specific policy documents found related to this query."

        yield self._format_event("trace", {
            "step_id": 3, "title": "Policy Search", 
            "status": "completed", 
            "desc": f"Found {len(matches)} relevant references." if found_evidence else "No references found."
        })

        # --- STEP 4: Reasoning & Response (LLM) ---
        yield self._format_event("trace", {
            "step_id": 4, "title": "Final Reasoning", 
            "status": "active", "desc": "Synthesizing answer with GPT-4o..."
        })

        # 4.1 Construct System Prompt
        system_prompt = f"""
        You are an expert Decision Control Copilot (AI Assistant).
        Analyze the provided CASE DATA, CONTRACT CHECK, and POLICY EVIDENCE to answer the user's question.

        GOAL: Provide accurate, helpful answers based on the 'CASE SNAPSHOT', 'CONTRACT CHECK', and 'RISK ANALYSIS'.

        RULES:
        - Answer in Thai language (Natural & Professional).
        - If the user asks about price validity, refer to the [CONTRACT CHECK] section.
        - If the user asks for specific details (PO Number, Vendor), look at [CASE SNAPSHOT].
        - Use [RISK ANALYSIS] and [CONTRACT STATUS FROM ENGINE] to explain context.
        - Be concise.

        {case_context_str}

        {rag_context_str}
        """

        # 4.2 Call OpenAI Stream
        try:
            stream = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_query}
                ],
                temperature=0.3,
                stream=True
            )

            # 4.3 Streaming Response
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    text_chunk = chunk.choices[0].delta.content
                    yield self._format_event("message_chunk", {"text": text_chunk})

        except Exception as e:
            yield self._format_event("message_chunk", {"text": f"\n\n[System Error] LLM Processing failed: {str(e)}"})

        yield self._format_event("trace", {
            "step_id": 4, "title": "Final Reasoning", 
            "status": "completed", "desc": "Response generated."
        })

    # ------------------------------------------------------------------
    # Helper Methods
    # ------------------------------------------------------------------
    def _format_event(self, event_type: str, data: dict) -> str:
        """Format data as Server-Sent Events (JSON line)"""
        return json.dumps({"type": event_type, "data": data}) + "\n"

    def _analyze_price_variance(self, line_items: list, vendor_name: str) -> dict:
        """
        Analyzes price variance against mock contracts.
        Returns report text and list of evidences.
        """
        contracts_db = self.mock_contracts.get("contracts", {})
        
        # 1. Improved Vendor Matching Logic (Case Insensitive)
        contract = contracts_db.get(vendor_name)
        if not contract:
            contract = contracts_db.get(vendor_name.lower())
        
        if not contract:
            # Loop search for partial match
            for k, v in contracts_db.items():
                if k.lower() == vendor_name.lower():
                    contract = v
                    break
        
        # Optional: Demo fallback if you want to force "story 1"
        # if not contract and "story 1" in contracts_db: contract = contracts_db["story 1"]

        if not contract:
            return {
                "report_text": f"- No active contract found for vendor: {vendor_name}",
                "evidences": []
            }

        report_lines = []
        evidences = []
        
        report_lines.append(f"{'SKU':<12} | {'PO Price':<10} | {'Contract':<10} | {'Diff %':<8} | {'Status'}")
        report_lines.append("-" * 65)

        for item in line_items:
            sku = item.get('sku', '')
            try: po_price = float(item.get('unit_price', 0))
            except: po_price = 0.0
            
            contract_item = contract["items"].get(sku)

            if contract_item:
                agreed_price = contract_item["agreed_price"]
                diff = po_price - agreed_price
                diff_percent = (diff / agreed_price) * 100 if agreed_price > 0 else 0
                
                status = "✅ OK"
                if diff_percent > 5.0: status = f"❌ VIOLATION"
                elif diff_percent > 0: status = f"⚠️ HIGH"

                report_lines.append(f"{sku:<12} | {po_price:,.0f}      | {agreed_price:,.0f}      | {diff_percent:+.1f}%    | {status}")

                evidences.append({
                    "file_id": contract["doc_id"],
                    "file_name": f"{contract['doc_title']} (Page {contract_item['evidence_meta']['page']})",
                    "highlight_text": contract_item['evidence_meta']['content_snippet'],
                    "score": 0.95,
                    "page": contract_item['evidence_meta']['page'],
                    "box": contract_item['evidence_meta']['highlight_box'] 
                })
            else:
                report_lines.append(f"{sku:<12} | {po_price:,.0f}      | {'N/A':<10} | {'-':<8} | ❓ No Ref")

        return {
            "report_text": "\n".join(report_lines),
            "evidences": evidences
        }

    def _build_smart_context(self, data: dict, audits: List[dict], contract_report: str = "") -> str:
        """
        Parses JSON Structure (from API) into readable text.
        Includes Contract Report and Engine Results.
        """
        # 1. Handle Nested Structure
        raw = data.get('raw', {})
        if not isinstance(raw, dict): raw = {}
        
        payload = raw.get('payload', {}) if isinstance(raw, dict) else {}
        if not payload and isinstance(data, dict) and 'payload' in data: 
             payload = data['payload']
        if not isinstance(payload, dict): payload = {}

        summary = data.get('decision_summary', {}) if isinstance(data.get('decision_summary'), dict) else {}
        story = data.get('story', {}) if isinstance(data.get('story'), dict) else {}

        # 2. Extract Engine Results (Consistency Check)
        engine_contract_result = ""
        last_results = payload.get("last_rule_results", [])
        contract_rules = [r for r in last_results if r.get("rule_id") in ["CONTRACT_EXPIRED", "CONTRACT_PRICE_VARIANCE", "NO_CONTRACT_REFERENCE"]]
        
        if contract_rules:
            engine_contract_result = "\n[CONTRACT STATUS FROM ENGINE]\n"
            for r in contract_rules:
                status = "❌ FAIL" if r.get("hit") else "✅ PASS"
                desc = r.get("description")
                detail = ""
                inputs = r.get("inputs", {})
                if isinstance(inputs, dict):
                    detail = " | ".join([str(v) for v in inputs.values()])
                engine_contract_result += f"- {status} {r.get('rule_id')}: {desc} ({detail})\n"

        # 3. Dynamic Snapshot
        snapshot_lines = []
        exclude_keys = ['line_items', 'last_rule_results', 'risk_drivers', 'description', 'payload', 'raw', 'story', 'decision_summary']
        
        if data.get('id') or data.get('case_id'): 
            snapshot_lines.append(f"Case ID: {data.get('id') or data.get('case_id')}")
        if data.get('status'): 
            snapshot_lines.append(f"Status: {data.get('status')}")
        
        evaluated_at = data.get('evaluated_at') or payload.get('evaluated_at')
        if evaluated_at:
             snapshot_lines.append(f"Evaluated At: {str(evaluated_at).replace('T', ' ')[:19]}")

        for key, val in payload.items():
            if key not in exclude_keys and not isinstance(val, (list, dict)):
                readable_key = key.replace('_', ' ').title()
                snapshot_lines.append(f"{readable_key}: {val}")
        
        snapshot_txt = "\n".join(snapshot_lines)

        # 4. Extract Risk Story
        risk_drivers_txt = ""
        risk_drivers = story.get('risk_drivers', [])
        if isinstance(risk_drivers, list):
            for driver in risk_drivers:
                if isinstance(driver, dict):
                    risk_drivers_txt += f"- [RISK] {driver.get('label')}: {driver.get('detail')}\n"
            
        suggested_action = story.get('suggested_action', {}) if isinstance(story.get('suggested_action'), dict) else {}
        action_txt = f"Action: {suggested_action.get('title', '-')} ({suggested_action.get('description', '')})"

        # 5. Extract Line Items
        items_txt = ""
        line_items = payload.get('line_items', [])
        if isinstance(line_items, list) and line_items:
            for item in line_items:
                if isinstance(item, dict):
                    desc = item.get('item_desc') or item.get('description') or 'Item'
                    qty = item.get('quantity', 0)
                    try:
                        price = item.get('total_price') or (item.get('unit_price', 0) * int(qty or 0))
                    except: price = 0
                    items_txt += f"- {desc} (Qty: {qty}, Total: {price:,.2f})\n"
        else:
            items_txt = "- No items detail found."

        # 6. Extract Audit Logs
        audit_txt = ""
        if isinstance(audits, list):
            sorted_audits = sorted(audits, key=lambda x: x.get('created_at', ''), reverse=True)
            for a in sorted_audits[:8]:
                if not isinstance(a, dict): continue
                action = a.get('action') or a.get('event_type') or 'Unknown Event'
                actor_obj = a.get('actor')
                if isinstance(actor_obj, dict): actor = actor_obj.get('name', 'System')
                elif isinstance(actor_obj, str): actor = actor_obj
                else: actor = 'System'
                timestamp = str(a.get('created_at', ''))[:16].replace('T', ' ')
                audit_txt += f"- {timestamp}: {action} by {actor}\n"

        return f"""
        === CASE CONTEXT ===
        
        [CASE SNAPSHOT]
        {snapshot_txt}
        
        [RISK ANALYSIS]
        {risk_drivers_txt if risk_drivers_txt else "- No critical risk drivers identified."}
        
        {engine_contract_result}

        [CONTRACT CHECK DETAIL]
        {contract_report if contract_report else "- No contract data available."}

        [SUGGESTED ACTION]
        {action_txt}

        [LINE ITEMS]
        {items_txt}

        [LATEST AUDIT LOGS]
        {audit_txt if audit_txt else "- No audit history available."}
        ====================
        """