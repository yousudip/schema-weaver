from typing import Any, Dict
from uuid import uuid4

from fastapi import APIRouter, Request
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
