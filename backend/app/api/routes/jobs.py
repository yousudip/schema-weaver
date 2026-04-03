from pathlib import Path
from typing import Dict, List
from uuid import uuid4

from fastapi import APIRouter, Request, UploadFile
from sqlalchemy import desc, select

from backend.app.db import get_db_session
from backend.app.db_models import Job, Task

router = APIRouter()


@router.post("/api/v1/upload")
async def upload_file(request: Request, file: UploadFile) -> Dict[str, str]:
    settings = request.app.state.settings
    storage_dir: Path = settings.local_storage_dir
    storage_dir.mkdir(parents=True, exist_ok=True)

    job_id = uuid4().hex
    sanitized_name = file.filename or "upload.bin"
    target_path = storage_dir / f"{job_id}-{sanitized_name}"

    with target_path.open("wb") as out_file:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            out_file.write(chunk)

    session = get_db_session(request.app.state.db_session_factory)
    try:
        session.add(
            Job(
                id=job_id,
                filename=sanitized_name,
                storage_path=str(target_path),
                status="queued",
                task_status="pending",
                result=None,
                error=None,
            )
        )
        session.add(
            Task(
                id=job_id,
                job_id=job_id,
                task_type="process_file",
                status="pending",
                result=None,
                error=None,
            )
        )
        session.commit()
    finally:
        session.close()

    queue = request.app.state.worker_queue
    queue.submit(
        "process_file",
        {"job_id": job_id, "storage_path": str(target_path), "filename": sanitized_name},
        task_id=job_id,
    )

    return {"job_id": job_id}


@router.get("/api/v1/jobs")
async def list_jobs(request: Request, limit: int = 20) -> Dict[str, List[Dict[str, str]]]:
    session = get_db_session(request.app.state.db_session_factory)
    try:
        rows = (
            session.execute(select(Job).order_by(desc(Job.created_at)).limit(limit))
            .scalars()
            .all()
        )
    finally:
        session.close()
    jobs = [
        {
            "job_id": row.id,
            "filename": row.filename,
            "status": row.status,
            "task_status": row.task_status,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]
    return {"jobs": jobs}


@router.delete("/api/v1/jobs/{job_id}")
async def delete_job(request: Request, job_id: str) -> Dict[str, str]:
    session = get_db_session(request.app.state.db_session_factory)
    try:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()
        task = session.execute(select(Task).where(Task.id == job_id)).scalar_one_or_none()
        if task:
            session.delete(task)
        if job:
            session.delete(job)
        session.commit()
    finally:
        session.close()

    if job and job.storage_path:
        path = Path(job.storage_path)
        if path.exists():
            path.unlink(missing_ok=True)

    return {"status": "deleted", "job_id": job_id}
