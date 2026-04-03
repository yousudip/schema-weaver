import csv
import io
import json
import os
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from sqlalchemy import delete, select

from backend.app.db import get_db_session
from backend.app.db_models import Job, SchemaVector, Task
from backend.app.tasks.handlers import demo_sleep_task
from backend.app.llm.inference import (
    SchemaInference,
    build_prompt,
    build_reflexion_prompt,
    coerce_inference_payload,
    parse_llm_json,
)
from backend.app.llm.embeddings import build_rich_representation, embed_texts
from backend.app.llm.codegen import (
    build_codegen_prompt,
    build_codegen_reflexion_prompt,
    parse_generated_code,
    wrap_for_sandbox,
)

router = APIRouter()


class TaskRequest(BaseModel):
    task_type: str = Field(default="demo_sleep")
    payload: Dict[str, Any] = Field(default_factory=dict)


class SchemaSelectRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    schema_payload: Dict[str, Any] | None = Field(default=None, alias="schema")


class SchemaMatchRequest(BaseModel):
    text: str
    job_id: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)


@router.post("/api/v1/jobs")
async def submit_job(request: Request, body: TaskRequest) -> Dict[str, str]:
    queue = request.app.state.worker_queue
    task_id = queue.submit(body.task_type, body.payload)
    session = get_db_session(request.app.state.db_session_factory)
    try:
        existing = (
            session.execute(select(Task).where(Task.id == task_id))
            .scalar_one_or_none()
        )
        if not existing:
            session.add(
                Task(
                    id=task_id,
                    job_id=body.payload.get("job_id"),
                    task_type=body.task_type,
                    status="pending",
                    result=None,
                    error=None,
                )
            )
            session.commit()
    finally:
        session.close()
    return {"job_id": task_id}


@router.get("/api/v1/jobs/{job_id}")
async def get_job(request: Request, job_id: str) -> Dict[str, Any]:
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
    if not job and not task:
        return {"job_id": job_id, "status": "not_found"}
    job_data = (
        {
            "job_id": job.id,
            "filename": job.filename,
            "storage_path": job.storage_path,
            "status": job.status,
            "task_status": job.task_status,
            "step": job.step,
            "result": job.result,
            "analysis": job.analysis,
            "error": job.error,
        }
        if job
        else None
    )
    task_data = (
        {
            "task_id": task.id,
            "job_id": task.job_id,
            "task_type": task.task_type,
            "status": task.status,
            "result": task.result,
            "error": task.error,
        }
        if task
        else None
    )
    return {"job": job_data, "task": task_data}


@router.post("/api/v1/jobs/{job_id}/infer")
async def infer_schema(request: Request, job_id: str) -> Dict[str, Any]:
    session = get_db_session(request.app.state.db_session_factory)
    try:
        job = (
            session.execute(select(Job).where(Job.id == job_id))
            .scalar_one_or_none()
        )
        if not job or not job.result:
            return {"status": "error", "message": "No job result available for inference."}
        preview = job.result.get("preview")
        if not preview:
            return {"status": "error", "message": "No preview available for inference."}

        client = request.app.state.llm_client
        prompt = build_prompt(preview)
        model = request.app.state.settings.azure_openai_deployment_gpt5_mini
        response = client.responses.create(
            model=model,
            input=prompt,
        )
        raw_text = response.output_text
        parsed = coerce_inference_payload(parse_llm_json(raw_text))
        try:
            validated = SchemaInference.model_validate(parsed).model_dump()
        except ValidationError as exc:
            retry_prompt = build_reflexion_prompt(preview, str(exc))
            retry_response = client.responses.create(
                model=model,
                input=retry_prompt,
            )
            retry_text = retry_response.output_text
            retry_parsed = coerce_inference_payload(parse_llm_json(retry_text))
            try:
                validated = SchemaInference.model_validate(retry_parsed).model_dump()
            except ValidationError as retry_exc:
                return {
                    "status": "error",
                    "message": "LLM output failed validation.",
                    "details": str(retry_exc),
                }

        job.analysis = {"schema_inference": validated}
        session.commit()
        return {"status": "ok", "analysis": job.analysis}
    finally:
        session.close()


