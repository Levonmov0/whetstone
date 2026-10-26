"""The swipe server's routes: thin, like the command line."""

import hmac
from collections.abc import Awaitable, Callable

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from whetstone.features.workspace.load import PromptSettings

Handler = Callable[[Request], Awaitable[Response]]


def make_app(prompt: PromptSettings, token: str) -> Starlette:
    expected = f"Bearer {token}".encode()

    def guarded(handler: Handler) -> Handler:
        async def guard(request: Request) -> Response:
            # Constant time, so the token can't be guessed a byte at a time.
            if not hmac.compare_digest(request.headers.get("authorization", "").encode(), expected):
                return JSONResponse({"error": "missing or wrong token"}, status_code=401)
            return await handler(request)

        return guard

    async def cards(request: Request) -> Response:
        return JSONResponse({})

    async def swipes(request: Request) -> Response:
        return JSONResponse({})

    return Starlette(routes=[Route("/api/cards", guarded(cards)), Route("/api/swipes", guarded(swipes), methods=["POST"])])
