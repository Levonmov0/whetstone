"""Claude Code's headless mode as a model call: the default way rewrites run, on the user's own Claude login."""

from whetstone.platform.model import ModelCall


def claude_code_model() -> ModelCall:
    raise NotImplementedError
