from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import docker

from backend.app.core.config import Settings
from backend.app.security.audit import write_audit_log
from backend.app.security.static_analyzer import StaticCodeAnalyzer


@dataclass
class SessionInfo:
    session_id: str
    workspace_dir: Path
    container_id: Optional[str] = None


class SessionManager:
    def __init__(self, settings: Settings) -> None:
        self._client = docker.from_env()
        self._settings = settings
        self._root = settings.local_storage_dir / "sandbox"
        self._root.mkdir(parents=True, exist_ok=True)
        self._audit_dir = settings.local_storage_dir / "audit"
        self._analyzer = StaticCodeAnalyzer(
            safe_imports={"pandas", "numpy", "math", "datetime", "json", "re"}
        )

    def create_session(self) -> SessionInfo:
        session_id = uuid.uuid4().hex
        workspace_dir = self._root / session_id
        workspace_dir.mkdir(parents=True, exist_ok=True)
        return SessionInfo(session_id=session_id, workspace_dir=workspace_dir)

    def upload_file(self, session: SessionInfo, filename: str, content: bytes) -> Path:
        target = session.workspace_dir / filename
        target.write_bytes(content)
        return target

    def execute_code(self, session: SessionInfo, code: str, timeout_seconds: int = 120) -> str:
        analysis = self._analyzer.analyze(code)
        if not analysis.ok:
            raise RuntimeError(f"Static analysis failed: {analysis.message}")
        job_id = None
        if session.workspace_dir.name:
            job_id = session.workspace_dir.name
        write_audit_log(
            self._audit_dir, code=code, session_id=session.session_id, job_id=job_id
        )
        wrapped_code = self._wrap_with_timeout(code, timeout_seconds)
        script_path = session.workspace_dir / "script.py"
        script_path.write_text(wrapped_code, encoding="utf-8")

        container = self._client.containers.run(
            self._settings.sandbox_image,
            command=["python", "/sandbox/data/script.py"],
            detach=True,
            network_disabled=True,
            mem_limit=f"{self._settings.sandbox_memory_mb}m",
            cpu_quota=int(self._settings.sandbox_cpu * 100000),
            volumes={
                str(session.workspace_dir): {
                    "bind": "/sandbox/data",
                    "mode": "rw",
                }
            },
        )
        session.container_id = container.id
        try:
            result = container.wait(timeout=timeout_seconds)
            logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="ignore")
            if result.get("StatusCode", 1) != 0:
                raise RuntimeError(f"Sandbox execution failed: {logs}")
            return logs
        finally:
            container.remove(force=True)
            session.container_id = None

    def close_session(self, session: SessionInfo) -> None:
        if session.container_id:
            try:
                container = self._client.containers.get(session.container_id)
                container.remove(force=True)
            except Exception:
                pass

    @staticmethod
    def _wrap_with_timeout(code: str, timeout_seconds: int) -> str:
        if timeout_seconds <= 0:
            return code
        prelude = (
            "import signal\n"
            "def _timeout_handler(signum, frame):\n"
            "    raise TimeoutError('Sandbox timeout')\n"
            "signal.signal(signal.SIGALRM, _timeout_handler)\n"
            f"signal.alarm({timeout_seconds})\n"
        )
        return f"{prelude}\n{code}\n"
