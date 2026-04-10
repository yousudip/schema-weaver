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
    build_validation_prompt,
    parse_generated_code,
    parse_validation_response,
    wrap_for_sandbox,
)
from backend.app.llm.quality import compute_quality_report

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
            "purpose": job.purpose,
            "description": job.description,
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
        model = request.app.state.settings.openai_deployment_gpt5_mini
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
    model = settings.openai_deployment_embeddings
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
    model = settings.openai_deployment_embeddings
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
        model = request.app.state.settings.openai_deployment_gpt5_mini
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
    """
    Run the cleaning script in the Docker sandbox, then validate quality.
    Automatically retries up to MAX_VALIDATION_ATTEMPTS times if the LLM
    flags critical quality issues (e.g. all dates are empty).
    """
    MAX_VALIDATION_ATTEMPTS = 3

    session = get_db_session(request.app.state.db_session_factory)
    try:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()
        if not job:
            return {"status": "error", "message": "Job not found."}

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

        schema = (job.analysis or {}).get("selected_schema") or (job.analysis or {}).get("schema_inference") or {}
        raw_sample_rows = (job.result or {}).get("preview", {}).get("sample_rows", [])
        file_type = (job.result or {}).get("file_type", "csv")
        original_ext = Path(storage_path).suffix.lower() or ".csv"
        input_filename = "input_file" + original_ext

        client = request.app.state.llm_client
        model = request.app.state.settings.openai_deployment_gpt5_mini

        sandbox_session = session_mgr.create_session()
        output_path_host = Path(sandbox_session.workspace_dir) / "output.csv"

        # Pre-build the env injection block (reused across all attempts)
        env_block = (
            f'import os\n'
            f'os.environ["INPUT_PATH"]  = "/sandbox/data/{input_filename}"\n'
            f'os.environ["OUTPUT_PATH"] = "/sandbox/data/output.csv"\n'
            f'os.environ["FILE_TYPE"]   = "{file_type}"\n\n'
        )

        sandbox_log = ""
        cleaned_preview = None
        quality_report = None
        validation_attempts: list[dict] = []
        current_code = user_code

        try:
            # ── Upload source file once ──────────────────────────────────────
            with open(storage_path, "rb") as fh:
                session_mgr.upload_file(sandbox_session, input_filename, fh.read())

            for attempt in range(MAX_VALIDATION_ATTEMPTS):
                attempt_log = f"\n{'='*60}\n--- ATTEMPT {attempt + 1}/{MAX_VALIDATION_ATTEMPTS} ---\n"

                # ── Step 1: Run the script ────────────────────────────────────
                run_ok = False
                try:
                    wrapped = env_block + wrap_for_sandbox(current_code)
                    run_output = session_mgr.execute_code(sandbox_session, wrapped, timeout_seconds=120)
                    attempt_log += run_output
                    run_ok = True
                except Exception as run_err:
                    attempt_log += f"EXECUTION ERROR: {run_err}"
                    # Self-heal crash with reflexion prompt
                    try:
                        fix_prompt = build_codegen_reflexion_prompt(current_code, str(run_err))
                        fix_resp = client.responses.create(model=model, input=fix_prompt)
                        current_code = parse_generated_code(fix_resp.output_text)
                        attempt_log += "\n[reflexion fix applied — retrying next attempt]"
                        # Re-upload source file before next attempt
                        with open(storage_path, "rb") as fh:
                            session_mgr.upload_file(sandbox_session, input_filename, fh.read())
                    except Exception as heal_err:
                        attempt_log += f"\n[reflexion failed: {heal_err}]"
                    sandbox_log += attempt_log
                    validation_attempts.append({"attempt": attempt + 1, "run_ok": False, "verdict": "crash"})
                    continue

                sandbox_log += attempt_log

                if not run_ok or not output_path_host.exists():
                    validation_attempts.append({"attempt": attempt + 1, "run_ok": False, "verdict": "no_output"})
                    continue

                # ── Step 2: Build cleaned preview ─────────────────────────────
                with open(output_path_host, "r", encoding="utf-8-sig", errors="replace") as f:
                    reader = csv.DictReader(f)
                    rows = [dict(r) for i, r in enumerate(reader) if i < 100]
                cleaned_preview = {
                    "columns": list(rows[0].keys()) if rows else [],
                    "sample_rows": rows[:20],
                    "row_count": sum(1 for _ in open(output_path_host, encoding="utf-8-sig")) - 1,
                }

                # ── Step 3: Compute quality report ────────────────────────────
                quality_report = compute_quality_report(output_path_host, schema)
                sandbox_log += (
                    f"\n[quality] overall_fill={quality_report['overall_fill_rate']*100:.1f}%"
                    f"  pass={quality_report['pass']}"
                    f"  rows={quality_report['total_rows']}\n"
                )
                for cr in quality_report.get("columns", []):
                    if cr.get("issues"):
                        sandbox_log += f"  ⚠ {cr['name']}: {'; '.join(cr['issues'])}\n"

                validation_attempts.append({
                    "attempt": attempt + 1,
                    "run_ok": True,
                    "verdict": "pass" if quality_report["pass"] else "pending",
                    "fill_rate": quality_report["overall_fill_rate"],
                })

                # ── Step 4: LLM judges quality ────────────────────────────────
                if quality_report["pass"]:
                    sandbox_log += "\n[validation] ✅ Quality check PASSED\n"
                    break

                if attempt >= MAX_VALIDATION_ATTEMPTS - 1:
                    sandbox_log += "\n[validation] ⚠ Max attempts reached — keeping best output\n"
                    break

                sandbox_log += "\n[validation] ❌ Quality issues found — asking LLM to fix...\n"
                try:
                    val_prompt = build_validation_prompt(
                        schema, quality_report, current_code, raw_sample_rows
                    )
                    val_resp = client.responses.create(model=model, input=val_prompt)
                    verdict = parse_validation_response(val_resp.output_text)
                    sandbox_log += f"[validation verdict] {verdict.get('verdict','?')}\n"

                    if verdict.get("verdict") == "pass":
                        sandbox_log += "[validation] LLM says quality is acceptable\n"
                        break

                    issues_reported = verdict.get("issues", [])
                    for iss in issues_reported:
                        sandbox_log += f"  LLM issue: {iss}\n"

                    fixed_code = verdict.get("fixed_code", "")
                    if fixed_code:
                        current_code = parse_generated_code(fixed_code) if "```" in fixed_code else fixed_code
                        sandbox_log += "[validation] LLM rewrote the script — retrying...\n"
                        # Re-upload source file for next attempt
                        with open(storage_path, "rb") as fh:
                            session_mgr.upload_file(sandbox_session, input_filename, fh.read())
                        # Rename old output to a backup instead of deleting it — if later
                        # attempts crash we can fall back to this best-so-far output.
                        if output_path_host.exists():
                            backup = output_path_host.with_name("output_best.csv")
                            output_path_host.rename(backup)
                    else:
                        sandbox_log += "[validation] LLM gave no fixed_code — stopping\n"
                        break

                except Exception as val_err:
                    sandbox_log += f"[validation error] {val_err} — keeping current output\n"
                    break

        finally:
            session_mgr.close_session(sandbox_session)

        # ── If final output.csv is missing, restore the best-so-far backup ────
        backup_path = output_path_host.with_name("output_best.csv")
        if not output_path_host.exists() and backup_path.exists():
            backup_path.rename(output_path_host)
            sandbox_log += "\n[validation] ⚠ Later attempts crashed — restored best output from earlier attempt\n"
            # Re-read cleaned_preview from the restored file
            try:
                with open(str(output_path_host), "r", encoding="utf-8-sig", errors="replace") as f:
                    reader = csv.DictReader(f)
                    rows = [dict(r) for i, r in enumerate(reader) if i < 100]
                if rows:
                    cleaned_preview = {
                        "columns": list(rows[0].keys()),
                        "sample_rows": rows[:20],
                        "row_count": sum(1 for _ in open(str(output_path_host), encoding="utf-8-sig")) - 1,
                    }
            except Exception:
                pass  # keep whatever cleaned_preview we already have

        # ── Persist everything ────────────────────────────────────────────────
        analysis = dict(job.analysis or {})
        analysis["execution_log"] = sandbox_log[-6000:]
        analysis["cleaned_preview"] = cleaned_preview
        analysis["quality_report"] = quality_report
        analysis["execution_ok"] = cleaned_preview is not None
        analysis["validation_attempts"] = validation_attempts
        if current_code != user_code:
            analysis["generated_code"] = current_code
            analysis["self_healed"] = True
        job.analysis = analysis
        session.commit()

        return {
            "status": "ok" if cleaned_preview else "error",
            "sandbox_log": sandbox_log[-3000:],
            "cleaned_preview": cleaned_preview,
            "quality_report": quality_report,
            "validation_attempts": validation_attempts,
            "analysis": job.analysis,
        }
    finally:
        session.close()


