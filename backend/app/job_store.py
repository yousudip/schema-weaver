from __future__ import annotations

from dataclasses import asdict, dataclass
from threading import Lock
from typing import Dict, Optional


@dataclass
class JobRecord:
    job_id: str
    filename: str
    storage_path: str


class JobStore:
    def __init__(self) -> None:
        self._jobs: Dict[str, JobRecord] = {}
        self._lock = Lock()

    def create_job(self, job: JobRecord) -> None:
        with self._lock:
            self._jobs[job.job_id] = job

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        with self._lock:
            return self._jobs.get(job_id)

    def get_job_snapshot(self, job_id: str) -> Optional[Dict[str, str]]:
        job = self.get_job(job_id)
        return asdict(job) if job else None
