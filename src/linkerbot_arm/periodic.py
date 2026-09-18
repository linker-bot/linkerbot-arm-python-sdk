"""One event-driven periodic scheduler per arm connection.

Query tasks retain nonblocking relay requests while other joints continue.
Reporting motors register no query tasks; heartbeat motors use the same clock.
"""

import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from linkerbot_arm.exceptions import ValidationError

logger = logging.getLogger(__name__)
_creation_lock = threading.Lock()


@dataclass
class PeriodicTask:
    interval_s: float
    begin: Callable
    consume: Callable | None = None
    pending: object | None = None
    deadline: float = 0.0
    next_due: float = 0.0

    def __post_init__(self):
        if (
            isinstance(self.interval_s, bool)
            or not isinstance(self.interval_s, (float, int))
            or not math.isfinite(self.interval_s)
            or self.interval_s <= 0
        ):
            raise ValidationError("poll interval must be finite and positive")


class PeriodicScheduler:
    def __init__(self):
        self._condition = threading.Condition(threading.RLock())
        self._tasks = {}
        self._thread = None
        self._lifecycle_lock = threading.RLock()
        self._closed = False

    def wake(self):
        with self._condition:
            self._condition.notify_all()

    def replace(self, owner, tasks):
        with self._lifecycle_lock, self._condition:
            if self._closed:
                raise RuntimeError("arm periodic scheduler is closed")
            self._remove(owner)
            if tasks:
                self._tasks[owner] = tasks
            if self._tasks and (self._thread is None or not self._thread.is_alive()):
                self._thread = threading.Thread(
                    target=self._run, daemon=True, name="LinkerbotArm.periodic"
                )
                self._thread.start()
            self._condition.notify_all()

    def _remove(self, owner):
        for task in self._tasks.pop(owner, ()):
            if task.pending is not None:
                task.pending.cancel()

    def remove(self, owner):
        # Serialize a last-owner stop with a new start, without holding the
        # condition while joining the worker that needs it in order to exit.
        with self._lifecycle_lock:
            with self._condition:
                self._remove(owner)
                self._condition.notify_all()
                thread = self._thread if not self._tasks else None
            self._join(thread)

    def close(self):
        with self._lifecycle_lock:
            with self._condition:
                self._closed = True
                for owner in tuple(self._tasks):
                    self._remove(owner)
                self._condition.notify_all()
                thread = self._thread
            self._join(thread)

    @staticmethod
    def _join(thread):
        if thread is not None and thread is not threading.current_thread():
            thread.join(2)
            if thread.is_alive():
                raise RuntimeError("arm periodic worker did not stop")

    def _run(self):
        with self._condition:
            while self._tasks:
                now = time.monotonic()
                nearest = now + 1.0
                for tasks in tuple(self._tasks.values()):
                    for task in tasks:
                        try:
                            if task.pending is not None:
                                if task.pending.done:
                                    value = task.pending.result()
                                    task.pending = None
                                    task.consume(value)
                                    task.next_due = time.monotonic() + task.interval_s
                                elif now >= task.deadline:
                                    task.pending.cancel()
                                    task.pending = None
                                    task.next_due = now + task.interval_s
                                else:
                                    nearest = min(nearest, task.deadline)
                                    continue
                            if now >= task.next_due:
                                # No catch-up bursts after a late wake or timeout.
                                task.next_due = now + task.interval_s
                                task.pending = task.begin(self.wake)
                                task.deadline = now + task.interval_s
                                if task.pending is not None and task.pending.done:
                                    value = task.pending.result()
                                    task.pending = None
                                    task.consume(value)
                                    task.next_due = time.monotonic() + task.interval_s
                            nearest = min(nearest, task.next_due)
                        except Exception:
                            if task.pending is not None:
                                task.pending.cancel()
                                task.pending = None
                            task.next_due = now + task.interval_s
                            nearest = min(nearest, task.next_due)
                            logger.exception("Arm periodic task failed")
                self._condition.wait(max(0.0, nearest - time.monotonic()))
            self._thread = None


def scheduler_for(dispatcher):
    with _creation_lock:
        scheduler = getattr(dispatcher, "_arm_periodic_scheduler", None)
        if scheduler is None:
            scheduler = PeriodicScheduler()
            dispatcher._arm_periodic_scheduler = scheduler
        return scheduler
