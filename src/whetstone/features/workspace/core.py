"""Pure rules about a prompt's harness request: no I/O, environment or SDKs."""

from typing import Any, cast


def request_problem(request: Any, case_id: str, production_model: str, editable: str) -> str | None:
    """Why a harness request can't be used, or None when it can."""
    for field in ("model", "messages"):
        if field not in request:
            return f'harness request for case {case_id} is missing "{field}"'
    if request["model"] != production_model:
        return f"harness requests {request['model']} but prompt.toml records production model {production_model}"
    times = sum(text.count(editable) for text in rendered_texts(request))
    if times != 1:
        return f"editable part found {times} times in request for case {case_id}"
    return None


def rendered_texts(request: Any) -> list[str]:
    """Every piece of prompt text in the request: the system prompt and each message's text."""
    parts = [request.get("system", "")] + [m["content"] for m in request["messages"]]
    return [text for part in parts for text in _texts(part)]


def _texts(content: Any) -> list[str]:
    # Content is a string or a list of text blocks.
    if isinstance(content, str):
        return [content]
    return [block["text"] for block in content]


def request_differences(built: Any, expected: Any, path: str = "") -> list[str]:
    """The path of every field where the harness's request and the production request differ."""
    if isinstance(built, dict) and isinstance(expected, dict):
        b, e = cast(dict[str, Any], built), cast(dict[str, Any], expected)
        return [d for k in sorted(b.keys() | e.keys()) for d in request_differences(b.get(k), e.get(k), f"{path}.{k}" if path else k)]
    if isinstance(built, list) and isinstance(expected, list) and len(cast(list[Any], built)) == len(cast(list[Any], expected)):
        pairs = zip(cast(list[Any], built), cast(list[Any], expected))
        return [d for i, (b, e) in enumerate(pairs) for d in request_differences(b, e, f"{path}[{i}]")]
    return [] if built == expected else [path]
