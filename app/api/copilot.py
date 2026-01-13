from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.services.copilot_agent import CopilotAgent

router = APIRouter(tags=["copilot"])

class ChatRequest(BaseModel):
    query: str
    case_id: str

@router.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    agent = CopilotAgent()
    
    return StreamingResponse(
        agent.run_workflow(req.query, req.case_id),
        media_type="application/x-ndjson" # Newline Delimited JSON
    )