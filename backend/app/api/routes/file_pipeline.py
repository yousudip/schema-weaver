"""
File-scoped pipeline routes for Phase 5 multi-file jobs.

Each endpoint mirrors the existing job-level pipeline but operates on a
JobFile record rather than the Job itself. The parent Job's `purpose` is
injected into every LLM call so the model has business context.

Endpoints:
  POST /api/v1/jobs/{job_id}/files/{file_id}/infer
  POST /api/v1/jobs/{job_id}/files/{file_id}/schema/select
  POST /api/v1/jobs/{job_id}/files/{file_id}/generate
  POST /api/v1/jobs/{job_id}/files/{file_id}/execute/stream
  GET  /api/v1/jobs/{job_id}/files/{file_id}/download
"""

import csv
import io
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from backend.app.db import get_db_session
from backend.app.db_models import Job, JobFile
from backend.app.llm.inference import (
    SchemaInference,
    build_prompt,
    build_reflexion_prompt,
    coerce_inference_payload,
    parse_llm_json,
)
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


def _get_job_and_file(session, job_id: str, file_id: str):
    """Helper — fetches both rows and raises 404 if either is missing."""
    job = session.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    jf = session.execute(
        select(JobFile).where(JobFile.id == file_id, JobFile.job_id == job_id)
    ).scalar_one_or_none()
    if not jf:
        raise HTTPException(status_code=404, detail="File not found in this job.")
    return job, jf


# ─── Infer schema ──────────────────────────────────────────────────────────────

@router.post("/api/v1/jobs/{job_id}/files/{file_id}/infer")
async def infer_file_schema(request: Request, job_id: str, file_id: str) -> Dict[str, Any]:
    session = get_db_session(request.app.state.db_session_factory)
    try:
        job, jf = _get_job_and_file(session, job_id, file_id)

        if not jf.result:
            return {"status": "error", "message": "File has no parsed preview — upload a valid file first."}
        preview = jf.result.get("preview")
        if not preview:
            return {"status": "error", "message": "No preview available for inference."}

        jf.status = "inferring"
        session.commit()

        client = request.app.state.llm_client
        model = request.app.state.settings.azure_openai_deployment_gpt5_mini
        purpose = job.purpose

        prompt = build_prompt(preview, purpose=purpose)
        response = client.responses.create(model=model, input=prompt)
        raw_text = response.output_text
        parsed = coerce_inference_payload(parse_llm_json(raw_text))

        try:
            validated = SchemaInference.model_validate(parsed).model_dump()
        except ValidationError as exc:
            retry_prompt = build_reflexion_prompt(preview, str(exc))
            retry_resp = client.responses.create(model=model, input=retry_prompt)
            retry_parsed = coerce_inference_payload(parse_llm_json(retry_resp.output_text))
            try:
                validated = SchemaInference.model_validate(retry_parsed).model_dump()
            except ValidationError as retry_exc:
                jf.status = "failed"
                jf.error = str(retry_exc)
                session.commit()
                return {"status": "error", "message": "LLM output failed validation.", "details": str(retry_exc)}

        analysis = dict(jf.analysis or {})
        analysis["schema_inference"] = validated
        jf.analysis = analysis
        jf.status = "ready"
        session.commit()
        return {"status": "ok", "analysis": jf.analysis}
    finally:
        session.close()


# ─── Select / confirm schema ───────────────────────────────────────────────────

class FileSchemaSelectRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    schema_payload: Dict[str, Any] | None = Field(default=None, alias="schema")


@router.post("/api/v1/jobs/{job_id}/files/{file_id}/schema/select")
async def select_file_schema(
    request: Request, job_id: str, file_id: str,
    body: FileSchemaSelectRequest | None = None,
) -> Dict[str, Any]:
    session = get_db_session(request.app.state.db_session_factory)
    try:
        _, jf = _get_job_and_file(session, job_id, file_id)
        analysis = dict(jf.analysis or {})
        schema = (
            body.schema_payload if body and body.schema_payload
            else analysis.get("schema_inference")
        )
        if not schema:
            return {"status": "error", "message": "No schema available to select."}
        analysis["selected_schema"] = schema
        jf.analysis = analysis
        session.commit()
        return {"status": "ok", "analysis": jf.analysis}
    finally:
        session.close()


