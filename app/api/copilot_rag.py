from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.copilot_orchestrator import CopilotOrchestrator

router = APIRouter(tags=["copilot"])

class CopilotStreamRequest(BaseModel):
    question: str

@router.post("/stream")
async def stream_copilot(req: CopilotStreamRequest):
    orchestrator = CopilotOrchestrator()

    return StreamingResponse(
        orchestrator.run(req.question),
        media_type="application/x-ndjson",
    )