@router.post("/api/v1/jobs/{job_id}/schema/select")
async def select_schema(
    request: Request, job_id: str, body: SchemaSelectRequest | None = None
) -> Dict[str, Any]:
    session = get_db_session(request.app.state.db_session_factory)
    try:
        job = (
            session.execute(select(Job).where(Job.id == job_id))
            .scalar_one_or_none()
        )
        if not job:
            return {"status": "error", "message": "Job not found."}
        analysis = job.analysis or {}
        schema = (
            body.schema_payload if body and body.schema_payload else analysis.get("schema_inference")
        )
        if not schema:
            return {"status": "error", "message": "No schema available to select."}
        analysis = dict(analysis)
        analysis["selected_schema"] = schema
        job.analysis = analysis
        session.commit()
        return {"status": "ok", "analysis": job.analysis}
    finally:
        session.close()


@router.post("/api/v1/jobs/{job_id}/schema/embeddings")
async def build_schema_embeddings(request: Request, job_id: str) -> Dict[str, Any]:
    settings = request.app.state.settings
    model = settings.azure_openai_deployment_embeddings
    if not model:
        return {"status": "error", "message": "Embedding model deployment is not set."}
    session = get_db_session(request.app.state.db_session_factory)
    try:
        job = (
            session.execute(select(Job).where(Job.id == job_id))
            .scalar_one_or_none()
        )
        if not job or not job.analysis:
            return {"status": "error", "message": "No analysis available for embeddings."}
        schema = job.analysis.get("selected_schema") or job.analysis.get("schema_inference")
        if not schema:
            return {"status": "error", "message": "No schema available for embeddings."}
        columns = schema.get("columns") if isinstance(schema, dict) else None
        if not isinstance(columns, list) or not columns:
            return {"status": "error", "message": "Schema columns are missing."}

        texts = [build_rich_representation(column) for column in columns]
        embeddings = embed_texts(request.app.state.llm_client, model, texts)
        if len(embeddings) != len(columns):
            return {"status": "error", "message": "Embedding count mismatch."}

        session.execute(delete(SchemaVector).where(SchemaVector.job_id == job_id))
        for column, vector, text in zip(columns, embeddings, texts):
            session.add(
                SchemaVector(
                    id=uuid4().hex,
                    job_id=job_id,
                    source_name=str(column.get("source_name", "")),
                    suggested_name=column.get("suggested_name"),
                    inferred_type=column.get("inferred_type"),
                    description=column.get("description"),
                    representation=text,
                    embedding=vector,
                    meta={"confidence": column.get("confidence")},
                )
            )
        session.commit()
        return {"status": "ok", "count": len(columns)}
    finally:
        session.close()


@router.post("/api/v1/schema/match")
async def match_schema(request: Request, body: SchemaMatchRequest) -> Dict[str, Any]:
    settings = request.app.state.settings
    model = settings.azure_openai_deployment_embeddings
    if not model:
        return {"status": "error", "message": "Embedding model deployment is not set."}
    query_text = body.text.strip()
    if not query_text:
        return {"status": "error", "message": "Text is required."}
    query_vector = embed_texts(request.app.state.llm_client, model, [query_text])[0]
    session = get_db_session(request.app.state.db_session_factory)
    try:
        stmt = select(SchemaVector)
        if body.job_id:
            stmt = stmt.where(SchemaVector.job_id == body.job_id)
        stmt = stmt.order_by(SchemaVector.embedding.cosine_distance(query_vector)).limit(body.top_k)
        rows = session.execute(stmt).scalars().all()
        matches = [
            {
                "id": row.id,
                "job_id": row.job_id,
                "source_name": row.source_name,
                "suggested_name": row.suggested_name,
                "inferred_type": row.inferred_type,
                "description": row.description,
                "metadata": row.meta,
            }
            for row in rows
        ]
        return {"status": "ok", "matches": matches}
    finally:
        session.close()


# ─── Code generation endpoint ──────────────────────────────────────────────────

