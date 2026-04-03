import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from backend.app.parsers.detect import detect_file_type
from backend.app.core.config import get_settings
from backend.app.parsers.pdf import parse_pdf_with_ocr
from backend.app.parsers.spreadsheet import parse_spreadsheet
from backend.app.sandbox.session_manager import SessionManager

_session_manager = None
_step_updater: Optional[Callable[[str, str], None]] = None


def set_session_manager(manager: SessionManager) -> None:
    global _session_manager
    _session_manager = manager


def set_step_updater(updater: Callable[[str, str], None]) -> None:
    global _step_updater
    _step_updater = updater


def demo_sleep_task(payload: Dict[str, Any]) -> Dict[str, Any]:
    duration = float(payload.get("seconds", 2))
    time.sleep(max(0.0, duration))
    return {"slept_seconds": duration}


def process_file_task(payload: Dict[str, Any]) -> Dict[str, Any]:
    storage_path = payload.get("storage_path", "")
    job_id = payload.get("job_id", "")
    logger = logging.getLogger(__name__)
    step = "queued"
    logger.info("process_file_task: step=%s path=%s", step, storage_path)
    if _step_updater and job_id:
        _step_updater(job_id, step)
    time.sleep(0.5)
    step = "detect_type"
    logger.info("process_file_task: step=%s", step)
    if _step_updater and job_id:
        _step_updater(job_id, step)
    file_type = detect_file_type(Path(storage_path))
    preview = None
    if file_type.kind in {"csv", "excel"}:
        step = "parse_spreadsheet"
        logger.info("process_file_task: step=%s", step)
        if _step_updater and job_id:
            _step_updater(job_id, step)
        preview = parse_spreadsheet(Path(storage_path))
    if file_type.kind == "pdf":
        settings = get_settings()
        step = "parse_pdf"
        logger.info("process_file_task: step=%s", step)
        if _step_updater and job_id:
            _step_updater(job_id, step)
        preview = parse_pdf_with_ocr(Path(storage_path), poppler_path=settings.poppler_path)
    if not _session_manager:
        step = "complete_no_sandbox"
        logger.info("process_file_task: step=%s", step)
        if _step_updater and job_id:
            _step_updater(job_id, step)
        return {
            "processed": True,
            "storage_path": storage_path,
            "file_type": file_type.kind,
            "preview": preview.__dict__ if preview else None,
            "step": step,
        }
    session = _session_manager.create_session()
    try:
        data_path = Path(storage_path)
        if data_path.exists():
            step = "upload_to_sandbox"
            logger.info("process_file_task: step=%s", step)
            if _step_updater and job_id:
                _step_updater(job_id, step)
            _session_manager.upload_file(session, data_path.name, data_path.read_bytes())
        step = "run_sandbox"
        logger.info("process_file_task: step=%s file=%s", step, data_path.name)
        if _step_updater and job_id:
            _step_updater(job_id, step)
        logs = _session_manager.execute_code(
            session,
            "print('processing ok')",
            timeout_seconds=60,
        )
        step = "complete_sandbox"
        logger.info("process_file_task: step=%s", step)
        if _step_updater and job_id:
            _step_updater(job_id, step)
        return {
            "processed": True,
            "storage_path": storage_path,
            "file_type": file_type.kind,
            "preview": preview.__dict__ if preview else None,
            "sandbox_log": logs,
            "step": step,
        }
    finally:
        _session_manager.close_session(session)
