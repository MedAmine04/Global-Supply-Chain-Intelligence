from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.copilot.agent import MissingApiKeyError, ask_copilot
from app.core.database import get_db
from app.schemas.copilot import CopilotAnswer, CopilotQuestion

router = APIRouter(prefix="/api", tags=["copilot"])


@router.post("/copilot/ask", response_model=CopilotAnswer)
def copilot_ask(payload: CopilotQuestion, db: Session = Depends(get_db)) -> CopilotAnswer:
    """Pose une question au Copilot IA (FR Phase 6). Requiert
    ANTHROPIC_API_KEY côté serveur — voir ADR-012 si absent."""
    try:
        response = ask_copilot(db, payload.question)
    except MissingApiKeyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return CopilotAnswer(answer=response.answer, tool_calls=response.tool_calls)
