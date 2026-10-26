"""The swipe server process that `whetstone serve` starts in the background.

Run as: python -m whetstone.entry.serve_main <workspace> <prompt> <listening socket fd>, with the token on stdin."""

import json
import os
import signal
import socket
import sys
from pathlib import Path

import uvicorn

from whetstone.entry.server import make_app
from whetstone.features.workspace.load import load_prompt


def _exit(_signum: int, _frame: object) -> None:
    sys.exit(0)


def main() -> None:
    workspace, name, fd = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
    token = sys.stdin.readline().strip()
    # At the end of its lifetime it stops the way `serve --stop` does, so its token dies with it.
    app = make_app(load_prompt(workspace, name), token, on_expiry=lambda: os.kill(os.getpid(), signal.SIGTERM))
    # uvicorn shuts down gracefully on SIGTERM, then re-raises it; this handler turns that into an exit that runs `finally`.
    signal.signal(signal.SIGTERM, _exit)
    try:
        uvicorn.Server(uvicorn.Config(app)).run(sockets=[socket.socket(fileno=fd)])
    finally:
        # Gone, so its state goes too; but only our own, in case a newer server already replaced it.
        state_file = workspace / ".whetstone" / "serve.json"
        if state_file.is_file() and json.loads(state_file.read_text()).get("pid") == os.getpid():
            state_file.unlink()


if __name__ == "__main__":
    main()