@router.post("/api/v1/jobs/{job_id}/generate")
async def generate_code(request: Request, job_id: str) -> Dict[str, Any]:
    """Ask GPT to write a pandas cleaning script based on the confirmed schema."""
    session = get_db_session(request.app.state.db_session_factory)
    try:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()
        if not job:
            return {"status": "error", "message": "Job not found."}
        if not job.analysis:
            return {"status": "error", "message": "No analysis available — run inference first."}
        if not job.result or not job.result.get("preview"):
            return {"status": "error", "message": "No parsed preview available."}

        schema = job.analysis.get("selected_schema") or job.analysis.get("schema_inference")
        if not schema:
            return {"status": "error", "message": "No schema selected — confirm schema first."}

        preview = job.result["preview"]
        # Enrich preview with file_type
        preview = dict(preview)
        preview["file_type"] = job.result.get("file_type", "csv")

        client = request.app.state.llm_client
        model = request.app.state.settings.azure_openai_deployment_gpt5_mini
        prompt = build_codegen_prompt(schema, preview)

        response = client.responses.create(model=model, input=prompt)
        raw_code = parse_generated_code(response.output_text)

        # Persist generated code into analysis
        analysis = dict(job.analysis)
        analysis["generated_code"] = raw_code
        analysis["generated_code_v"] = analysis.get("generated_code_v", 0) + 1
        job.analysis = analysis
        session.commit()

        return {
            "status": "ok",
            "code": raw_code,
            "version": analysis["generated_code_v"],
            "analysis": job.analysis,
        }
    finally:
        session.close()


# ─── Sandbox execution endpoint ────────────────────────────────────────────────

class ExecuteRequest(BaseModel):
    code: str | None = None  # If omitted, uses last generated_code


@router.post("/api/v1/jobs/{job_id}/execute")
async def execute_code(request: Request, job_id: str, body: ExecuteRequest | None = None) -> Dict[str, Any]:
    """Run the (optionally user-edited) cleaning script in the Docker sandbox."""
    session = get_db_session(request.app.state.db_session_factory)
    try:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()
        if not job:
            return {"status": "error", "message": "Job not found."}

        # Resolve which code to run
        user_code = (body.code if body and body.code else None) or (
            job.analysis or {}
        ).get("generated_code")
        if not user_code:
            return {"status": "error", "message": "No code available — generate first."}

        session_mgr = getattr(request.app.state, "session_manager", None)
        if not session_mgr:
            return {"status": "error", "message": "Sandbox not available (Docker not running?)."}

        storage_path = job.storage_path
        if not storage_path or not Path(storage_path).exists():
            return {"status": "error", "message": "Source file not found on disk."}

        file_type = (job.result or {}).get("file_type", "csv")
        original_ext = Path(storage_path).suffix.lower() or ".csv"

        # Create sandbox session
        sandbox_session = session_mgr.create_session()
        sandbox_log = ""
        cleaned_preview = None
        output_path_host = Path(sandbox_session.workspace_dir) / "output.csv"

        try:
            # Upload source file into sandbox workspace
            with open(storage_path, "rb") as fh:
                input_filename = "input_file" + original_ext
                session_mgr.upload_file(sandbox_session, input_filename, fh.read())

            # Inject env vars before the preamble so SANDBOX_PREAMBLE picks them up
            env_block = (
                f'import os\n'
                f'os.environ["INPUT_PATH"]  = "/sandbox/data/{input_filename}"\n'
                f'os.environ["OUTPUT_PATH"] = "/sandbox/data/output.csv"\n'
                f'os.environ["FILE_TYPE"]   = "{file_type}"\n\n'
            )
            wrapped = env_block + wrap_for_sandbox(user_code)

            sandbox_log = session_mgr.execute_code(sandbox_session, wrapped, timeout_seconds=120)

            # Read back the output CSV if it exists
            if output_path_host.exists():
                with open(output_path_host, "r", encoding="utf-8-sig", errors="replace") as f:
                    reader = csv.DictReader(f)
                    rows = []
                    for i, row in enumerate(reader):
                        if i >= 100:
                            break
                        rows.append(dict(row))
                cleaned_preview = {
                    "columns": list(rows[0].keys()) if rows else [],
                    "sample_rows": rows[:20],
                    "row_count": sum(1 for _ in open(output_path_host, encoding="utf-8-sig")) - 1,
                }
        except Exception as exec_err:
            sandbox_log = str(exec_err)

            # Self-healing: one reflexion retry
            try:
                client = request.app.state.llm_client
                model = request.app.state.settings.azure_openai_deployment_gpt5_mini
                fix_prompt = build_codegen_reflexion_prompt(user_code, sandbox_log)
                fix_response = client.responses.create(model=model, input=fix_prompt)
                fixed_code = parse_generated_code(fix_response.output_text)

                # Upload fresh copy of file for retry
                with open(storage_path, "rb") as fh:
                    session_mgr.upload_file(sandbox_session, input_filename, fh.read())

                wrapped_fix = env_block + wrap_for_sandbox(fixed_code)

                sandbox_log += "\n\n--- SELF-HEAL RETRY ---\n"
                sandbox_log += session_mgr.execute_code(sandbox_session, wrapped_fix, timeout_seconds=120)

                if output_path_host.exists():
                    with open(output_path_host, "r", encoding="utf-8-sig", errors="replace") as f:
                        reader = csv.DictReader(f)
                        rows = []
                        for i, row in enumerate(reader):
                            if i >= 100:
                                break
                            rows.append(dict(row))
                    cleaned_preview = {
                        "columns": list(rows[0].keys()) if rows else [],
                        "sample_rows": rows[:20],
                        "row_count": sum(1 for _ in open(output_path_host, encoding="utf-8-sig")) - 1,
                    }

                # Save the fixed code back into analysis
                analysis = dict(job.analysis or {})
                analysis["generated_code"] = fixed_code
                analysis["self_healed"] = True
                job.analysis = analysis
            except Exception as heal_err:
                sandbox_log += f"\n--- SELF-HEAL FAILED: {heal_err} ---"
        finally:
            session_mgr.close_session(sandbox_session)

        # Persist execution result
        analysis = dict(job.analysis or {})
        analysis["execution_log"] = sandbox_log[-4000:]        # keep last 4k chars
        analysis["cleaned_preview"] = cleaned_preview
        analysis["execution_ok"] = cleaned_preview is not None
        job.analysis = analysis
        session.commit()

        return {
            "status": "ok" if cleaned_preview else "error",
            "sandbox_log": sandbox_log[-2000:],
            "cleaned_preview": cleaned_preview,
            "analysis": job.analysis,
        }
    finally:
        session.close()


