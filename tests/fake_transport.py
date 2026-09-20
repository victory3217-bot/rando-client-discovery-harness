# -*- coding: utf-8 -*-
"""A transport that answers without a network, and records what it was asked.

``adapters/llm/anthropic.py`` takes its transport as a constructor argument for two reasons,
and this module is the first of them: every path in that adapter — request construction,
retry, backoff, timeout, error mapping, text extraction, schema validation — can be driven
here with no credential, no socket and no monkeypatching of a library's internals.

``schema_responder`` is the one worth reading. It pulls the JSON Schema back out of the
request the adapter built and synthesises a valid instance from it using ``EchoLLM``'s own
synthesiser. That makes the interchangeability test real rather than nominal: if the adapter
ever stopped putting a machine-readable schema into the request, the fake could not answer it
and the test would fail for the right reason.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Optional, Union

from adapters.llm.anthropic import SCHEMA_HEADING, TransportResponse
from adapters.llm.echo import _synthesize


@dataclass(frozen=True)
class FakeRequest:
    """One call the adapter made, exactly as it made it."""

    url: str
    headers: dict[str, str]
    body: bytes
    timeout: float

    @property
    def payload(self) -> dict:
        return json.loads(self.body.decode("utf-8"))

    @property
    def system(self) -> str:
        return self.payload.get("system", "")

    @property
    def user(self) -> str:
        return self.payload["messages"][0]["content"]

    @property
    def schema(self) -> Optional[dict]:
        marker = "\n\n" + SCHEMA_HEADING + "\n"
        if marker not in self.user:
            return None
        return json.loads(self.user.rsplit(marker, 1)[1])


#: A scripted step: a response to return, an exception to raise, or a function of the request.
Step = Union[TransportResponse, BaseException, Callable[[FakeRequest], TransportResponse]]


class FakeTransport:
    """Answers from a script, and keeps every request for the test to assert on.

    Steps are consumed in order; once the script runs out the **last step repeats**, so a
    one-step script is a constant answer and a multi-step one is a sequence (a 429 then a 200,
    for instance). Tests that care how many calls were made assert on ``requests``, which is
    the honest way to check it — a transport that refused a second call would make "no retry
    by default" pass for the wrong reason.
    """

    def __init__(self, *script: Step) -> None:
        if not script:
            raise ValueError("a fake transport needs at least one step")
        self._script: list[Step] = list(script)
        self._index = 0
        self.requests: list[FakeRequest] = []

    def __call__(
        self, *, url: str, headers: dict[str, str], body: bytes, timeout: float
    ) -> TransportResponse:
        request = FakeRequest(url=url, headers=dict(headers), body=body, timeout=timeout)
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

def message_body(
    text: str,
    *,
    stop_reason: str = "end_turn",
    message_id: str = "msg_fictional_0001",
    model: str = "model-under-test",
    input_tokens: int = 11,
    output_tokens: int = 7,
    content: Optional[list] = None,
) -> dict:
    """A Messages API response body, in the shape the adapter reads."""
    return {
        "id": message_id,
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": text}] if content is None else content,
        "stop_reason": stop_reason,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


def ok(text: str, **kwargs: Any) -> TransportResponse:
    """A 200 carrying ``text``."""
    return raw(200, message_body(text, **kwargs))


def raw(status: int, body: Any, *, headers: Optional[dict[str, str]] = None) -> TransportResponse:
    """Any status with any body — including a body that is not a Messages response at all."""
    encoded = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    return TransportResponse(status=status, headers=dict(headers or {}), body=encoded)


def error(
    status: int, *, headers: Optional[dict[str, str]] = None, message: str = "provider detail"
) -> TransportResponse:
    """An error status whose body carries a message the adapter must never surface."""
    return raw(
        status,
        {"type": "error", "error": {"type": "invalid_request_error", "message": message}},
        headers=headers,
    )


def schema_responder(request: FakeRequest) -> TransportResponse:
    """Answer whatever schema the request carries, with a valid instance of it.

    Uses ``EchoLLM``'s synthesiser so that the two adapters answer the same shape, which is
    what lets one contract test run against both.
    """
    schema = request.schema
    if schema is None:
        return ok("[fake] no schema in this request")
    value = _synthesize(schema, key="root", required=True)
    return ok(json.dumps(value if isinstance(value, dict) else {"value": value}))
