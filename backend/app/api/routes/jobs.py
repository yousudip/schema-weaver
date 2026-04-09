import math
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import desc, select

from backend.app.db import get_db_session
from backend.app.db_models import Job, JobFile, Task
from backend.app.parsers.detect import detect_file_type
from backend.app.parsers.spreadsheet import parse_spreadsheet
from backend.app.core.config import get_settings

router = APIRouter()


def _sanitize_for_json(value: Any) -> Any:
    """Recursively replace NaN/Inf floats with None so PostgreSQL JSON accepts it."""
    if isinstance(value, float):
        return None if not math.isfinite(value) else value
    if isinstance(value, dict):
        return {k: _sanitize_for_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_for_json(v) for v in value]
    return value


# ─── Legacy single-file upload (preserved for backward compat) ─────────────────

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


# ─── Phase 5: Multi-file job creation ──────────────────────────────────────────

class NewJobRequest(BaseModel):
    purpose: str
    description: str | None = None


@router.post("/api/v1/jobs/new")
async def create_job(request: Request, body: NewJobRequest) -> Dict[str, str]:
    """Create a new multi-file job with a business purpose. Returns job_id."""
    job_id = uuid4().hex
    session = get_db_session(request.app.state.db_session_factory)
    try:
        session.add(
            Job(
                id=job_id,
                filename="",           # no single file for multi-file jobs
                storage_path="",
                status="ready",
                task_status="pending",
                purpose=body.purpose,
                description=body.description,
                result=None,
                error=None,
            )
        )
        session.commit()
    finally:
        session.close()
    return {"job_id": job_id, "purpose": body.purpose}


@router.post("/api/v1/jobs/{job_id}/files")
async def add_file_to_job(request: Request, job_id: str, file: UploadFile) -> Dict:
    """Upload a file into an existing multi-file job. Parses it immediately."""
    settings = request.app.state.settings
    storage_dir: Path = settings.local_storage_dir / "jobs" / job_id
    storage_dir.mkdir(parents=True, exist_ok=True)

    session = get_db_session(request.app.state.db_session_factory)
    try:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")
    finally:
        session.close()

    file_id = uuid4().hex
    sanitized_name = file.filename or "upload.bin"
    target_path = storage_dir / f"{file_id}-{sanitized_name}"

    with target_path.open("wb") as out_file:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            out_file.write(chunk)

    # Detect file type and parse preview synchronously (fast for CSV/Excel)
    try:
        ft = detect_file_type(target_path)
        file_type_kind = ft.kind
    except Exception:
        file_type_kind = "unknown"

    preview_data = None
    parse_error = None
    if file_type_kind in ("csv", "excel"):
        try:
            preview = parse_spreadsheet(target_path)
            preview_data = _sanitize_for_json(preview.__dict__) if preview else None
        except Exception as e:
            parse_error = str(e)

    file_status = "ready" if preview_data else ("failed" if parse_error else "pending")

    session = get_db_session(request.app.state.db_session_factory)
    try:
        jf = JobFile(
            id=file_id,
            job_id=job_id,
            filename=sanitized_name,
            storage_path=str(target_path),
            file_type=file_type_kind,
            status=file_status,
            result={"preview": preview_data, "file_type": file_type_kind} if preview_data else None,
            error=parse_error,
        )
        session.add(jf)
        session.commit()
    finally:
        session.close()

    response: Dict = {
        "file_id": file_id,
        "job_id": job_id,
        "filename": sanitized_name,
        "file_type": file_type_kind,
        "status": file_status,
        "error": parse_error,
    }
    if file_type_kind == "pdf":
        response["has_preview"] = False
        response["needs_extraction"] = True
    return response


