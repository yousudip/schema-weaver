from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional


def write_audit_log(
    log_dir: Path, code: str, session_id: str, job_id: Optional[str] = None
) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "audit.log"
    code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
    timestamp = datetime.utcnow().isoformat()
    job_value = job_id or ""
    line = f"{timestamp}\t{session_id}\t{job_value}\t{code_hash}\n"
    log_path.open("a", encoding="utf-8").write(line)