# ─── Generate cleaning code ────────────────────────────────────────────────────

@router.post("/api/v1/jobs/{job_id}/files/{file_id}/generate")
async def generate_file_code(request: Request, job_id: str, file_id: str) -> Dict[str, Any]:
    session = get_db_session(request.app.state.db_session_factory)
    try:
        job, jf = _get_job_and_file(session, job_id, file_id)

        if not jf.analysis:
            return {"status": "error", "message": "No analysis available — run inference first."}
        if not jf.result or not jf.result.get("preview"):
            return {"status": "error", "message": "No parsed preview available."}

        schema = jf.analysis.get("selected_schema") or jf.analysis.get("schema_inference")
        if not schema:
            return {"status": "error", "message": "No schema selected — confirm schema first."}

        preview = dict(jf.result["preview"])
        raw_file_type = jf.result.get("file_type", "csv")
        # PDFs are pre-extracted to tabular rows — treat as CSV for codegen
        preview["file_type"] = "csv" if raw_file_type == "pdf" else raw_file_type
        if raw_file_type == "pdf":
            preview["source_note"] = (
                "IMPORTANT: This data was extracted from a PDF and converted to a CSV file. "
                "The input file IS a CSV — always read it with pd.read_csv(input_path, dtype=str). "
                "The file_type variable is 'csv'. "
                "NEVER add any 'if file_type == \"pdf\"' checks — they will break execution. "
                "NEVER raise NotImplementedError or return early for PDF types. "
                "Treat this exactly like any other CSV input."
            )

        jf.status = "generating"
        session.commit()

        client = request.app.state.llm_client
        model = request.app.state.settings.azure_openai_deployment_gpt5_mini
        prompt = build_codegen_prompt(schema, preview, purpose=job.purpose)

        response = client.responses.create(model=model, input=prompt)
        raw_code = parse_generated_code(response.output_text)

        # Post-process: strip any stray PDF checks the LLM may have added
        if raw_file_type == "pdf":
            import re as _re
            # Remove entire if-blocks that check for pdf file_type (they write empty output or raise)
            raw_code = _re.sub(
                r"(?m)^\s*if\s+file_type(?:\.lower\(\))?\s*(?:==|in)\s*['\"]pdf['\"].*?(?=\n\S|\Z)",
                "",
                raw_code,
                flags=_re.DOTALL,
            ).strip()

        analysis = dict(jf.analysis)
        analysis["generated_code"] = raw_code
        analysis["generated_code_v"] = analysis.get("generated_code_v", 0) + 1
        jf.analysis = analysis
        jf.status = "ready"
        session.commit()

        return {
            "status": "ok",
            "code": raw_code,
            "version": analysis["generated_code_v"],
            "analysis": jf.analysis,
        }
    finally:
        session.close()


# ─── Streaming execute with validation loop ────────────────────────────────────

class FileExecuteRequest(BaseModel):
    code: str | None = None


