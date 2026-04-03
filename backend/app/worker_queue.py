from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from queue import Queue, Empty
import logging
from threading import Event, Lock, Thread
from typing import Any, Callable, Dict, Optional
from uuid import uuid4


class TaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


TaskHandler = Callable[[Dict[str, Any]], Any]
StatusCallback = Callable[["Task"], None]


@dataclass
class Task:
    task_id: str
    task_type: str
    payload: Dict[str, Any]
    status: TaskStatus = TaskStatus.pending
    result: Optional[Any] = None
    error: Optional[str] = None


@dataclass
class QueueConfig:
    poll_interval_seconds: float = 0.1
    max_queue_size: int = 0


class LocalWorkerQueue:
    """
    Local in-memory worker queue.
    Designed as a minimal interface that can be swapped later.
    """

    def __init__(
        self,
        config: Optional[QueueConfig] = None,
        status_callback: Optional[StatusCallback] = None,
    ) -> None:
        self._config = config or QueueConfig()
        self._queue: Queue[Task] = Queue(maxsize=self._config.max_queue_size)
        self._handlers: Dict[str, TaskHandler] = {}
        self._tasks: Dict[str, Task] = {}
        self._tasks_lock = Lock()
        self._stop_event = Event()
        self._worker: Optional[Thread] = None
        self._status_callback = status_callback

    def register_handler(self, task_type: str, handler: TaskHandler) -> None:
        self._handlers[task_type] = handler

    def submit(
        self, task_type: str, payload: Dict[str, Any], task_id: Optional[str] = None
    ) -> str:
        task_id = task_id or uuid4().hex
        task = Task(task_id=task_id, task_type=task_type, payload=payload)
        with self._tasks_lock:
            self._tasks[task_id] = task
        self._queue.put(task)
        self._notify_status(task)
        return task_id

    def get_task(self, task_id: str) -> Optional[Task]:
        with self._tasks_lock:
            return self._tasks.get(task_id)

    def get_task_snapshot(self, task_id: str) -> Optional[Dict[str, Any]]:
        task = self.get_task(task_id)
        if not task:
            return None
        return {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "status": task.status,
            "result": task.result,
            "error": task.error,
        }

    def get_task_status(self, task_id: str) -> Optional[TaskStatus]:
        task = self.get_task(task_id)
        return task.status if task else None

    def start(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._stop_event.clear()
        self._worker = Thread(target=self._run, name="local-worker-queue", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._worker:
            self._worker.join(timeout=2)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                task = self._queue.get(timeout=self._config.poll_interval_seconds)
            except Empty:
                continue
            handler = self._handlers.get(task.task_type)
            if not handler:
                task.status = TaskStatus.failed
                task.error = f"No handler registered for task type '{task.task_type}'."
                self._notify_status(task)
                continue
            task.status = TaskStatus.running
            self._notify_status(task)
            try:
                task.result = handler(task.payload)
                task.status = TaskStatus.succeeded
            except Exception as exc:  # pragma: no cover - passthrough errors
                task.status = TaskStatus.failed
                task.error = str(exc)
            self._notify_status(task)

    def _notify_status(self, task: Task) -> None:
        if not self._status_callback:
            return
        try:
            self._status_callback(task)
        except Exception as exc:
            logging.getLogger(__name__).exception(
                "status_callback failed for task %s: %s", task.task_id, exc
            )
            return