@router.get("/api/v1/jobs/{job_id}/files")
async def list_job_files(request: Request, job_id: str) -> Dict:
    """List all files in a job with their per-file status and quality info."""
    session = get_db_session(request.app.state.db_session_factory)
    try:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")
        files = (
            session.execute(
                select(JobFile)
                .where(JobFile.job_id == job_id)
                .order_by(JobFile.created_at)
            )
            .scalars()
            .all()
        )
        file_list = [
            {
                "file_id": f.id,
                "filename": f.filename,
                "file_type": f.file_type,
                "status": f.status,
                "error": f.error,
                "has_preview": f.result is not None,
                "has_schema": f.analysis is not None and "schema_inference" in (f.analysis or {}),
                "has_code": f.analysis is not None and "generated_code" in (f.analysis or {}),
                "execution_ok": bool((f.analysis or {}).get("execution_ok")),
                "quality_report": (f.analysis or {}).get("quality_report"),
                "validation_attempts": (f.analysis or {}).get("validation_attempts", []),
                "created_at": f.created_at.isoformat() if f.created_at else None,
                "needs_extraction": f.file_type == "pdf" and not f.result,
            }
            for f in files
        ]
    finally:
        session.close()

    return {
        "job_id": job_id,
        "purpose": job.purpose,
        "description": job.description,
        "files": file_list,
    }


@router.delete("/api/v1/jobs/{job_id}/files/{file_id}")
async def remove_job_file(request: Request, job_id: str, file_id: str) -> Dict[str, str]:
    """Remove a file from a job (deletes file from disk too)."""
    session = get_db_session(request.app.state.db_session_factory)
    storage_path = None
    try:
        jf = (
            session.execute(
                select(JobFile).where(JobFile.id == file_id, JobFile.job_id == job_id)
            )
            .scalar_one_or_none()
        )
        if not jf:
            raise HTTPException(status_code=404, detail="File not found in this job.")
        storage_path = jf.storage_path
        session.delete(jf)
        session.commit()
    finally:
        session.close()

    if storage_path:
        p = Path(storage_path)
        if p.exists():
            p.unlink(missing_ok=True)

    return {"status": "deleted", "file_id": file_id}


# ─── Job list (updated to include purpose + file_count) ────────────────────────

@router.get("/api/v1/jobs")
async def list_jobs(request: Request, limit: int = 20) -> Dict[str, List[Dict]]:
    session = get_db_session(request.app.state.db_session_factory)
    try:
        rows = (
            session.execute(select(Job).order_by(desc(Job.created_at)).limit(limit))
            .scalars()
            .all()
        )
        # Count files per job in one pass
        job_ids = [r.id for r in rows]
        file_counts: Dict[str, int] = {}
        if job_ids:
            file_rows = (
                session.execute(select(JobFile).where(JobFile.job_id.in_(job_ids)))
                .scalars()
                .all()
            )
            for f in file_rows:
                file_counts[f.job_id] = file_counts.get(f.job_id, 0) + 1
    finally:
        session.close()

    jobs = [
        {
            "job_id": row.id,
            "filename": row.filename,
            "purpose": row.purpose,
            "status": row.status,
            "task_status": row.task_status,
            "file_count": file_counts.get(row.id, 0),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]
    return {"jobs": jobs}


# ─── Job deletion (handles both legacy + multi-file jobs) ──────────────────────

@router.delete("/api/v1/jobs/{job_id}")
async def delete_job(request: Request, job_id: str) -> Dict[str, str]:
    session = get_db_session(request.app.state.db_session_factory)
    storage_paths = []
    try:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()
        task = session.execute(select(Task).where(Task.id == job_id)).scalar_one_or_none()
        # Collect all associated file paths
        if job and job.storage_path:
            storage_paths.append(job.storage_path)
        job_files = (
            session.execute(select(JobFile).where(JobFile.job_id == job_id))
            .scalars()
            .all()
        )
        for jf in job_files:
            if jf.storage_path:
                storage_paths.append(jf.storage_path)
            session.delete(jf)
        if task:
            session.delete(task)
        if job:
            session.delete(job)
        session.commit()
    finally:
        session.close()

    for sp in storage_paths:
        p = Path(sp)
        if p.exists():
            p.unlink(missing_ok=True)

    return {"status": "deleted", "job_id": job_id}
