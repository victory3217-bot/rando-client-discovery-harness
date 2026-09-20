# -*- coding: utf-8 -*-
"""A search transport that answers without a network, and records what it was asked.

``fake_transport.py`` does this for ``adapters/llm/anthropic.py``; this is the same idea for
``adapters/search/brave.py``, and it is separate for the same reason the two adapters declare
their own ``Transport`` protocols — neither should have to import the other to be testable.

The difference that matters is the shape of a request. An LLM call is a POST with a JSON body,
so the fake parses bytes; a search call is a GET with a query string, so the adapter hands the
transport a ``params`` mapping and this records it as-is. That is what lets a test assert
``request.params["q"] == query`` rather than decoding a URL and hoping the encoding round trips.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Optional, Union

from adapters.search.brave import TransportResponse


@dataclass(frozen=True)
class FakeRequest:
    """One call the adapter made, exactly as it made it."""

    url: str
    headers: dict[str, str]
    params: dict[str, str]
    timeout: float

    @property
    def query(self) -> str:
        return self.params["q"]

    @property
    def count(self) -> Optional[int]:
        raw = self.params.get("count")
        return None if raw is None else int(raw)


#: A scripted step: a response to return, an exception to raise, or a function of the request.
Step = Union[TransportResponse, BaseException, Callable[[FakeRequest], TransportResponse]]


class FakeTransport:
    """Answers from a script, and keeps every request for the test to assert on.

    Steps are consumed in order; once the script runs out the **last step repeats**, so a
    one-step script is a constant answer and a multi-step one is a sequence (a 429 then a 200,
    for instance). Tests that care how many calls were made assert on ``requests``, which is the
    honest way to check it — a transport that refused a second call would make "no retry by
    default" pass for the wrong reason.
    """

    def __init__(self, *script: Step) -> None:
        if not script:
            raise ValueError("a fake transport needs at least one step")
        self._script: list[Step] = list(script)
        self._index = 0
        self.requests: list[FakeRequest] = []

    def __call__(
        self, *, url: str, headers: dict[str, str], params: dict[str, str], timeout: float
    ) -> TransportResponse:
        request = FakeRequest(
            url=url, headers=dict(headers), params=dict(params), timeout=timeout
        )
        self.requests.append(request)

        step = self._script[min(self._index, len(self._script) - 1)]
        self._index += 1

        if isinstance(step, BaseException):
            raise step
        if callable(step):
            return step(request)
        return step

    @property
    def calls(self) -> int:
        return len(self.requests)

    @property
    def last(self) -> FakeRequest:
        return self.requests[-1]


# -- response builders ------------------------------------------------------

#: "This argument was not passed", as distinct from "this argument was passed as ``None``".
#:
#: The distinction is the whole point for ``profile`` and ``description``: a provider may send
#: the key with a null value, and a test has to be able to build that case. A plain ``None``
#: default would silently turn it back into the fixture's value.
ABSENT = object()


def result(
    *,
    title: Any = "Fictional market note",
    url: Any = "https://example.invalid/note",
    description: Any = "fictional desalination demand is rising",
    profile: Any = ABSENT,
    page_age: Any = ABSENT,
    **extra: Any,
) -> dict:
    """One ``web.results`` entry, in the shape the adapter reads.

    ``page_age`` is offered so a test can supply one and assert it does **not** become a
    ``published_date``. A builder that could not produce the field could not prove the rule.
    """
    entry: dict = {
        "type": "search_result",
        "title": title,
        "url": url,
        "description": description,
        "profile": {"name": "Example Institute"} if profile is ABSENT else profile,
        "language": "en",
        "family_friendly": True,
    }
    if page_age is not ABSENT:
        entry["page_age"] = page_age
    entry.update(extra)
    return entry


def web_body(*results: dict, **extra: Any) -> dict:
    """A web-search response body carrying ``results``."""
    body: dict = {
        "type": "search",
        "query": {"original": "fictional query"},
        "web": {"type": "search", "results": list(results)},
    }
    body.update(extra)
    return body


def ok(*results: dict, headers: Optional[dict[str, str]] = None, **extra: Any) -> TransportResponse:
    """A 200 carrying ``results``."""
    return raw(200, web_body(*results, **extra), headers=headers)


def raw(status: int, body: Any, *, headers: Optional[dict[str, str]] = None) -> TransportResponse:
    """Any status with any body — including a body that is not a search response at all."""
    encoded = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    return TransportResponse(status=status, headers=dict(headers or {}), body=encoded)


def error(
    status: int,
    *,
    headers: Optional[dict[str, str]] = None,
    message: str = "provider detail",
) -> TransportResponse:
    """An error status whose body carries a message the adapter must never surface."""
    return raw(
        status,
        {
            "type": "ErrorResponse",
            "error": {"code": "VALIDATION", "detail": message, "meta": {"query": message}},
            "time": 0,
        },
        headers=headers,
    )
