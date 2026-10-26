"""The swipe server's routes: thin, like the command line."""

import hmac
import json
from datetime import UTC, datetime
from collections.abc import Awaitable, Callable

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from whetstone.features.grading.core import swipe_problem, swipe_reasons
from whetstone.features.grading.store import add_label, load_deck, load_labels
from whetstone.features.workspace.load import PromptSettings

Handler = Callable[[Request], Awaitable[Response]]

MAX_BODY = 64 * 1024


def refuse(error: str) -> Response:
    return JSONResponse({"error": error}, status_code=400)


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
        deck = load_deck(prompt.workspace, prompt.dir.name)
        grader = request.headers.get("x-grader", "")
        swiped = {label["card_id"] for label in load_labels(prompt.dir) if label["grader"] == grader}
        return JSONResponse({"cards": [c for c in deck["cards"] if c["card_id"] not in swiped], "reasons": prompt.reasons})

    async def swipes(request: Request) -> Response:
        # Handlers run one at a time on the event loop, so appends never interleave.
        raw = b""
        async for chunk in request.stream():
            raw += chunk
            if len(raw) > MAX_BODY:
                return refuse("body is over 64 KB")
        try:
            body = json.loads(raw)
        except ValueError:
            return refuse("body must be a JSON object")
        if problem := swipe_problem(body):
            return refuse(problem)
        deck = load_deck(prompt.workspace, prompt.dir.name)
        card = next((c for c in deck["cards"] if c["card_id"] == body.get("card_id")), None)
        if card is None:
            return refuse(f"no card {body.get('card_id')} in the current deck")
        swipe = {k: body[k] for k in ("grader", "verdict", "reasons", "note")}
        swipe["reasons"] = swipe_reasons(body["verdict"], body["reasons"], card["caught_by"])
        add_label(prompt.dir, {**card, "deck_id": deck["id"], **swipe, "at": datetime.now(UTC).isoformat()})
        return JSONResponse({}, status_code=201)

    return Starlette(routes=[Route("/api/cards", guarded(cards)), Route("/api/swipes", guarded(swipes), methods=["POST"])])
