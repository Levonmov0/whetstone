"""The swipe server's routes: thin, like the command line."""

import asyncio
import hmac
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import unquote
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from whetstone.features.checks.core import covered_reasons
from whetstone.features.checks.load import code_check_reasons, load_judges
from whetstone.features.grading.core import swipe_problem, swipe_reasons
from whetstone.features.grading.store import add_label, load_deck, load_labels
from whetstone.features.matching.core import pending
from whetstone.features.matching.store import load_events
from whetstone.features.workspace.load import PromptSettings

Handler = Callable[[Request], Awaitable[Response]]

MAX_BODY = 64 * 1024
LIFETIME = timedelta(hours=12)
STATIC = Path(__file__).parent / "static"


def refuse(error: str) -> Response:
    return JSONResponse({"error": error}, status_code=400)


def make_app(prompt: PromptSettings, token: str, lifetime: timedelta = LIFETIME, on_expiry: Callable[[], None] = lambda: None) -> Starlette:
    """on_expiry is called once the server has run for its lifetime, whatever graders are doing; the server process
    stops itself there, so its token dies with it and no process outlives half a day."""
    expected = f"Bearer {token}".encode()

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncGenerator[None]:
        async def expire() -> None:
            await asyncio.sleep(lifetime.total_seconds())
            on_expiry()

        timer = asyncio.create_task(expire())
        yield
        timer.cancel()

    def guarded(handler: Handler) -> Handler:
        async def guard(request: Request) -> Response:
            # Constant time, so the token can't be guessed a byte at a time.
            if not hmac.compare_digest(request.headers.get("authorization", "").encode(), expected):
                return JSONResponse({"error": "missing or wrong token"}, status_code=401)
            return await handler(request)

        return guard

    def no_deck() -> Response:
        return JSONResponse({"error": f"no cards yet; run whetstone check {prompt.dir.name}"}, status_code=409)

    async def cards(request: Request) -> Response:
        deck = load_deck(prompt.workspace, prompt.dir.name)
        if deck is None:
            return no_deck()
        grader = unquote(request.headers.get("x-grader", ""))  # URL-encoded: a header can't carry most names
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
        except (ValueError, RecursionError):  # RecursionError: nested deeper than the parser goes
            return refuse("body must be a JSON object")
        if problem := swipe_problem(body):
            return refuse(problem)
        deck = load_deck(prompt.workspace, prompt.dir.name)
        if deck is None:
            return no_deck()
        card = next((c for c in deck["cards"] if c["card_id"] == body.get("card_id")), None)
        if card is None:
            return refuse(f"no card {body.get('card_id')} in the current deck")
        swipe = {k: body[k] for k in ("grader", "verdict", "reasons", "note")}
        by_code = [name for name in card["caught_by"] if name not in card.get("judges", [])]
        swipe["reasons"] = swipe_reasons(body["verdict"], body["reasons"], by_code)
        add_label(prompt.dir, {**card, "deck_id": deck["id"], **swipe, "at": datetime.now(UTC).isoformat()})
        return JSONResponse({}, status_code=201)

    def covered() -> set[str]:
        return covered_reasons(code_check_reasons(prompt.dir), load_judges(prompt.dir))

    async def matches(request: Request) -> Response:
        grader = unquote(request.headers.get("x-grader", ""))
        reasons = covered()
        items = pending(load_labels(prompt.dir), load_events(prompt.dir), reasons, grader)
        # Every reason a check stands for: the Different chip sheet offers only reasons that can count.
        return JSONResponse({"items": items, "reasons": sorted(reasons)})

    async def answer_match(request: Request) -> Response:
        return JSONResponse({})

    async def app_page(request: Request) -> Response:
        return HTMLResponse((STATIC / "app.html").read_text())

    async def theme(request: Request) -> Response:
        # Whetstone's theme first, the repo's on top: a repo theme holds only the tokens init found, and every other
        # variable falls back to Whetstone's.
        workspace_theme = prompt.workspace / "theme.css"
        css = (STATIC / "default.css").read_text() + (workspace_theme.read_text() if workspace_theme.is_file() else "")
        return Response(css, media_type="text/css")

    return Starlette(lifespan=lifespan, routes=[
        Route("/", app_page), Route("/theme.css", theme), Route("/api/cards", guarded(cards)), Route("/api/swipes", guarded(swipes), methods=["POST"]),
        Route("/api/matches", guarded(matches)), Route("/api/matches/{match}", guarded(answer_match), methods=["POST"]),
    ])
