"""Background job runner with two lanes.

`gpu`   : AI generation. Strictly one at a time so a 4 GB card is never shared.
`media` : ffmpeg work (export, quick tools). Runs alongside generation.
"""

from __future__ import annotations

import queue
import threading
import time
import traceback
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from .editor.media import FfmpegError, RenderCancelled

log = logging.getLogger("ltxps.jobs")

Lane = str


class JobCancelled(Exception):
    pass


class UserFacingError(Exception):
    """An error whose message is safe and useful to show in the UI as-is."""


@dataclass
class Job:
    id: str
    kind: str
    title: str
    lane: Lane
    status: str = "queued"  # queued | running | done | error | cancelled
    progress: float = 0.0
    phase: str = "Waiting in queue"
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    created: float = field(default_factory=time.time)
    started: float = 0.0
    finished: float = 0.0
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    expected: float = 0.0  # seconds the estimate promised (0 = no estimate)
    note: str = ""  # why a job was stopped or what the person should know

    def to_json(self) -> dict[str, Any]:
        now = time.time()
        elapsed = (self.finished or now) - self.started if self.started else 0.0
        eta = None
        if self.status == "running" and self.progress > 0.03:
            eta = max(0.0, elapsed / self.progress - elapsed)
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "lane": self.lane,
            "status": self.status,
            "progress": round(self.progress, 4),
            "phase": self.phase,
            "result": self.result,
            "error": self.error,
            "created": self.created,
            "elapsed": round(elapsed, 1),
            "eta": round(eta, 1) if eta is not None else None,
            "expected": round(self.expected),
            "note": self.note,
        }


class JobContext:
    def __init__(self, job: Job):
        self.job = job

    @property
    def cancel(self) -> threading.Event:
        return self.job.cancel

    def update(self, progress: float | None = None, phase: str | None = None) -> None:
        if progress is not None:
            self.job.progress = max(0.0, min(1.0, progress))
        if phase is not None:
            self.job.phase = phase

    def check(self) -> None:
        if self.job.cancel.is_set():
            raise JobCancelled()


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._queues: dict[Lane, queue.Queue[tuple[Job, Callable[[JobContext], dict[str, Any]]]]] = {}
        self._counter = 0
        for lane in ("gpu", "media"):
            q: queue.Queue = queue.Queue()
            self._queues[lane] = q
            threading.Thread(target=self._worker, args=(q,), daemon=True, name=f"jobs-{lane}").start()

    def submit(self, kind: str, title: str, fn: Callable[[JobContext], dict[str, Any]], lane: Lane = "media") -> Job:
        with self._lock:
            self._counter += 1
            job = Job(id=f"j{self._counter}-{int(time.time())}", kind=kind, title=title, lane=lane)
            self._jobs[job.id] = job
            self._trim()
        self._queues[lane].put((job, fn))
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created, reverse=True)

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job or job.status in ("done", "error", "cancelled"):
            return False
        job.cancel.set()
        if job.status == "queued":
            job.status = "cancelled"
            job.phase = "Cancelled"
            job.finished = time.time()
        return True

    def busy(self, lane: Lane) -> bool:
        return any(j.lane == lane and j.status in ("queued", "running") for j in self.list())

    def _trim(self) -> None:
        finished = [j for j in self._jobs.values() if j.status in ("done", "error", "cancelled")]
        finished.sort(key=lambda j: j.finished)
        for j in finished[:-40]:
            self._jobs.pop(j.id, None)

    def _worker(self, q: "queue.Queue[tuple[Job, Callable[[JobContext], dict[str, Any]]]]") -> None:
        while True:
            job, fn = q.get()
            if job.status == "cancelled":
                continue
            job.status = "running"
            job.phase = "Starting"
            job.started = time.time()
            try:
                job.result = fn(JobContext(job)) or {}
                job.progress = 1.0
                job.status = "done"
                job.phase = "Done"
            except (JobCancelled, RenderCancelled):
                job.status = "cancelled"
                job.phase = "Cancelled"
            except (UserFacingError, FfmpegError) as exc:
                job.status = "error"
                job.error = str(exc)
                job.phase = "Failed"
                log.warning("job %s failed: %s", job.id, exc)
            except Exception as exc:  # noqa: BLE001 - last line of defence for a worker thread
                job.status = "error"
                job.error = f"{exc.__class__.__name__}: {exc}" if str(exc) else exc.__class__.__name__
                job.phase = "Failed"
                log.error("job %s crashed:\n%s", job.id, traceback.format_exc())
            finally:
                job.finished = time.time()
