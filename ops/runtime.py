"""Desk worker lifecycle.

Stop is cooperative. In-flight work may finish until the deadline. A task
that is still running at the deadline is not recorded as complete.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from ops.files import update_json


def _state_path():
    root = Path(os.environ.get("AUREON_DATA") or "data")
    return root / "worker" / "runtime.json"


class DeskRuntime:
    def __init__(self, deadline_s=5):
        self.deadline_s = float(deadline_s)
        self._stop = threading.Event()
        self._cv = threading.Condition()
        self._inflight = 0
        self._names = {}
        self.phase = "created"
        self.last_result = None

    def running(self):
        return not self._stop.is_set() and self.phase == "running"

    def tick_start(self, name):
        with self._cv:
            if self._stop.is_set() or self.phase != "running":
                return False
            self._inflight += 1
            self._names[name] = self._names.get(name, 0) + 1
            return True

    def tick_end(self, name, completed):
        with self._cv:
            self._inflight = max(0, self._inflight - 1)
            count = self._names.get(name, 1) - 1
            if count <= 0:
                self._names.pop(name, None)
            else:
                self._names[name] = count
            self.last_result = {"name": name, "completed": bool(completed)}
            self._cv.notify_all()
        self._task_result(name, bool(completed))

    def wait(self, seconds):
        return self._stop.wait(timeout=float(seconds))

    def mark_started(self):
        previous = self.read_state()
        self._stop.clear()
        self.phase = "running"
        if previous.get("phase") in {"stopped", "interrupted", "recovered"}:
            self._record(
                "worker_restarted",
                "The desk started again. Unfinished work was not marked complete and was not replayed as a success.",
            )
        self._merge_state({
            "phase": "running",
            "inflight": 0,
            "completed": None,
            "accepting": True,
            "failed_tasks": [],
            "unfinished": [],
        })
        return {"started": True, "phase": self.phase}

    def shutdown(self, deadline_s=None):
        if self.phase == "created":
            return {"ok": True, "completed": False, "phase": "created", "reason": "not_started", "inflight": 0}
        deadline = self.deadline_s if deadline_s is None else float(deadline_s)
        with self._cv:
            self.phase = "stopping"
            self._stop.set()
            finished = self._cv.wait_for(lambda: self._inflight == 0, timeout=max(0.0, deadline))
            inflight = self._inflight
            unfinished = sorted(self._names)
        state = self.read_state()
        tasks = dict(state.get("tasks") or {})
        failed = list(state.get("failed_tasks") or [])
        for name in unfinished:
            if tasks.get(name) is not False:
                tasks[name] = False
            if name not in failed:
                failed.append(name)
        if not finished:
            self.phase = "interrupted"
            self._merge_state({
                "phase": "interrupted",
                "inflight": inflight,
                "unfinished": unfinished,
                "completed": False,
                "accepting": False,
                "tasks": tasks,
                "failed_tasks": failed,
            })
            self._record(
                "work_interrupted",
                "Shutdown deadline passed before in-flight work finished. The task was not recorded as complete.",
            )
            return {
                "ok": False,
                "completed": False,
                "phase": "interrupted",
                "inflight": inflight,
                "unfinished": unfinished,
                "tasks": tasks,
                "reason": "deadline",
            }
        if failed:
            self.phase = "interrupted"
            self._merge_state({
                "phase": "interrupted",
                "inflight": 0,
                "completed": False,
                "accepting": False,
                "tasks": tasks,
                "failed_tasks": failed,
            })
            self._record(
                "work_interrupted",
                "A task ended without completing. It was not recorded as a success.",
            )
            return {"ok": False, "completed": False, "phase": "interrupted", "inflight": 0, "tasks": tasks, "reason": "task_failed"}
        self.phase = "stopped"
        self._merge_state({"phase": "stopped", "inflight": 0, "completed": True, "accepting": False, "tasks": tasks, "failed_tasks": []})
        self._record("worker_stopped", "Shutdown let in-flight work finish. No new work was accepted after the stop.")
        return {"ok": True, "completed": True, "phase": "stopped", "inflight": 0, "tasks": tasks}

    def recover(self):
        state = self.read_state()
        unfinished = state.get("unfinished") or []
        failed = state.get("failed_tasks") or []
        if state.get("phase") == "interrupted" or unfinished or (state.get("inflight") and state.get("completed") is False):
            self._record(
                "work_interrupted",
                "Restart found unfinished work. It was not marked complete and it was not replayed as a success.",
            )
            tasks = dict(state.get("tasks") or {})
            for name in list(unfinished) + list(failed):
                tasks[name] = False
            self._merge_state({"phase": "recovered", "inflight": 0, "completed": False, "accepting": False, "tasks": tasks, "failed_tasks": failed, "unfinished": unfinished})
            return {"recovered": True, "completed": False, "reason": "unfinished", "tasks": tasks}
        return {"recovered": state.get("phase") in {"stopped", "recovered"}, "completed": state.get("completed") is True}

    def read_state(self):
        path = _state_path()
        if not path.is_file():
            return {}
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return body if isinstance(body, dict) else {}

    def _write_state(self, body):
        try:
            update_json(_state_path(), lambda _current: dict(body), dict(body))
        except Exception:
            return None
        return body

    def _merge_state(self, patch):
        def apply(current):
            base = dict(current) if isinstance(current, dict) else {}
            base.update(patch)
            return base

        try:
            return update_json(_state_path(), apply, {})
        except Exception:
            return None

    def _task_result(self, name, completed):
        def apply(current):
            base = dict(current) if isinstance(current, dict) else {}
            tasks = dict(base.get("tasks") or {})
            tasks[name] = bool(completed)
            base["tasks"] = tasks
            if not completed:
                failed = list(base.get("failed_tasks") or [])
                if name not in failed:
                    failed.append(name)
                base["failed_tasks"] = failed
            return base

        try:
            update_json(_state_path(), apply, {})
        except Exception:
            return None

    def _record(self, event_type, note):
        try:
            from ops.activity import record

            record(event_type, component="worker", entity="desk", detail={"note": note, "phase": self.phase})
        except Exception:
            return None
