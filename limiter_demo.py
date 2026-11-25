"""Offline cutoff demonstration using a disposable Windows process tree."""

import _winapi
from pathlib import Path
import sys
import tempfile
import time

from limiter_windows import bind, start_job, wintypes


def run_demo():
    from limiter import monitor, open_database, save_readings

    open_process = bind("OpenProcess", wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    child_code = (
        "import os, sys, time; from pathlib import Path; "
        "Path(sys.argv[1]).write_text(str(os.getpid()), encoding='ascii'); time.sleep(30)"
    )
    parent_code = "import subprocess, sys; subprocess.run([sys.executable, '-c', *sys.argv[1:]], check=True)"
    with tempfile.TemporaryDirectory(prefix="limiter-demo-") as directory:
        root = Path(directory)
        ready = root / "child.pid"
        with open_database(root) as db:
            reset = int(time.time()) + 3600
            save_readings(db, [("five_hour", 89, reset), ("seven_day", 10, reset)])
            command = [sys.executable, "-c", parent_code, child_code, str(ready)]
            with start_job(command) as process:
                for _ in range(100):
                    if ready.exists() and ready.stat().st_size:
                        break
                    time.sleep(0.05)
                else:
                    raise RuntimeError("The demo child did not start.")
                child = open_process(0x100000, False, int(ready.read_text(encoding="ascii")))
                if not child:
                    raise OSError("Could not verify the demo child process.")
                try:
                    print("89%: the disposable process and its child are running.", flush=True)
                    save_readings(db, [("five_hour", 90, reset)])
                    if monitor(process, db, initially_blocked=False, label="demo process") != 2:
                        raise RuntimeError("The demo process exited before the cutoff was enforced.")
                    if _winapi.WaitForSingleObject(child, 2000) != _winapi.WAIT_OBJECT_0:
                        raise RuntimeError("The demo child did not stop.")
                finally:
                    _winapi.CloseHandle(child)
    print("90%: both processes stopped. No Claude request was made.")
    return 0
