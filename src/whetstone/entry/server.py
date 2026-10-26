"""The swipe server's routes: thin, like the command line."""

from starlette.applications import Starlette

from whetstone.features.workspace.load import PromptSettings


def make_app(prompt: PromptSettings, token: str) -> Starlette:
    return Starlette()