@router.post("/api/v1/jobs/{job_id}/files/{file_id}/execute/stream")
async def execute_file_stream(
    request: Request, job_id: str, file_id: str,
    body: FileExecuteRequest | None = None,
) -> StreamingResponse:
    """
    SSE streaming execution for a specific file within a job.
    Identical validation loop to the job-level endpoint, but reads/writes
    from JobFile instead of Job.
    """
    import asyncio as _asyncio
    import json as _json

    def _sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {_json.dumps(data)}\n\n"

    async def _generate():  # noqa: C901
        loop = _asyncio.get_event_loop()
        MAX_ATTEMPTS = 3

        session = get_db_session(request.app.state.db_session_factory)
        try:
            try:
                job, jf = _get_job_and_file(session, job_id, file_id)
            except HTTPException as e:
                yield _sse("error", {"message": e.detail})
                return

            user_code = (body.code if body and body.code else None) or (jf.analysis or {}).get("generated_code")
            if not user_code:
                yield _sse("error", {"message": "No code available — generate first."})
                return

            session_mgr = getattr(request.app.state, "session_manager", None)
            if not session_mgr:
                yield _sse("error", {"message": "Sandbox not available (Docker not running?)."})
                return

            storage_path = jf.storage_path
            if not storage_path or not Path(storage_path).exists():
                yield _sse("error", {"message": "Source file not found on disk."})
                return

            schema = (jf.analysis or {}).get("selected_schema") or (jf.analysis or {}).get("schema_inference") or {}
            raw_sample_rows = (jf.result or {}).get("preview", {}).get("sample_rows", [])
            raw_file_type = (jf.result or {}).get("file_type", "csv")

            # PDFs: use the extracted tabular rows as a CSV input (not the binary PDF)
            is_pdf = raw_file_type == "pdf"
            file_type = "csv" if is_pdf else raw_file_type
            original_ext = ".csv" if is_pdf else (Path(storage_path).suffix.lower() or ".csv")
            input_filename = "input_file" + original_ext

            client = request.app.state.llm_client
            model = request.app.state.settings.azure_openai_deployment_gpt5_mini

            jf.status = "executing"
            session.commit()

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
                if is_pdf:
                    # Write extracted rows as CSV — the sandbox can only read csv/excel
                    import csv as _csv
                    import io as _io
                    preview_data = (jf.result or {}).get("preview", {})
                    columns_list = preview_data.get("columns", [])
                    rows_list = preview_data.get("sample_rows", [])
                    buf = _io.StringIO()
                    writer = _csv.DictWriter(buf, fieldnames=columns_list, extrasaction="ignore")
                    writer.writeheader()
                    writer.writerows(rows_list)
                    file_bytes = buf.getvalue().encode("utf-8-sig")
                else:
                    with open(storage_path, "rb") as fh:
                        file_bytes = fh.read()
                await loop.run_in_executor(
                    None, lambda: session_mgr.upload_file(sandbox_session, input_filename, file_bytes)
                )

                for attempt in range(MAX_ATTEMPTS):
                    yield _sse("attempt_start", {
                        "attempt": attempt + 1,
                        "total": MAX_ATTEMPTS,
                        "message": f"Running script (attempt {attempt + 1}/{MAX_ATTEMPTS})...",
                        "file_id": file_id,
                    })

                    attempt_log = f"\n{'='*60}\n--- ATTEMPT {attempt + 1}/{MAX_ATTEMPTS} ---\n"
                    run_ok = False
                    # Capture the code used for THIS attempt (before any reflexion rewrites it)
                    attempt_code = current_code

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
                            "attempt": attempt + 1, "message": str(run_err)[:300], "file_id": file_id,
                        })
                        try:
                            fix_prompt = build_codegen_reflexion_prompt(current_code, str(run_err))
                            fix_resp = await loop.run_in_executor(
                                None, lambda p=fix_prompt: client.responses.create(model=model, input=p)
                            )
                            current_code = parse_generated_code(fix_resp.output_text)
                            attempt_log += "\n[reflexion fix applied]"
                            await loop.run_in_executor(
                                None, lambda: session_mgr.upload_file(sandbox_session, input_filename, file_bytes)
                            )
                        except Exception as heal_err:
                            attempt_log += f"\n[reflexion failed: {heal_err}]"
                        sandbox_log += attempt_log
                        validation_attempts.append({"attempt": attempt + 1, "run_ok": False, "verdict": "crash", "code": attempt_code})
                        continue

                    sandbox_log += attempt_log

                    if not run_ok or not output_path_host.exists():
                        validation_attempts.append({"attempt": attempt + 1, "run_ok": False, "verdict": "no_output", "code": attempt_code})
                        yield _sse("attempt_crash", {
                            "attempt": attempt + 1, "message": "Script produced no output.", "file_id": file_id,
                        })
                        continue

                    # Build preview
                    with open(output_path_host, "r", encoding="utf-8-sig", errors="replace") as f:
                        reader = csv.DictReader(f)
                        rows = [dict(r) for i, r in enumerate(reader) if i < 100]
                    cleaned_preview = {
                        "columns": list(rows[0].keys()) if rows else [],
                        "sample_rows": rows[:20],
                        "row_count": sum(1 for _ in open(output_path_host, encoding="utf-8-sig")) - 1,
                    }

                    quality_report = compute_quality_report(output_path_host, schema)
                    fill_pct = round(quality_report["overall_fill_rate"] * 100, 1)
                    passed = quality_report["pass"]

                    sandbox_log += (
                        f"\n[quality] fill={fill_pct}%  pass={passed}"
                        f"  rows={quality_report['total_rows']}\n"
                    )

                    validation_attempts.append({
                        "attempt": attempt + 1,
                        "run_ok": True,
                        "verdict": "pass" if passed else "pending",
                        "fill_rate": quality_report["overall_fill_rate"],
                        "code": attempt_code,
                    })

                    yield _sse("attempt_result", {
                        "attempt": attempt + 1,
                        "run_ok": True,
                        "fill_rate": quality_report["overall_fill_rate"],
                        "pass": passed,
                        "message": "Quality passed!" if passed else f"{fill_pct}% fill — quality issues found",
                        "file_id": file_id,
                    })

                    if passed:
                        break

                    if attempt >= MAX_ATTEMPTS - 1:
                        break

                    yield _sse("llm_fixing", {
                        "attempt": attempt + 1,
                        "message": "Asking LLM to rewrite the script...",
                        "file_id": file_id,
                    })

                    try:
                        val_prompt = build_validation_prompt(schema, quality_report, current_code, raw_sample_rows)
                        val_resp = await loop.run_in_executor(
                            None, lambda p=val_prompt: client.responses.create(model=model, input=p)
                        )
                        verdict = parse_validation_response(val_resp.output_text)

                        if verdict.get("verdict") == "pass":
                            break

                        fixed_code = verdict.get("fixed_code", "")
                        if fixed_code:
                            current_code = parse_generated_code(fixed_code) if "```" in fixed_code else fixed_code
                            await loop.run_in_executor(
                                None, lambda: session_mgr.upload_file(sandbox_session, input_filename, file_bytes)
                            )
                            if output_path_host.exists():
                                output_path_host.rename(output_path_host.with_name("output_best.csv"))
                        else:
                            break
                    except Exception as val_err:
                        sandbox_log += f"[validation error] {val_err}\n"
                        break

            finally:
                session_mgr.close_session(sandbox_session)

            # Restore best backup if final output missing
            backup_path = output_path_host.with_name("output_best.csv")
            if not output_path_host.exists() and backup_path.exists():
                backup_path.rename(output_path_host)
                sandbox_log += "\n[restored best output from earlier attempt]\n"
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

            # Persist to JobFile
            analysis_dict = dict(jf.analysis or {})
            analysis_dict["execution_log"] = sandbox_log[-6000:]
            analysis_dict["cleaned_preview"] = cleaned_preview
            analysis_dict["quality_report"] = quality_report
            analysis_dict["execution_ok"] = cleaned_preview is not None
            analysis_dict["validation_attempts"] = validation_attempts
            if current_code != user_code:
                analysis_dict["generated_code"] = current_code
                analysis_dict["self_healed"] = True
            jf.analysis = analysis_dict
            jf.status = "validated" if (quality_report and quality_report.get("pass")) else (
                "ready" if cleaned_preview else "failed"
            )
            session.commit()

            yield _sse("complete", {
                "status": "ok" if cleaned_preview else "error",
                "sandbox_log": sandbox_log[-3000:],
                "cleaned_preview": cleaned_preview,
                "quality_report": quality_report,
                "validation_attempts": validation_attempts,
                "file_id": file_id,
            })

        except Exception as exc:
            yield _sse("error", {"message": str(exc), "file_id": file_id})
        finally:
            session.close()

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# ─── PDF extraction / tabularize SSE endpoint ────────────────────────────────

