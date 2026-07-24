"""Worker pool, event bus, live logs."""

import threading
import time
from collections import deque
from queue import Queue

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

