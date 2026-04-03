import logging
import math

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.jobs import router as jobs_router
from backend.app.api.routes.stream import router as stream_router
from backend.app.api.routes.tasks import router as tasks_router
from backend.app.core.config import get_settings
from backend.app.core.llm_client import create_azure_openai_client
from sqlalchemy import select, text

from backend.app.db import (
    check_db_connection,
    create_db_engine,
    create_session_factory,
    get_db_session,
)
from backend.app.db_models import Base, Job, Task as TaskModel
from backend.app.sandbox.session_manager import SessionManager
from backend.app.parsers.pdf import configure_ocr
from backend.app.tasks.handlers import (
    demo_sleep_task,
    process_file_task,
    set_session_manager,
    set_step_updater,
)
from backend.app.worker_queue import LocalWorkerQueue, TaskStatus, Task

_settings = get_settings()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

app = FastAPI(title="Gamified Data Consolidator API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, tags=["health"])
app.include_router(jobs_router, tags=["jobs"])
app.include_router(stream_router, tags=["stream"])
app.include_router(tasks_router, tags=["tasks"])


def _task_status_updater(session_factory, task: Task) -> None:
    logger = logging.getLogger(__name__)
    session = get_db_session(session_factory)
    try:
        task_row = (
            session.execute(select(TaskModel).where(TaskModel.id == task.task_id))
            .scalar_one_or_none()
        )
        if not task_row:
            task_row = TaskModel(
                id=task.task_id,
                job_id=task.payload.get("job_id"),
                task_type=task.task_type,
                status=task.status.value,
                result=None,
                error=None,
            )
            session.add(task_row)
        else:
            task_row.status = task.status.value
        job = session.execute(select(Job).where(Job.id == task.task_id)).scalar_one_or_none()
        if job:
            job.task_status = task.status.value
            if task.status == TaskStatus.running:
                job.status = "processing"
            elif task.status == TaskStatus.succeeded:
                job.status = "completed"
                job.result = _sanitize_json(task.result)
                job.error = None
            elif task.status == TaskStatus.failed:
                job.status = "failed"
                job.error = task.error
            elif task.status == TaskStatus.pending:
                job.status = "queued"
        if task.status in (TaskStatus.running, TaskStatus.succeeded, TaskStatus.failed):
            result = task.result or {}
            if isinstance(result, dict) and "step" in result:
                if job:
                    job.step = result.get("step")
        if task.status in (TaskStatus.succeeded, TaskStatus.failed):
            task_row.result = _sanitize_json(task.result)
            task_row.error = task.error
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.exception("Failed to persist task status: %s", exc)
        raise
    finally:
        session.close()


def _sanitize_json(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _sanitize_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_json(v) for v in value]
    return value


def _update_job_step(session_factory, job_id: str, step: str) -> None:
    session = get_db_session(session_factory)
    try:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()
        if not job:
            return
        job.step = step
        session.commit()
    finally:
        session.close()


@app.on_event("startup")
async def startup() -> None:
    settings = _settings
    settings.local_storage_dir.mkdir(parents=True, exist_ok=True)
    app.state.settings = settings
    engine = create_db_engine(settings)
    with engine.begin() as connection:
        try:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            logging.getLogger(__name__).info("pgvector extension enabled.")
        except Exception as vec_err:
            logging.getLogger(__name__).warning(
                "pgvector extension not available — semantic schema matching will be disabled. "
                "Install pgvector for PostgreSQL 17 to enable it. Error: %s", vec_err
            )
    # Create tables individually so a missing pgvector extension
    # doesn't block the jobs/tasks tables from being created.
    from backend.app.db_models import Job, Task as TaskModel, SchemaVector
    for table in [Job.__table__, TaskModel.__table__]:
        try:
            table.create(engine, checkfirst=True)
        except Exception as tbl_err:
            logging.getLogger(__name__).error("Failed to create table %s: %s", table.name, tbl_err)
    try:
        SchemaVector.__table__.create(engine, checkfirst=True)
    except Exception:
        logging.getLogger(__name__).warning(
            "schema_vectors table could not be created (pgvector missing) — "
            "embedding features disabled."
        )
    check_db_connection(engine)
    app.state.db_engine = engine
    app.state.db_session_factory = create_session_factory(engine)
    app.state.llm_client = create_azure_openai_client(settings)
    app.state.session_manager = SessionManager(settings)
    configure_ocr(settings)
    set_session_manager(app.state.session_manager)
    set_step_updater(
        lambda job_id, step: _update_job_step(app.state.db_session_factory, job_id, step)
    )
    queue = LocalWorkerQueue(
        status_callback=lambda task: _task_status_updater(app.state.db_session_factory, task)
    )
    queue.register_handler("demo_sleep", demo_sleep_task)
    queue.register_handler("process_file", process_file_task)
    queue.start()
    app.state.worker_queue = queue


@app.on_event("shutdown")
async def shutdown() -> None:
    queue = getattr(app.state, "worker_queue", None)
    if queue:
        queue.stop()


@app.get("/")
async def root() -> dict:
    return {"status": "ok"}
