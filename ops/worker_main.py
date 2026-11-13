"""The worker container. It does not serve customer HTTP.

Web imports this code only as a process entrypoint. Background loops stay
here so a web process with AUREON_DISABLE_WORKERS=1 never starts them.
"""

from __future__ import annotations

import os
import signal
import sys
import threading
import time


def request_stop(runtime):
    """Ask the loops to finish the current tick. Do not kill them."""
    runtime._stop.set()


def install_signals(runtime):
    def handler(_signum, _frame):
        request_stop(runtime)

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)
    return handler


def main():
    os.environ["AUREON_DISABLE_WORKERS"] = "1"
    os.environ["AUREON_ROLE"] = "worker"
    from ops.paths import data_root
    from ops.schema_guard import guard

    checked = guard(data_root(), apply=os.environ.get("AUREON_SCHEMA_APPLY", "1") != "0")
    if not checked.get("ok"):
        sys.stderr.write("schema guard refused: " + str(checked.get("action")) + "\n")
        return 2
    from ops.app import _digest_loop, _loop, _telegram_loop, desk_runtime
    from ops.worker_status import publish_patch

    desk_runtime.mark_started()
    install_signals(desk_runtime)
    threads = [
        threading.Thread(target=_loop, name="aureon-desk", daemon=True),
        threading.Thread(target=_telegram_loop, name="aureon-telegram", daemon=True),
        threading.Thread(target=_digest_loop, name="aureon-digest", daemon=True),
    ]
    for thread in threads:
        thread.start()
    while not desk_runtime._stop.is_set():
        publish_patch({
            "alive_ms": int(time.time() * 1000),
            "role": "worker",
            "threads": [thread.name for thread in threads if thread.is_alive()],
            "runtime": desk_runtime.operational_view(),
        })
        if desk_runtime._stop.wait(2):
            break
    stopped = desk_runtime.shutdown(deadline_s=5)
    return 0 if stopped.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