# ─── Download cleaned CSV ──────────────────────────────────────────────────────

@router.get("/api/v1/jobs/{job_id}/download")
async def download_cleaned(request: Request, job_id: str) -> StreamingResponse:
    """Stream the output.csv from the sandbox workspace back to the browser."""
    session = get_db_session(request.app.state.db_session_factory)
    try:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()
        if not job:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Job not found.")

        # The sandbox workspace is stored under storage_dir/sandbox/<session_id>/output.csv
        # We look for any output.csv under storage/sandbox/ belonging to this job.
        # Simpler: store output_path in analysis during execute.
        cleaned_preview = (job.analysis or {}).get("cleaned_preview")
        if not cleaned_preview:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="No cleaned output available — run execute first.")

        settings = request.app.state.settings
        sandbox_root = Path(settings.local_storage_dir) / "sandbox"

        # Find most recent output.csv for this job
        output_file: Path | None = None
        if sandbox_root.exists():
            candidates = sorted(
                sandbox_root.glob("*/output.csv"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if candidates:
                output_file = candidates[0]

        if not output_file or not output_file.exists():
            # Fall back: regenerate from cleaned_preview
            rows = cleaned_preview.get("sample_rows", [])
            cols = cleaned_preview.get("columns", [])
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=cols)
            writer.writeheader()
            writer.writerows(rows)
            buf.seek(0)
            content = buf.getvalue().encode("utf-8-sig")
            return StreamingResponse(
                io.BytesIO(content),
                media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="{job.filename}_cleaned.csv"'},
            )

        def file_streamer():
            with open(output_file, "rb") as f:
                while chunk := f.read(65536):
                    yield chunk

        return StreamingResponse(
            file_streamer(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{Path(job.filename).stem}_cleaned.csv"'},
        )
    finally:
        session.close()
