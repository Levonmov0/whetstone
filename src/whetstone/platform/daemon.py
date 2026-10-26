"""Background processes that outlive the command, and the Claude session, that started them."""

import os
import signal
import subprocess
import time
from pathlib import Path


def start_detached(argv: list[str], stdin_text: str, log: Path, pass_fds: tuple[int, ...] = ()) -> int:
    """Start argv in its own session, so closing the terminal doesn't end it. stdin_text is written to its stdin
    and closed: the way to hand it a secret without putting it in its argv, where `ps` would show it."""
    with log.open("ab") as out:
        process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=out, stderr=out, start_new_session=True, pass_fds=pass_fds, text=True)
    assert process.stdin
    process.stdin.write(stdin_text)
    process.stdin.close()
    return process.pid


def write_private(path: Path, text: str) -> None:
    """Write a file only its owner can read."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)


def is_running(pid: int) -> bool:
    # ponytail: a pid the OS has reused for another process counts as running; serve --stop clears it.
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # alive, but another user's
        return True
    return True


def stop(pid: int, timeout: float = 5) -> None:
    """End the process and wait for it to go, so its port is free when this returns: SIGTERM, then SIGKILL after timeout."""
    for sig, wait in ((signal.SIGTERM, timeout), (signal.SIGKILL, timeout)):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + wait
        while _alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)


def _alive(pid: int) -> bool:
    # A child of this process lingers as a zombie until reaped, and a zombie still answers kill(pid, 0).
    try:
        if os.waitpid(pid, os.WNOHANG)[0] == pid:
            return False
    except ChildProcessError:
        pass  # not our child: someone else reaps it
    return is_running(pid)


def command_line(pid: int) -> str:
    """The process's command line, or "" when there is no such process."""
    # By full path: the check must not depend on what PATH holds.
    result = subprocess.run(["/bin/ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True)
    return result.stdout.strip()
