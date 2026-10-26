"""Background processes that outlive the command, and the Claude session, that started them."""

import os
import subprocess
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
    return True
