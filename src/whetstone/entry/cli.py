import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from whetstone.features.workspace.load import find_workspace
from whetstone.platform.model import ModelCall


def run(argv: list[str], make_model: Callable[[Any], ModelCall]) -> int:
    parser = argparse.ArgumentParser(prog="whetstone")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="run every case through the prompt and its checks")
    check.add_argument("prompt")
    args = parser.parse_args(argv)

    workspace = find_workspace(Path.cwd())
    if workspace is None:
        print("no Whetstone workspace found; run /whetstone:init or pass --workspace", file=sys.stderr)
        return 2
    return 0
