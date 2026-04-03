import asyncio
import json
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from backend.app.db import get_db_session
from backend.app.db_models import Job, Task

router = APIRouter()


async def _sse_event_stream(request: Request, job_id: str) -> AsyncGenerator[str, None]:
    """
    SSE stream that emits job status from the database.
    """
    last_status: Optional[str] = None
    last_task_status: Optional[str] = None
    last_heartbeat = 0.0
    while True:
        try:
            session = get_db_session(request.app.state.db_session_factory)
            try:
                job = (
                    session.execute(select(Job).where(Job.id == job_id))
                    .scalar_one_or_none()
                )
                task = (
                    session.execute(select(Task).where(Task.id == job_id))
                    .scalar_one_or_none()
                )
            finally:
                session.close()
            status = job.status if job else "not_found"
            task_status = task.status if task else None
            if status != last_status or task_status != last_task_status:
                payload = {
                    "job_id": job_id,
                    "status": status,
                    "task_status": task_status,
                    "step": job.step if job else None,
                }
                data = json.dumps(payload)
                yield f"event: status\ndata: {data}\n\n"
                last_status = status
                last_task_status = task_status
            now = asyncio.get_event_loop().time()
            if now - last_heartbeat >= 5:
                last_heartbeat = now
                yield "event: heartbeat\ndata: {}\n\n"
            if status in ("completed", "failed"):
                result_payload = {
                    "job_id": job_id,
                    "status": status,
                    "result": job.result if job else None,
                    "error": job.error if job else None,
                }
                data = json.dumps(result_payload)
                yield f"event: result\ndata: {data}\n\n"
                break
        except Exception as exc:
            payload = {"job_id": job_id, "error": str(exc)}
            data = json.dumps(payload)
            yield f"event: error\ndata: {data}\n\n"
        await asyncio.sleep(1)


@router.get("/api/v1/jobs/{job_id}/status/stream")
async def stream_job_status(request: Request, job_id: str) -> StreamingResponse:
    return StreamingResponse(
        _sse_event_stream(request, job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
