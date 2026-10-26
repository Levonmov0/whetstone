"""The swipe server process that `whetstone serve` starts in the background.

Run as: python -m whetstone.entry.serve_main <workspace> <prompt> <listening socket fd>, with the token on stdin."""

import socket
import sys
from pathlib import Path

import uvicorn

from whetstone.entry.server import make_app
from whetstone.features.workspace.load import load_prompt


def main() -> None:
    workspace, name, fd = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
    token = sys.stdin.readline().strip()
    app = make_app(load_prompt(workspace, name), token)
    uvicorn.Server(uvicorn.Config(app)).run(sockets=[socket.socket(fileno=fd)])


if __name__ == "__main__":
    main()