@router.post("/api/v1/jobs/{job_id}/files/{file_id}/extract/stream")
async def extract_pdf_stream(
    request: Request, job_id: str, file_id: str,
) -> StreamingResponse:
    """
    SSE streaming endpoint that detects, extracts, and tabularizes a PDF file.
    Events: detecting, extracting, tabularizing, complete, error.
    """
    import asyncio as _asyncio
    import json as _json

    def _sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {_json.dumps(data)}\n\n"

    async def _generate():
        loop = _asyncio.get_event_loop()

        session = get_db_session(request.app.state.db_session_factory)
        try:
            try:
                job, jf = _get_job_and_file(session, job_id, file_id)
            except HTTPException as e:
                yield _sse("error", {"message": e.detail, "file_id": file_id})
                return

            if jf.file_type != "pdf":
                yield _sse("error", {"message": "File is not a PDF.", "file_id": file_id})
                return

            storage_path = jf.storage_path
            if not storage_path or not Path(storage_path).exists():
                yield _sse("error", {"message": "PDF file not found on disk.", "file_id": file_id})
                return

            client = request.app.state.llm_client
            settings = request.app.state.settings
            model = settings.azure_openai_deployment_gpt5_mini
            purpose = job.purpose

            # Step 1: Detect
            yield _sse("detecting", {"message": "Detecting PDF type…", "file_id": file_id})

            try:
                from backend.app.parsers.pdf_tabularize import (
                    detect_pdf_type,
                    extract_text_pdf,
                    extract_image_pdf,
                    build_text_tabularize_prompt,
                    build_vision_tabularize_input,
                    parse_tabular_llm_response,
                )
                pdf_type = await loop.run_in_executor(
                    None, lambda: detect_pdf_type(Path(storage_path))
                )
            except Exception as exc:
                yield _sse("error", {"message": f"PDF detection failed: {exc}", "file_id": file_id})
                return

            # Step 2: Extract
            method_label = "text extraction" if pdf_type == "text" else "vision OCR"
            yield _sse("extracting", {
                "message": f"Extracting content via {method_label}…",
                "method": pdf_type,
                "file_id": file_id,
            })

            try:
                if pdf_type == "text":
                    raw_text = await loop.run_in_executor(
                        None, lambda: extract_text_pdf(Path(storage_path))
                    )
                    llm_input = await loop.run_in_executor(
                        None, lambda: build_text_tabularize_prompt(raw_text, purpose)
                    )
                else:
                    poppler_path = getattr(settings, "poppler_path", "") or ""
                    images_b64 = await loop.run_in_executor(
                        None, lambda: extract_image_pdf(Path(storage_path), poppler_path)
                    )
                    llm_input = await loop.run_in_executor(
                        None, lambda: build_vision_tabularize_input(images_b64, purpose)
                    )
            except Exception as exc:
                yield _sse("error", {"message": f"PDF extraction failed: {exc}", "file_id": file_id})
                return

            # Step 3: Tabularize via LLM
            yield _sse("tabularizing", {"message": "LLM tabularizing data…", "file_id": file_id})

            try:
                response = await loop.run_in_executor(
                    None, lambda: client.responses.create(model=model, input=llm_input)
                )
                raw_text_response = response.output_text
                parsed = await loop.run_in_executor(
                    None, lambda: parse_tabular_llm_response(raw_text_response)
                )
            except Exception as exc:
                yield _sse("error", {"message": f"LLM tabularization failed: {exc}", "file_id": file_id})
                return

            # Step 4: Persist result
            if parsed:
                jf.result = {
                    "preview": parsed,
                    "file_type": "pdf",
                    "extraction_method": pdf_type,
                }
                jf.status = "ready"
                session.commit()
                yield _sse("complete", {
                    "status": "ok",
                    "preview": parsed,
                    "method": pdf_type,
                    "file_id": file_id,
                })
            else:
                jf.status = "failed"
                jf.error = "Could not extract tabular data from PDF"
                session.commit()
                yield _sse("error", {
                    "message": "Could not extract tabular data from PDF",
                    "file_id": file_id,
                })

        except Exception as exc:
            yield _sse("error", {"message": str(exc), "file_id": file_id})
        finally:
            session.close()

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# ─── Download cleaned output ───────────────────────────────────────────────────

@router.get("/api/v1/jobs/{job_id}/files/{file_id}/download")
async def download_file_output(request: Request, job_id: str, file_id: str) -> StreamingResponse:
    session = get_db_session(request.app.state.db_session_factory)
    try:
        _, jf = _get_job_and_file(session, job_id, file_id)
        cleaned_preview = (jf.analysis or {}).get("cleaned_preview")
        if not cleaned_preview:
            raise HTTPException(status_code=404, detail="No cleaned output — run execute first.")
        filename_stem = Path(jf.filename).stem
    finally:
        session.close()

    settings = request.app.state.settings
    sandbox_root = Path(settings.local_storage_dir) / "sandbox"
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
            headers={"Content-Disposition": f'attachment; filename="{filename_stem}_cleaned.csv"'},
        )

    def file_streamer():
        with open(output_file, "rb") as f:
            while chunk := f.read(65536):
                yield chunk

    return StreamingResponse(
        file_streamer(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename_stem}_cleaned.csv"'},
    )
