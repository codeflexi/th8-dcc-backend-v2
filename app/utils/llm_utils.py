# app/utils/llm_utils.py
import tiktoken

def count_tokens(text: str, model: str = "gpt-4o") -> int:
    try:
        encoding = tiktoken.encoding_for_model(model)
        return len(encoding.encode(text))
    except KeyError:
        return len(text) // 4 # Fallback

def estimate_cost_usd(tokens: int, model: str = "gpt-4o") -> float:
    # ราคา Input Token (สมมติ $5.00 / 1M tokens)
    price_per_million = 5.00 if model == "gpt-4o" else 0.50
    return (tokens / 1_000_000) * price_per_million


# # app/services/ai_service.py
# from app.utils.llm_utils import count_tokens, estimate_cost_usd

# async def analyze_contract_with_ai(contract_text: str):
    
#     # 1. เช็ค Token ก่อนยิง
#     token_count = count_tokens(contract_text)
#     estimated_price = estimate_cost_usd(token_count)
    
#     print(f"💰 Cost Estimation: {token_count} tokens (~${estimated_price:.4f})")
    
#     # 2. Safety Check (ถ้าแพงไป ไม่ยิง)
#     if token_count > 120000:
#         raise ValueError("Contract is too long for AI context window!")

#     # 3. Call OpenAI...
#     # response = await openai.chat.completions.create(...)