"""The swipe server's routes: thin, like the command line."""

import asyncio
import hmac
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import unquote
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from whetstone.features.checks.core import covered_reasons
from whetstone.features.checks.load import CheckLoadError, code_check_reasons, load_judges
from whetstone.features.grading.core import swipe_problem, swipe_reasons
from whetstone.features.grading.store import add_label, load_deck, load_labels
from whetstone.features.matching.core import Refusal, answer, case_of, said, answer_problem, pending, sure_items, undo
from whetstone.features.matching.store import add_event, snapshot
from whetstone.features.workspace.load import PromptSettings

Handler = Callable[[Request], Awaitable[Response]]

MAX_BODY = 64 * 1024
LIFETIME = timedelta(hours=12)
STATIC = Path(__file__).parent / "static"


def refuse(error: str) -> Response:
    return JSONResponse({"error": error}, status_code=400)


async def read_json(request: Request) -> Any:
    """The request's JSON body, or the refusal: over 64 KB, or not JSON."""
    raw = b""
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_BODY:
            return refuse("body is over 64 KB")
    try:
        return json.loads(raw)
    except (ValueError, RecursionError):  # RecursionError: nested deeper than the parser goes
        return refuse("body must be a JSON object")


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
        body = await read_json(request)
        if isinstance(body, Response):
            return body
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
        snap = snapshot(prompt.dir)
        # Every reason a check stands for: the Different chip sheet offers only reasons that can count.
        return JSONResponse({"items": pending(snap, reasons, grader), "reasons": sorted(reasons), "sure": sure_items(snap, reasons, grader)})

    async def answer_match(request: Request) -> Response:
        # One at a time on the event loop, as swipes are: two phones answering the same item can't both find it open.
        body = await read_json(request)
        if isinstance(body, Response):
            return body
        if problem := answer_problem(body):
            return refuse(problem)
        grader = unquote(request.headers.get("x-grader", ""))
        match = request.path_params["match"]
        reasons = covered()
        snap = snapshot(prompt.dir)
        now = datetime.now(UTC).isoformat()
        undoing = body["answer"] in ("undo", "redo")
        if undoing:
            line = undo(snap, reasons, grader, match, body["answer"], now)
            writes = (None, line) if isinstance(line, dict) else line
        else:
            writes = answer(snap, reasons, grader, match, body["answer"], body.get("reason"), now)
        if writes is None:  # answered already, from a double tap or another phone: it counts once, as first answered
            return JSONResponse({} if undoing else said(snap, reasons, match))
        if isinstance(writes, Refusal):
            # A stale item gets its own status, so the app can drop it.
            return JSONResponse({"error": writes.message}, status_code={"missing": 404, "stale": 409}.get(writes.kind, 400))
        event, line = writes
        if line is not None:
            add_label(prompt.dir, line)
        if event is not None:
            add_event(prompt.dir, case_of(snap, event), event)
        # Just stored, so the answer sent is the stored one: answer_problem allows a reason only with a different chip.
        return JSONResponse({} if undoing else {key: body[key] for key in ("answer", "reason") if key in body})

    async def app_page(request: Request) -> Response:
        return HTMLResponse((STATIC / "app.html").read_text())

    async def theme(request: Request) -> Response:
        # Whetstone's theme first, the repo's on top: a repo theme holds only the tokens init found, and every other
        # variable falls back to Whetstone's.
        workspace_theme = prompt.workspace / "theme.css"
        css = (STATIC / "default.css").read_text() + (workspace_theme.read_text() if workspace_theme.is_file() else "")
        return Response(css, media_type="text/css")

    async def broken_check(_request: Request, error: Exception) -> Response:
        # A check file that doesn't load is the session runner's to fix; the grader's answer waits until it's fixed.
        return JSONResponse({"error": str(error)}, status_code=500)

    return Starlette(lifespan=lifespan, exception_handlers={CheckLoadError: broken_check}, routes=[
        Route("/", app_page), Route("/theme.css", theme), Route("/api/cards", guarded(cards)), Route("/api/swipes", guarded(swipes), methods=["POST"]),
        Route("/api/matches", guarded(matches)), Route("/api/matches/{match}", guarded(answer_match), methods=["POST"]),
    ])