# ─── Streaming sandbox execution endpoint ─────────────────────────────────────

@router.post("/api/v1/jobs/{job_id}/execute/stream")
async def execute_code_stream(request: Request, job_id: str, body: ExecuteRequest | None = None) -> StreamingResponse:
    """
    SSE streaming version of execute — yields progress events after each attempt
    so the UI can show live status while the validation loop runs.

    Events emitted:
      attempt_start   → {"attempt": N, "total": 3, "message": "..."}
      attempt_result  → {"attempt": N, "run_ok": true, "fill_rate": 0.84, "pass": false, "message": "..."}
      attempt_crash   → {"attempt": N, "message": "..."}
      llm_fixing      → {"attempt": N, "message": "Asking LLM to rewrite..."}
      complete        → {status, sandbox_log, cleaned_preview, quality_report, validation_attempts}
      error           → {"message": "..."}
    """
    import asyncio as _asyncio
    import json as _json

    def _sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {_json.dumps(data)}\n\n"

    async def _generate():  # noqa: C901
        loop = _asyncio.get_event_loop()
        MAX_VALIDATION_ATTEMPTS = 3

        session = get_db_session(request.app.state.db_session_factory)
        try:
            job = session.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()
            if not job:
                yield _sse("error", {"message": "Job not found."})
                return

            user_code = (body.code if body and body.code else None) or (job.analysis or {}).get("generated_code")
            if not user_code:
                yield _sse("error", {"message": "No code available — generate first."})
                return

            session_mgr = getattr(request.app.state, "session_manager", None)
            if not session_mgr:
                yield _sse("error", {"message": "Sandbox not available (Docker not running?)."})
                return

            storage_path = job.storage_path
            if not storage_path or not Path(storage_path).exists():
                yield _sse("error", {"message": "Source file not found on disk."})
                return

            schema = (job.analysis or {}).get("selected_schema") or (job.analysis or {}).get("schema_inference") or {}
            raw_sample_rows = (job.result or {}).get("preview", {}).get("sample_rows", [])
            file_type = (job.result or {}).get("file_type", "csv")
            original_ext = Path(storage_path).suffix.lower() or ".csv"
            input_filename = "input_file" + original_ext

            client = request.app.state.llm_client
            model = request.app.state.settings.openai_deployment_gpt5_mini

            sandbox_session = session_mgr.create_session()
            output_path_host = Path(sandbox_session.workspace_dir) / "output.csv"

            env_block = (
                f'import os\n'
                f'os.environ["INPUT_PATH"]  = "/sandbox/data/{input_filename}"\n'
                f'os.environ["OUTPUT_PATH"] = "/sandbox/data/output.csv"\n'
                f'os.environ["FILE_TYPE"]   = "{file_type}"\n\n'
            )

            sandbox_log = ""
            cleaned_preview = None
            quality_report = None
            validation_attempts: list[dict] = []
            current_code = user_code

            try:
                # Upload source file once
                with open(storage_path, "rb") as fh:
                    file_bytes = fh.read()
                await loop.run_in_executor(
                    None, lambda: session_mgr.upload_file(sandbox_session, input_filename, file_bytes)
                )

                for attempt in range(MAX_VALIDATION_ATTEMPTS):
                    yield _sse("attempt_start", {
                        "attempt": attempt + 1,
                        "total": MAX_VALIDATION_ATTEMPTS,
                        "message": f"Running script (attempt {attempt + 1}/{MAX_VALIDATION_ATTEMPTS})...",
                    })

                    attempt_log = f"\n{'='*60}\n--- ATTEMPT {attempt + 1}/{MAX_VALIDATION_ATTEMPTS} ---\n"
                    run_ok = False

                    # ── Run script ────────────────────────────────────────────
                    try:
                        wrapped = env_block + wrap_for_sandbox(current_code)
                        run_output = await loop.run_in_executor(
                            None,
                            lambda w=wrapped: session_mgr.execute_code(sandbox_session, w, timeout_seconds=120),
                        )
                        attempt_log += run_output
                        run_ok = True
                    except Exception as run_err:
                        attempt_log += f"EXECUTION ERROR: {run_err}"
                        yield _sse("attempt_crash", {
                            "attempt": attempt + 1,
                            "message": str(run_err)[:300],
                        })
                        # Reflexion fix
                        try:
                            fix_prompt = build_codegen_reflexion_prompt(current_code, str(run_err))
                            fix_resp = await loop.run_in_executor(
                                None, lambda p=fix_prompt: client.responses.create(model=model, input=p)
                            )
                            current_code = parse_generated_code(fix_resp.output_text)
                            attempt_log += "\n[reflexion fix applied — retrying next attempt]"
                            with open(storage_path, "rb") as fh:
                                fb = fh.read()
                            await loop.run_in_executor(
                                None, lambda: session_mgr.upload_file(sandbox_session, input_filename, fb)
                            )
                        except Exception as heal_err:
                            attempt_log += f"\n[reflexion failed: {heal_err}]"
                        sandbox_log += attempt_log
                        validation_attempts.append({"attempt": attempt + 1, "run_ok": False, "verdict": "crash"})
                        continue

                    sandbox_log += attempt_log

                    if not run_ok or not output_path_host.exists():
                        validation_attempts.append({"attempt": attempt + 1, "run_ok": False, "verdict": "no_output"})
                        yield _sse("attempt_crash", {"attempt": attempt + 1, "message": "Script ran but produced no output."})
                        continue

                    # ── Build cleaned preview ─────────────────────────────────
                    with open(output_path_host, "r", encoding="utf-8-sig", errors="replace") as f:
                        reader = csv.DictReader(f)
                        rows = [dict(r) for i, r in enumerate(reader) if i < 100]
                    cleaned_preview = {
                        "columns": list(rows[0].keys()) if rows else [],
                        "sample_rows": rows[:20],
                        "row_count": sum(1 for _ in open(output_path_host, encoding="utf-8-sig")) - 1,
                    }

                    # ── Quality report ────────────────────────────────────────
                    quality_report = compute_quality_report(output_path_host, schema)
                    fill_pct = round(quality_report["overall_fill_rate"] * 100, 1)
                    passed = quality_report["pass"]

                    sandbox_log += (
                        f"\n[quality] overall_fill={fill_pct}%  pass={passed}"
                        f"  rows={quality_report['total_rows']}\n"
                    )
                    for cr in quality_report.get("columns", []):
                        if cr.get("issues"):
                            sandbox_log += f"  ⚠ {cr['name']}: {'; '.join(cr['issues'])}\n"

                    validation_attempts.append({
                        "attempt": attempt + 1,
                        "run_ok": True,
                        "verdict": "pass" if passed else "pending",
                        "fill_rate": quality_report["overall_fill_rate"],
                    })

                    yield _sse("attempt_result", {
                        "attempt": attempt + 1,
                        "run_ok": True,
                        "fill_rate": quality_report["overall_fill_rate"],
                        "pass": passed,
                        "message": "✅ Quality passed!" if passed else f"⚠ {fill_pct}% fill — quality issues found",
                    })

                    if passed:
                        sandbox_log += "\n[validation] ✅ Quality check PASSED\n"
                        break

                    if attempt >= MAX_VALIDATION_ATTEMPTS - 1:
                        sandbox_log += "\n[validation] ⚠ Max attempts reached — keeping best output\n"
                        break

                    # ── Ask LLM to fix ────────────────────────────────────────
                    sandbox_log += "\n[validation] ❌ Quality issues — asking LLM to fix...\n"
                    yield _sse("llm_fixing", {
                        "attempt": attempt + 1,
                        "message": "Asking LLM to rewrite the script for better date parsing...",
                    })

                    try:
                        val_prompt = build_validation_prompt(schema, quality_report, current_code, raw_sample_rows)
                        val_resp = await loop.run_in_executor(
                            None, lambda p=val_prompt: client.responses.create(model=model, input=p)
                        )
                        verdict = parse_validation_response(val_resp.output_text)
                        sandbox_log += f"[validation verdict] {verdict.get('verdict','?')}\n"

                        if verdict.get("verdict") == "pass":
                            sandbox_log += "[validation] LLM says quality is acceptable\n"
                            break

                        for iss in verdict.get("issues", []):
                            sandbox_log += f"  LLM issue: {iss}\n"

                        fixed_code = verdict.get("fixed_code", "")
                        if fixed_code:
                            current_code = parse_generated_code(fixed_code) if "```" in fixed_code else fixed_code
                            sandbox_log += "[validation] LLM rewrote the script — retrying...\n"
                            with open(storage_path, "rb") as fh:
                                fb = fh.read()
                            await loop.run_in_executor(
                                None, lambda: session_mgr.upload_file(sandbox_session, input_filename, fb)
                            )
                            if output_path_host.exists():
                                backup = output_path_host.with_name("output_best.csv")
                                output_path_host.rename(backup)
                        else:
                            sandbox_log += "[validation] LLM gave no fixed_code — stopping\n"
                            break

                    except Exception as val_err:
                        sandbox_log += f"[validation error] {val_err} — keeping current output\n"
                        break

            finally:
                session_mgr.close_session(sandbox_session)

            # Restore best backup if final output missing
            backup_path = output_path_host.with_name("output_best.csv")
            if not output_path_host.exists() and backup_path.exists():
                backup_path.rename(output_path_host)
                sandbox_log += "\n[validation] ⚠ Later attempts crashed — restored best output\n"
                try:
                    with open(str(output_path_host), "r", encoding="utf-8-sig", errors="replace") as f:
                        reader = csv.DictReader(f)
                        rows = [dict(r) for i, r in enumerate(reader) if i < 100]
                    if rows:
                        cleaned_preview = {
                            "columns": list(rows[0].keys()),
                            "sample_rows": rows[:20],
                            "row_count": sum(1 for _ in open(str(output_path_host), encoding="utf-8-sig")) - 1,
                        }
                except Exception:
                    pass

            # Persist
            analysis_dict = dict(job.analysis or {})
            analysis_dict["execution_log"] = sandbox_log[-6000:]
            analysis_dict["cleaned_preview"] = cleaned_preview
            analysis_dict["quality_report"] = quality_report
            analysis_dict["execution_ok"] = cleaned_preview is not None
            analysis_dict["validation_attempts"] = validation_attempts
            if current_code != user_code:
                analysis_dict["generated_code"] = current_code
                analysis_dict["self_healed"] = True
            job.analysis = analysis_dict
            session.commit()

            yield _sse("complete", {
                "status": "ok" if cleaned_preview else "error",
                "sandbox_log": sandbox_log[-3000:],
                "cleaned_preview": cleaned_preview,
                "quality_report": quality_report,
                "validation_attempts": validation_attempts,
            })

        except Exception as exc:
            yield _sse("error", {"message": str(exc)})
        finally:
            session.close()

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


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
