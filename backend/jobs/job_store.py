"""任务状态仓库：线程安全的内存任务表。

后端的工作线程负责写入，FastAPI 的请求线程负责读取，
因此所有操作都用 Lock 保护。
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Optional

from shared.schemas import FailureItem, JobInfo, JobStatus

logger = logging.getLogger(__name__)

# 超过该时间且已结束的任务会被清理，避免长时间运行后内存无限增长
FINISHED_TTL_SECONDS = 30 * 60
MAX_HISTORY = 50


class JobStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, JobInfo] = {}
        self._finished_at: dict[str, float] = {}
        self._cancel_flags: set[str] = set()

    # ------------------------------------------------------------------ 生命周期
    def create(self, folder: str, prompt: str) -> JobInfo:
        job_id = uuid.uuid4().hex[:12]
        job = JobInfo(job_id=job_id, status=JobStatus.PENDING)
        with self._lock:
            self._jobs[job_id] = job
        logger.info("创建任务 %s：folder=%s prompt=%s", job_id, folder, prompt)
        self._cleanup()
        return job

    def get(self, job_id: str) -> Optional[JobInfo]:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.model_copy(deep=True) if job else None

    def exists(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._jobs

    # ------------------------------------------------------------------ 更新
    def update(self, job_id: str, **fields) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for key, value in fields.items():
                setattr(job, key, value)
            if job.status in (
                JobStatus.DONE,
                JobStatus.FAILED,
                JobStatus.CANCELED,
            ):
                self._finished_at.setdefault(job_id, time.time())

    def add_result(self, job_id: str, filename: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.results.append(filename)
                job.succeeded = len(job.results)

    def add_failure(self, job_id: str, filename: str, error: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.failures.append(FailureItem(filename=filename, error=error))
            job.failed = len(job.failures)

    # ------------------------------------------------------------------ 取消
    def request_cancel(self, job_id: str) -> None:
        with self._lock:
            self._cancel_flags.add(job_id)

    def is_canceled(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancel_flags

    def clear_cancel(self, job_id: str) -> None:
        with self._lock:
            self._cancel_flags.discard(job_id)

    # ------------------------------------------------------------------ 清理
    def _cleanup(self) -> None:
        """移除过期任务与超出上限的历史任务，防止内存泄漏。"""
        with self._lock:
            now = time.time()
            expired = [
                job_id
                for job_id, ts in self._finished_at.items()
                if now - ts > FINISHED_TTL_SECONDS
            ]
            for job_id in expired:
                self._jobs.pop(job_id, None)
                self._finished_at.pop(job_id, None)
                self._cancel_flags.discard(job_id)

            finished = sorted(self._finished_at, key=lambda k: self._finished_at[k])
            for job_id in finished[: max(0, len(finished) - MAX_HISTORY)]:
                self._jobs.pop(job_id, None)
                self._finished_at.pop(job_id, None)
                self._cancel_flags.discard(job_id)


job_store = JobStore()
