from fastapi import APIRouter, Request

from backend.app.db import check_db_connection

router = APIRouter()


@router.get("/health")
async def health_check(request: Request) -> dict:
    engine = request.app.state.db_engine
    check_db_connection(engine)
    llm_ready = request.app.state.llm_client is not None
    return {"status": "ok", "db": "ok", "llm": "ok" if llm_ready else "not_ready"}
