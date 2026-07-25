"""
Worker pool, event bus, live logs.

Ported structurally from TubeForge. The difference is that a job here wraps
a Python callable rather than a subprocess, so cancellation is cooperative:
the callable is handed a `ctl` object and is expected to check `ctl.cancelled`
between iterations. Bootstrap, permutation and harvest loops all do.
"""

import json
import threading
import time
import traceback
import uuid
from collections import deque
from queue import Queue, Empty

from .config import get
from . import db

LOG_RING = 3000
BUS_RING = 300


class EventBus:
    def __init__(self):
        self._subs = []
        self._recent = deque(maxlen=BUS_RING)
        self._lock = threading.Lock()

    def publish(self, event):
        event = dict(event)
        event.setdefault("t", time.time())
        with self._lock:
            self._recent.append(event)
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(event)
            except Exception:
                pass

    def subscribe(self, replay=40):
        q = Queue(maxsize=1000)
        with self._lock:
            for e in list(self._recent)[-replay:]:
                try:
                    q.put_nowait(e)
                except Exception:
                    break
            self._subs.append(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)


BUS = EventBus()


class Cancelled(Exception):
    pass


class Ctl:
    """Handed to the job body. Progress and logging go through here."""

    def __init__(self, job):
        self.job = job

    @property
    def cancelled(self):
        return self.job.cancel_flag.is_set()

    def check(self):
        if self.cancelled:
            raise Cancelled()

    def log(self, line):
        self.job.log(line)

    def progress(self, pct, note=None):
        self.job.set_progress(pct, note)


class Job:
    def __init__(self, kind, title, fn, spec=None, meta=None, project_id=None,
                 attempt_id=None, on_finish=None):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.title = title
        self.fn = fn
        # Called with the job once its terminal state is persisted, so anything
        # derived from the job can never report "finished" ahead of the job.
        self.on_finish = on_finish
        self.spec = spec or {}
        self.meta = meta or {}
        self.project_id = project_id or self.meta.get("project_id") or self.spec.get("project")
        self.attempt_id = attempt_id or self.meta.get("attempt_id")
        self.status = "queued"
        self.progress = 0.0
        self.note = ""
        self.lines = deque(maxlen=LOG_RING)
        self.result = None
        self.error = None
        self.started_at = None
        self.ended_at = None
        self.cancel_flag = threading.Event()
        self._lock = threading.Lock()

    def _persist(self, event_type=None, payload=None):
        try:
            db.exec_(
                "UPDATE job SET status=?,progress=?,note=?,error=?,result=?,started_at=?,ended_at=?,"
                "cancel_requested_at=? WHERE id=?",
                (self.status, self.progress, self.note, self.error,
                 json.dumps(self.result, default=str) if self.result is not None else None,
                 self.started_at,
                 self.ended_at, time.time() if self.cancel_flag.is_set() else None, self.id),
            )
            if event_type and self.project_id:
                db.exec_(
                    "INSERT INTO job_event(project_id,job_id,type,payload,created_at) "
                    "VALUES(?,?,?,?,?)",
                    (self.project_id, self.id, event_type,
                     json.dumps(payload or {}, default=str), time.time()),
                )
        except Exception:
            # Persistence failures must not kill a running scientific callable;
            # the finalizer records the failure where possible.
            pass

    def log(self, line):
        with self._lock:
            self.lines.append(str(line))
        BUS.publish({"type": "log", "job": self.id, "line": str(line)})
        self._persist("log", {"line": str(line)[-4000:]})

    def set_progress(self, pct, note=None):
        self.progress = max(0.0, min(100.0, float(pct)))
        if note is not None:
            self.note = note
        BUS.publish({"type": "progress", "job": self.id,
                     "project_id": self.project_id,
                     "progress": self.progress, "note": self.note})
        self._persist("progress", {"progress": self.progress, "note": self.note})

    def set_status(self, status):
        self.status = status
        BUS.publish({"type": "status", "job": self.id, "status": status,
                     "project_id": self.project_id,
                     "title": self.title, "kind": self.kind})
        self._persist("status", {"status": status, "title": self.title})

    def cancel(self):
        self.cancel_flag.set()
        self.log("Cancellation requested.")
        self._persist("cancel_requested", {})

    def to_dict(self, with_log=False):
        d = {
            "id": self.id, "kind": self.kind, "title": self.title,
            "status": self.status, "progress": self.progress, "note": self.note,
            "error": self.error, "started_at": self.started_at,
            "ended_at": self.ended_at, "meta": self.meta,
            "project_id": self.project_id, "attempt_id": self.attempt_id,
            "has_result": self.result is not None,
        }
        if with_log:
            d["log"] = list(self.lines)
            d["result"] = self.result
        return d


