"""Run the packaged executable before it is released.

    python tools/smoke_test.py dist/puppet-strings-linux

The spec leaves out Qt plugins and libraries the app does not use, and what it leaves out
can only be told apart from what it needs by running the result. This solves a day of the
fixture sheets, which takes OR-Tools, numpy and pandas as packaged, and opens the request
manager and the trainer offscreen, each of which must still be running after a while. A
missing library shows up as an exit, where a working window only ever waits.
"""

import contextlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
SOLVE_SECONDS = 300
WINDOW_SECONDS = 15


# A one-file executable is a launcher that runs the app as a child, so stopping it means
# stopping both: its own process group on POSIX, and the process tree on Windows.
NEW_GROUP = (
    {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    if sys.platform == "win32"
    else {"start_new_session": True}
)


def _stop(process: subprocess.Popen) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], check=False)
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    process.wait()


def main() -> int:
    """Run each check and report the first that fails. Returns the exit code."""
    executable = str(Path(sys.argv[1]).resolve())
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    solve = [executable, "--fixtures", str(FIXTURES), "--date", "2026-09-16", "solve"]
    done = subprocess.run(solve, env=env, cwd=ROOT, timeout=SOLVE_SECONDS, check=False)
    if done.returncode != 0:
        print(f"solve exited with {done.returncode}", file=sys.stderr)
        return 1
    print("solve: ok")
    for name, args in (("app", ["--fixtures", str(FIXTURES), "app"]), ("train", ["train"])):
        window = subprocess.Popen([executable, *args], env=env, cwd=ROOT, **NEW_GROUP)
        time.sleep(WINDOW_SECONDS)
        code = window.poll()
        _stop(window)
        if code is not None:
            print(f"{name} exited with {code} before {WINDOW_SECONDS}s", file=sys.stderr)
            return 1
        print(f"{name}: still running after {WINDOW_SECONDS}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