class JobManager:
    def __init__(self):
        self.jobs = {}
        self.order = deque()
        self.queue = Queue()
        self._lock = threading.Lock()
        self._workers = []

    def _ensure_workers(self):
        want = max(1, int(get("max_concurrent_jobs", 2)))
        while len(self._workers) < want:
            t = threading.Thread(target=self._worker, daemon=True)
            t.start()
            self._workers.append(t)

    def _worker(self):
        while True:
            try:
                job = self.queue.get(timeout=1)
            except Empty:
                continue
            try:
                if job.cancel_flag.is_set():
                    job.set_status("cancelled")
                else:
                    job.started_at = time.time()
                    job.set_status("running")
                    try:
                        job.result = job.fn(Ctl(job))
                        job.set_progress(100)
                        job.set_status("done")
                    except Cancelled:
                        job.set_status("cancelled")
                    except Exception as exc:
                        job.error = f"{type(exc).__name__}: {exc}"
                        job.log(traceback.format_exc().rstrip())
                        job.set_status("failed")
            finally:
                job.ended_at = time.time()
                job._persist("finished", {"status": job.status, "title": job.title})
                if job.on_finish is not None:
                    try:
                        job.on_finish(job)
                    except Exception:
                        job.log(traceback.format_exc().rstrip())
                BUS.publish({"type": "finished", "job": job.id,
                             "project_id": job.project_id,
                             "status": job.status, "title": job.title})
                self.queue.task_done()
                with self._lock:
                    self._prune_history()

    def _prune_history(self):
        limit = max(1, int(get("keep_job_history", 500)))
        finished = [jid for jid in self.order
                    if jid in self.jobs and self.jobs[jid].status not in ("queued", "running")]
        excess = max(0, len(finished) - limit)
        if not excess:
            return
        remove = set(finished[:excess])
        self.order = deque(jid for jid in self.order if jid not in remove)
        for jid in remove:
            self.jobs.pop(jid, None)

    def submit(self, kind, title, fn, spec=None, meta=None, project_id=None,
               attempt_id=None, on_finish=None):
        job = Job(kind, title, fn, spec, meta, project_id, attempt_id, on_finish)
        try:
            db.insert("job", {
                "id": job.id, "project_id": job.project_id,
                "attempt_id": job.attempt_id, "kind": kind, "title": title,
                "status": "queued", "spec": job.spec, "result": None,
                "progress": 0.0, "note": "", "error": None,
                "created_at": time.time(), "started_at": None, "ended_at": None,
            })
        except Exception:
            # Creating a durable job is mandatory once the new schema exists.
            # Older embedded callers may not have initialized a database yet.
            try:
                has_table = db.one("SELECT name FROM sqlite_master WHERE type='table' AND name='job'")
            except Exception:
                has_table = None
            if has_table:
                raise
        with self._lock:
            self.jobs[job.id] = job
            self.order.append(job.id)
            self._prune_history()
            self._ensure_workers()
        job.set_status("queued")
        self.queue.put(job)
        return job

    def get(self, jid):
        return self.jobs.get(jid)

    def list(self, project_id=None):
        with self._lock:
            ids = list(self.order)
        live = [self.jobs[i].to_dict() for i in reversed(ids) if i in self.jobs]
        if project_id is not None:
            live = [j for j in live if j.get("project_id") == project_id]
        return live

    def recover_interrupted(self):
        """A restart cannot resume Python callables; mark that fact honestly."""
        now = time.time()
        try:
            rows = db.query("SELECT id,project_id FROM job WHERE status IN ('queued','running','validating','cancel_requested')")
            for row in rows:
                db.exec_("UPDATE job SET status='interrupted',ended_at=?,"
                         "error=COALESCE(error,'Application restarted before completion.') WHERE id=?",
                         (now, row["id"]))
                if row.get("project_id"):
                    db.exec_(
                        "INSERT INTO job_event(project_id,job_id,type,payload,created_at) "
                        "VALUES(?,?,?,?,?)",
                        (row["project_id"], row["id"], "interrupted",
                         json.dumps({"reason": "application_restart"}), now),
                    )
        except Exception:
            return

    def stored(self, jid, project_id=None):
        where = "id=?" + (" AND project_id=?" if project_id is not None else "")
        args = (jid, project_id) if project_id is not None else (jid,)
        row = db.one(f"SELECT * FROM job WHERE {where}", args)
        if row:
            row["spec"] = db.json_value(row.get("spec"), {})
            row["result"] = db.json_value(row.get("result"), None)
        return row

    def cancel_all(self):
        for j in self.jobs.values():
            if j.status in ("queued", "running"):
                j.cancel()

    def clear_finished(self):
        with self._lock:
            keep = [i for i in self.order
                    if i in self.jobs and self.jobs[i].status in ("queued", "running")]
            for i in list(self.jobs):
                if i not in keep:
                    self.jobs.pop(i, None)
            self.order = deque(keep)


JOBS = JobManager()


def sse(event):
    return f"data: {json.dumps(event, default=str)}\n\n"
