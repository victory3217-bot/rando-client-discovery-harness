# -*- coding: utf-8 -*-
"""Anthropic Messages API — the first production ``LLMProvider`` in this repository.

``echo`` proves the pipeline runs with no provider at all. This one is the opposite end: it is
the adapter that actually sends a client's evidence over the network and bills for it. Three
things follow from that, and they are the reason this file looks the way it does.

**The prompt is not rewritten here.** ``prompts/`` owns what the model is asked to do;
``tests/test_research.py`` already fails if a prompt file so much as names a vendor. What this
adapter adds is an envelope, and the rule for it is mechanical: **instructions go in the system
block, data goes in the user block, and the core's own text goes first and verbatim in each.**
The three directives below (language, grounding, JSON) exist because ``LLMProvider`` hands the
adapter ``output_lang``, ``evidence`` and ``schema`` as *parameters* and something has to turn
them into words — ``core/interfaces/llm.py`` says as much: "Provider differences
(system-message handling, tool use, JSON modes, retries) are absorbed by the adapter." They
carry no business rule, no persona and no evidence policy, and
``tests/test_llm_anthropic.py`` asserts the whole of what they contain.

**Nothing is re-sent unless somebody asked for it.** :class:`RetryPolicy` defaults to
``max_attempts=1``, which is no retry at all. In this harness a retry is not free the way it is
in a CRUD service: the request body is the client's evidence, so re-sending it transmits that
evidence to a third party a second time, and bills a second time. That is a decision an
operator makes, not one an SDK default makes for them — which is the main reason the default
transport below is fifteen lines of ``urllib`` rather than a client library whose retry
behaviour is a constructor argument somebody has to remember to override.

**It does not log, and it does not keep anything.** There is no logger in this module, no
cache, no transcript, no temp file. Usage counts reach the caller only through an opt-in
``usage_sink`` callback carrying numbers and identifiers — never text. Provider error messages
are discarded the same way ``IntakeError`` and ``SQLiteStorageError`` discard theirs, because a
400 from a model API quotes the request that caused it and the request is the document.

Retention, training use and data residency are properties of the deployment, not of this file.
Nothing here asserts what the provider does with what it receives; ``docs/privacy.md`` says
what an operator has to check for themselves.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

from core.errors import ProviderError, StructuredOutputError

#: Messages API endpoint. Overridable per instance so that a gateway or a proxy can be used
#: without editing this file; there is no other reason to change it.
DEFAULT_API_URL = "https://api.anthropic.com/v1/messages"

#: ``anthropic-version`` request header. Pinned rather than "latest": a version the adapter has
#: not been read against can change the response shape under a deployment that did not move.
DEFAULT_API_VERSION = "2023-06-01"

#: Per-socket-operation timeout, in seconds. See :class:`AnthropicLLM` for why this is not an
#: overall deadline, and ``docs/product-spec.md`` for where the number comes from.
DEFAULT_TIMEOUT_SECONDS = 60.0

#: Every key this adapter ever puts in a request body. A closed set rather than a list of
#: things not to send, for the reason ``docs/privacy.md`` gives about logging allowlists: a
#: denylist leaks quietly every time the API grows a field.
#:
#: ``max_tokens`` is in the list and comes from the caller: it is a generation policy, and
#: this adapter has no default for it any more than it has a default model.
#:
#: What is deliberately absent, and why:
#:
#: * ``temperature`` / ``top_p`` / ``top_k`` — **sampling controls are not set here.** Their
#:   semantics differ between providers and between models of one provider, and some models
#:   constrain or reject them outright. An adapter that sent a value would be choosing a
#:   sampling policy for every stage of the analysis; one that translated between providers
#:   would be claiming the values mean the same thing. Neither is a transport's business.
#: * ``thinking`` — not turned on, not turned off. Whether a model reasons before answering,
#:   and what that costs in latency and tokens, is a property of the model the caller chose.
#:   Forcing it either way here would make a provider-native behaviour into a harness policy.
#: * ``tools`` / ``tool_choice`` — out of scope for Phase 8. The harness's determinism comes
#:   from prompt → response → parser/validator, and tool calling moves a decision into the
#:   provider.
#: * ``stream`` — excluded from Phase 1–8 by ``HARNESS.md`` section 10. The pipeline needs a
#:   complete response before it can validate one.
REQUEST_BODY_KEYS = ("max_tokens", "messages", "model", "system")


# -- error taxonomy ---------------------------------------------------------

class LLMErrorCode:
    """The closed set of reasons a provider call can fail.

    Codes rather than messages, for the same reason :class:`~core.errors.IntakeErrorCode`
    exists: what the provider says went wrong is a sentence that quotes the request, and the
    request is the client's evidence.
    """

    AUTH_FAILED = "LLM_AUTH_FAILED"
    RATE_LIMITED = "LLM_RATE_LIMITED"
    TIMEOUT = "LLM_TIMEOUT"
    NETWORK_FAILED = "LLM_NETWORK_FAILED"
    PROVIDER_UNAVAILABLE = "LLM_PROVIDER_UNAVAILABLE"
    INVALID_REQUEST = "LLM_INVALID_REQUEST"
    EMPTY_RESPONSE = "LLM_EMPTY_RESPONSE"
    RESPONSE_TRUNCATED = "LLM_RESPONSE_TRUNCATED"
    MALFORMED_RESPONSE = "LLM_MALFORMED_RESPONSE"
    CONTENT_REFUSED = "LLM_CONTENT_REFUSED"
    NOT_CONFIGURED = "LLM_NOT_CONFIGURED"
    OUTPUT_NOT_JSON = "LLM_OUTPUT_NOT_JSON"
    OUTPUT_SCHEMA_INVALID = "LLM_OUTPUT_SCHEMA_INVALID"
    VALIDATOR_UNAVAILABLE = "LLM_SCHEMA_VALIDATOR_UNAVAILABLE"


#: Every code an adapter error may carry. A test asserts no failure path invents one.
LLM_ERROR_CODES = frozenset(
    value
    for name, value in vars(LLMErrorCode).items()
    if not name.startswith("_") and isinstance(value, str)
)


class AnthropicLLMError(ProviderError):
    """A provider call failed, described without describing what was in it.

    Defined here rather than in ``core/errors.py`` because it is an adapter's concern — the
    core has no business knowing one of its providers speaks HTTP. It subclasses
    :class:`~core.errors.ProviderError` so a caller can catch every provider failure in one
    place regardless of which adapter is wired.

    The provider's own message is **discarded**. A ``400`` from a model API quotes the request
    that produced it, a ``401`` may echo a header, and both end up in every log line and
    traceback that touches the exception. What survives is a stable code, the HTTP status when
    there was one, and the originating exception's *class name* — the same rule, for the same
    reason, as :class:`~core.errors.IntakeError` and ``SQLiteStorageError``.
    """

    code = LLMErrorCode.NETWORK_FAILED

    def __init__(
        self,
        code: str,
        *,
        status: Optional[int] = None,
        exception_type: Optional[str] = None,
        attempts: int = 1,
    ) -> None:
        self.status = status
        self.exception_type = exception_type
        self.attempts = attempts
        super().__init__(code, code=code)

    def __repr__(self) -> str:
        return (
            f"AnthropicLLMError(code={self.code!r}, status={self.status!r}, "
            f"exception_type={self.exception_type!r}, attempts={self.attempts!r})"
        )


class AnthropicStructuredOutputError(StructuredOutputError):
    """The model answered, but not with a value satisfying the requested schema.

    Separate from :class:`AnthropicLLMError` because ``core/interfaces/llm.py`` names
    :class:`~core.errors.StructuredOutputError` as the contract for exactly this case, and a
    caller written against the contract must keep catching it whichever adapter is wired. The
    finer code says which half failed — not JSON at all, or JSON that the schema rejects.

    ``invalid_paths`` holds the JSON pointers of the failing fields, **not the validator's
    messages.** ``jsonschema`` quotes the instance in every message it produces, and the
    instance here is a model's answer derived from the client's documents. Paths are field
    names; anything that does not look like one is replaced with ``<omitted>``.
    """

    code = LLMErrorCode.OUTPUT_SCHEMA_INVALID

    def __init__(self, code: str, *, invalid_paths: Optional[tuple[str, ...]] = None) -> None:
        self.invalid_paths = tuple(invalid_paths or ())
        super().__init__(code, code=code)

    def __repr__(self) -> str:
        return (
            f"AnthropicStructuredOutputError(code={self.code!r}, "
            f"invalid_paths={self.invalid_paths!r})"
        )


# -- transport --------------------------------------------------------------

@dataclass(frozen=True)
class TransportResponse:
    """One HTTP response, reduced to what this adapter reads.

    ``headers`` is kept because two of them drive behaviour — ``retry-after`` and
    ``request-id`` — and for no other reason. The adapter never stores the mapping and never
    passes it on.
    """

    status: int
    headers: dict[str, str]
    body: bytes


class Transport(Protocol):
    """How a request reaches the provider.

    This seam exists for two reasons. It is what lets the offline tests drive every path in
    this file — request construction, retry, timeout, error mapping, extraction — without
    patching a library's internals or reaching the network. And it is where an organisation
    that would rather use the official SDK, Bedrock or Vertex plugs that in, without this
    adapter or the core acquiring a dependency on it.

    A transport **returns** a :class:`TransportResponse` for anything that produced an HTTP
    status, including 4xx and 5xx — those are answers, not transport failures. It **raises**
    ``TimeoutError`` when the deadline passed and ``OSError`` when the request could not be
    completed at all. Any other exception is treated as a network failure and only its class
    name is kept.
    """

    def __call__(
        self, *, url: str, headers: dict[str, str], body: bytes, timeout: float
    ) -> TransportResponse: ...


def urllib_transport(
    *, url: str, headers: dict[str, str], body: bytes, timeout: float
) -> TransportResponse:
    """The default transport: one POST, standard library only.

    Nothing about a Messages call needs more than this — no streaming, no connection reuse
    across a run that makes a provider round trip every few seconds anyway, no multipart. The
    official SDK would bring thirteen packages including two compiled extensions, and its
    retry behaviour would have to be switched off in a constructor argument to satisfy the
    rule above this file that nothing is re-sent unless somebody asked for it.

    The ``HTTPError`` branch matters more than it looks: converting the exception into a
    status and a body here means the rest of the adapter never handles a provider exception
    object at all, so there is no path by which one reaches a traceback.

    ``urllib`` is imported here rather than at module scope because importing it pulls in
    ``http.client`` and through it ``ssl``, which loads a TLS library. Nothing about defining
    this adapter needs that to have happened; a deployment that injects its own transport
    never needs it at all. Same reasoning as the lazily imported intake parsers.
    """
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return TransportResponse(
                status=response.status,
                headers={k.lower(): v for k, v in response.headers.items()},
                body=response.read(),
            )
    except urllib.error.HTTPError as exc:
        try:
            payload = exc.read()
        except Exception:  # pragma: no cover - the body is optional, the status is not
            payload = b""
        return TransportResponse(
            status=exc.code,
            headers={k.lower(): v for k, v in (exc.headers or {}).items()},
            body=payload,
        )


# -- policy -----------------------------------------------------------------

@dataclass(frozen=True)
class RetryPolicy:
    """When a failed call may be sent again, and how often.

    **The default is not to retry.** ``max_attempts`` counts attempts, not retries, so ``1``
    means the request goes out once and a failure is a failure. A retry in this harness
    re-transmits the client's evidence to a third party and bills for it again, which makes it
    an operator's decision rather than a library default — see ``docs/privacy.md``.

    ``retry_on`` holds codes, not statuses, so the set reads as the thing it is about: a
    rate limit, a provider outage, a timeout, a dropped connection. Everything else is left
    out deliberately. ``LLM_AUTH_FAILED`` and ``LLM_INVALID_REQUEST`` will fail identically
    however many times they are sent, and ``LLM_OUTPUT_SCHEMA_INVALID`` is a different request
    dressed as the same one — retrying it is resampling the model until it agrees, which is
    not a transport concern and would hide a prompt that has stopped working.
    """

    max_attempts: int = 1
    backoff_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    max_backoff_seconds: float = 30.0
    respect_retry_after: bool = True
    retry_on: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                LLMErrorCode.RATE_LIMITED,
                LLMErrorCode.PROVIDER_UNAVAILABLE,
                LLMErrorCode.TIMEOUT,
                LLMErrorCode.NETWORK_FAILED,
            }
        )
    )

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts is a number of attempts and cannot be below 1")

    def delay_for(self, attempt: int, retry_after: Optional[float]) -> float:
        """Seconds to wait before attempt ``attempt + 1`` (1-based ``attempt``)."""
        if self.respect_retry_after and retry_after is not None:
            return min(max(retry_after, 0.0), self.max_backoff_seconds)
        planned = self.backoff_seconds * (self.backoff_multiplier ** (attempt - 1))
        return min(max(planned, 0.0), self.max_backoff_seconds)


@dataclass(frozen=True)
class AnthropicUsage:
    """What one call cost, in counts. Never the content.

    Safe to log in full, on the same terms as
    :class:`~core.transmission.TransmissionRecord`: every field is a number, a status, an
    opaque identifier or a model name. It is handed to an opt-in callback and kept nowhere —
    there is no entity for it, because ``docs/data-model.md`` describes a domain and token
    counts are not part of one (see ``adapters/README.md``).
    """

    model: str
    input_tokens: int
    output_tokens: int
    status: int
    latency_ms: int
    attempts: int
    message_id: Optional[str] = None
    stop_reason: Optional[str] = None

    def as_log_fields(self) -> dict:
        return {
            "provider": "anthropic",
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "attempts": self.attempts,
            "message_id": self.message_id,
            "stop_reason": self.stop_reason,
        }


# -- the envelope -----------------------------------------------------------
#
# Everything this adapter adds to what the core supplied. Module constants rather than inline
# strings so that a test can assert the exact and entire text of it: an envelope nobody can
# enumerate is indistinguishable from a hidden system prompt.

#: Language codes this adapter can name in English. An unrecognised code is passed through as
#: written rather than guessed at — the core accepts any string here and inventing a mapping
#: would silently answer in the wrong language.
LANGUAGE_NAMES = {"ko": "Korean", "en": "English"}

#: ``output_lang`` is a parameter of every ``LLMProvider`` method, so the adapter has to say it.
LANGUAGE_DIRECTIVE = "Write your response in {language}."

#: ``analyze`` is the grounded call. ``core/interfaces/llm.py``: "An adapter is expected to
#: make the grounding explicit to the model and to leave fields unanswered rather than filling
#: them from general knowledge." This sentence is that, and nothing beyond it — which evidence
#: counts and what may be concluded from it is the prompt's business, not this file's.
EVIDENCE_DIRECTIVE = (
    "The passages under Evidence are the only evidence for this request. "
    "Base the answer on them, and where they do not settle a field, "
    "leave it unanswered rather than filling it from general knowledge."
)

#: ``generate_structured`` and ``analyze`` are contractually required to return a value
#: satisfying a JSON Schema, and the model cannot satisfy one it has not been shown.
JSON_DIRECTIVE = (
    "Return one JSON object that validates against the JSON Schema under JSON Schema. "
    "Output that object alone: no prose, no explanation, no code fence."
)

#: ``summarize`` takes raw text rather than a prompt file, so its instruction has nowhere else
#: to live. It is the only method whose whole instruction originates in this adapter.
SUMMARY_DIRECTIVE = "Condense the passage under Text into at most {max_sentences} sentence(s)."

#: Labels for the data sections of the user message. Plain headings, so that the core's own
#: prompt text stays first and recognisable.
EVIDENCE_HEADING = "Evidence:"
SCHEMA_HEADING = "JSON Schema:"
TEXT_HEADING = "Text:"

_FENCE = re.compile(r"^```[A-Za-z0-9_-]*\s*\n(?P<body>.*?)\n?```$", re.DOTALL)

#: A JSON pointer component is a field name or an index. Anything else in that position came
#: from the model rather than from the schema, which makes it content — see
#: ``core.research.models.safe_reference`` for the same rule applied to rejections.
_SAFE_PATH = re.compile(r"^[A-Za-z0-9_\-\[\]]{1,64}$")

#: Enough failing fields to debug a prompt, few enough that the list cannot become a payload.
_MAX_INVALID_PATHS = 12


def _language_name(output_lang: str) -> str:
    return LANGUAGE_NAMES.get((output_lang or "").strip().lower(), output_lang)


def build_system(
    system: Optional[str],
    *,
    output_lang: str,
    grounded: bool = False,
    structured: bool = False,
    max_sentences: Optional[int] = None,
) -> str:
    """The system block: the core's text verbatim and first, then the directives it implies."""
    parts: list[str] = []
    if system:
        parts.append(system)
    parts.append(LANGUAGE_DIRECTIVE.format(language=_language_name(output_lang)))
    if grounded:
        parts.append(EVIDENCE_DIRECTIVE)
    if structured:
        parts.append(JSON_DIRECTIVE)
    if max_sentences is not None:
        parts.append(SUMMARY_DIRECTIVE.format(max_sentences=max_sentences))
    return "\n\n".join(parts)


def build_user(
    prompt: str,
    *,
    evidence: Optional[list[str]] = None,
    schema: Optional[dict] = None,
    text: Optional[str] = None,
) -> str:
    """The user block: the core's prompt verbatim and first, then the data it refers to.

    ``sort_keys`` on the schema is not cosmetic — it is what makes two runs of the same stage
    produce byte-identical requests, which a test can then assert.

    An empty ``prompt`` contributes nothing rather than a leading blank: ``summarize`` has no
    prompt file behind it, so it passes one.
    """
    parts: list[str] = [prompt] if prompt else []
    if evidence:
        parts.append(EVIDENCE_HEADING + "\n" + "\n".join(evidence))
    if text is not None:
        parts.append(TEXT_HEADING + "\n" + text)
    if schema is not None:
        parts.append(
            SCHEMA_HEADING + "\n" + json.dumps(schema, ensure_ascii=False, sort_keys=True)
        )
    return "\n\n".join(parts)


# -- response reading -------------------------------------------------------

def _decode_body(body: bytes) -> dict:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise AnthropicLLMError(
            LLMErrorCode.MALFORMED_RESPONSE, exception_type=type(exc).__name__
        ) from None
    if not isinstance(payload, dict):
        raise AnthropicLLMError(LLMErrorCode.MALFORMED_RESPONSE)
    return payload


def _extract_text(payload: dict) -> str:
    """Every ``text`` block, joined. Other block types are ignored rather than rendered.

    A response can legitimately carry blocks this adapter did not ask for; turning one into a
    string would put a model's internal reasoning into an analysis result.
    """
    blocks = payload.get("content")
    if not isinstance(blocks, list):
        raise AnthropicLLMError(LLMErrorCode.MALFORMED_RESPONSE)
    pieces = [
        block["text"]
        for block in blocks
        if isinstance(block, dict)
        and block.get("type") == "text"
        and isinstance(block.get("text"), str)
    ]
    return "".join(pieces)


def _check_stop_reason(payload: dict) -> None:
    """A stop reason that means the answer is not the whole answer.

    ``max_tokens`` is the one that matters. A truncated response parses, reads as prose and is
    wrong in a way nothing downstream can see — half a SWOT classification is not a partial
    result, it is an unmarked one.
    """
    stop_reason = payload.get("stop_reason")
    if stop_reason == "max_tokens":
        raise AnthropicLLMError(LLMErrorCode.RESPONSE_TRUNCATED)
    if stop_reason == "refusal":
        raise AnthropicLLMError(LLMErrorCode.CONTENT_REFUSED)


def _strip_code_fence(text: str) -> str:
    match = _FENCE.match(text.strip())
    return match.group("body").strip() if match else text.strip()


def _safe_path(parts: list[Any]) -> str:
    if not parts:
        return "<root>"
    rendered = "/".join(str(part) for part in parts)
    return rendered if _SAFE_PATH.match(rendered.replace("/", "")) else "<omitted>"


def _parse_structured(text: str, schema: dict) -> dict:
    """Model text to a validated object, or a :class:`StructuredOutputError` saying which half failed."""
    stripped = _strip_code_fence(text)
    if not stripped:
        raise AnthropicLLMError(LLMErrorCode.EMPTY_RESPONSE)
    try:
        value = json.loads(stripped)
    except ValueError:
        raise AnthropicStructuredOutputError(LLMErrorCode.OUTPUT_NOT_JSON) from None
    if not isinstance(value, dict):
        raise AnthropicStructuredOutputError(LLMErrorCode.OUTPUT_NOT_JSON) from None

    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        # Returning the value unvalidated would hand the pipeline a dict that looks checked
        # and is not. The harness does not represent something unchecked as having passed —
        # the same rule the pricing adapter follows with EXTERNAL_CONTRACT_NOT_CHECKED.
        raise AnthropicLLMError(LLMErrorCode.VALIDATOR_UNAVAILABLE) from None

    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda e: list(e.path))
    if errors:
        raise AnthropicStructuredOutputError(
            LLMErrorCode.OUTPUT_SCHEMA_INVALID,
            invalid_paths=tuple(
                _safe_path(list(error.path)) for error in errors[:_MAX_INVALID_PATHS]
            ),
        )
    return value


def _status_code(status: int) -> str:
    if status in (401, 403):
        return LLMErrorCode.AUTH_FAILED
    if status == 429:
        return LLMErrorCode.RATE_LIMITED
    if status >= 500:
        return LLMErrorCode.PROVIDER_UNAVAILABLE
    return LLMErrorCode.INVALID_REQUEST


def _transport_failure_code(exc: BaseException) -> str:
    """A timeout reaches this adapter in two shapes, depending on when it happened.

    ``urlopen`` raises ``TimeoutError`` when a read runs out, but a connect timeout arrives
    wrapped in ``URLError``, whose ``reason`` is the original. Treating the second as a
    generic network failure would make a retry policy that excludes timeouts behave
    differently for the two.

    The wrapper is recognised by its ``reason`` attribute rather than by its class, so that
    the classification does not import ``urllib`` — and so that an injected transport
    wrapping its own timeout the same way is classified the same way.
    """
    if isinstance(exc, TimeoutError):
        return LLMErrorCode.TIMEOUT
    if isinstance(getattr(exc, "reason", None), TimeoutError):
        return LLMErrorCode.TIMEOUT
    return LLMErrorCode.NETWORK_FAILED


def _retry_after_seconds(headers: dict[str, str]) -> Optional[float]:
    raw = headers.get("retry-after")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        # The header also has an HTTP-date form. Rather than parse a date into a wait, fall
        # back to the configured backoff — a wrong wait is worse than a planned one.
        return None


# -- the adapter ------------------------------------------------------------

class AnthropicLLM:
    """Anthropic Messages API. Implements ``LLMProvider``.

    ``api_key`` and ``model`` are **supplied by the caller** and have no defaults. Neither is
    read from the environment: ``adapters/README.md`` puts that on the application layer, and
    an adapter that reads ``ANTHROPIC_API_KEY`` on its own starts billing whichever key
    happened to be exported in the shell that ran the tests. An adapter that picks the model
    is worse — it changes what the analysis says, silently, on the day the default moves.

    **The generation budget is the caller's too, and it has no default.** ``max_tokens`` is
    required, on the same terms as ``api_key`` and ``model``: it comes from this constructor
    and from nowhere else — not from the model name, not from a per-model table, not from the
    size of the prompt. How many tokens an answer may cost is a *policy* — it follows from
    what a deployment is for and what it is willing to spend — and policy selection is the
    application layer's job, not a transport's. A default here would be this adapter quietly
    making that choice for every deployment that forgot to.

    It is validated but **not bounded**: a positive ``int`` (``bool`` rejected explicitly,
    since it is one). No per-model ceiling is hardcoded, because this adapter does not know
    what any given model allows and would be wrong the first time one changed. A value the
    provider will not accept comes back as ``LLM_INVALID_REQUEST`` from the provider itself,
    which is the only party that actually knows.

    Sampling controls and ``thinking`` are not sent at all; :data:`REQUEST_BODY_KEYS` is the
    closed list of what is, and says why each absence is deliberate.

    **Timeout.** ``timeout_seconds`` is passed to the transport, and the default transport
    hands it to ``urlopen``, where it bounds *each socket operation* — the connect, and each
    read — rather than the call as a whole. So a server that trickles bytes can exceed it in
    total, and this adapter does not claim an overall deadline it cannot enforce. A transport
    that can enforce one may be injected; the seam is there for exactly this kind of thing.
    The default of ``60`` seconds is a starting value with headroom over the 2–8 s per-call
    band ``docs/product-spec.md`` models, not a measurement — real provider latency is
    NOT_MEASURED in this repository.

    **Blocking.** Every method blocks the calling thread for the whole round trip. The
    ``LLMProvider`` protocol is synchronous and stays that way; Phase 8's application runs a
    Bootstrap on a background thread, which is where the waiting belongs
    (``HARNESS.md`` section 10).

    **Sharing an instance.** The instance holds configuration and nothing else — no client
    object, no connection, no counter — and each call builds its own request, so one instance
    may be used from several threads. That is a property of this implementation, not a claim
    about the transport: a caller who injects one with shared state owns that question, as
    does a caller whose ``usage_sink`` is not itself thread-safe.
    """

    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        max_tokens: int,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        retry: Optional[RetryPolicy] = None,
        transport: Optional[Transport] = None,
        api_url: str = DEFAULT_API_URL,
        api_version: str = DEFAULT_API_VERSION,
        usage_sink: Optional[Callable[[AnthropicUsage], None]] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key or not api_key.strip():
            # Fail here rather than at the first call: discovering a missing credential after
            # a Bootstrap has assembled and batched a client's evidence wastes the part that
            # cost something.
            raise AnthropicLLMError(LLMErrorCode.NOT_CONFIGURED)
        if not model or not model.strip():
            raise AnthropicLLMError(LLMErrorCode.NOT_CONFIGURED)
        # ``bool`` is a subclass of ``int``, so ``max_tokens=True`` would otherwise pass the
        # numeric checks and put ``"max_tokens": true`` in the request body. Checked rather
        # than coerced: ``int("4096")`` and ``int(4096.9)`` both succeed and both mean the
        # caller did not send what they thought they sent.
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1:
            raise AnthropicLLMError(LLMErrorCode.NOT_CONFIGURED)

        self._api_key = api_key
        self._model = model
        self._timeout_seconds = float(timeout_seconds)
        self._max_tokens = max_tokens
        self._retry = retry or RetryPolicy()
        self._transport: Transport = transport or urllib_transport
        self._api_url = api_url
        self._api_version = api_version
        self._usage_sink = usage_sink
        self._sleep = sleep

    def __repr__(self) -> str:
        """No credential, here or anywhere else an object of this class is rendered."""
        return (
            f"AnthropicLLM(model={self._model!r}, timeout_seconds={self._timeout_seconds!r}, "
            f"max_attempts={self._retry.max_attempts!r})"
        )

    # -- LLMProvider -------------------------------------------------------
    def generate(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        output_lang: str = "ko",
    ) -> str:
        return self._text_call(
            system=build_system(system, output_lang=output_lang),
            user=build_user(prompt),
        )

    def generate_structured(
        self,
        prompt: str,
        *,
        schema: dict,
        system: Optional[str] = None,
        output_lang: str = "ko",
    ) -> dict:
        text = self._text_call(
            system=build_system(system, output_lang=output_lang, structured=True),
            user=build_user(prompt, schema=schema),
        )
        return _parse_structured(text, schema)

    def analyze(
        self,
        prompt: str,
        *,
        evidence: list[str],
        schema: dict,
        system: Optional[str] = None,
        output_lang: str = "ko",
    ) -> dict:
        text = self._text_call(
            system=build_system(
                system, output_lang=output_lang, grounded=True, structured=True
            ),
            user=build_user(prompt, evidence=list(evidence), schema=schema),
        )
        return _parse_structured(text, schema)

    def summarize(
        self,
        text: str,
        *,
        output_lang: str = "ko",
        max_sentences: int = 3,
    ) -> str:
        return self._text_call(
            system=build_system(
                None, output_lang=output_lang, max_sentences=max_sentences
            ),
            user=build_user("", text=text),
        )

    # -- one round trip ----------------------------------------------------
    def _text_call(self, *, system: str, user: str) -> str:
        payload, status, latency_ms, attempts = self._send(self._body(system, user))
        # Recorded before the response is judged: a truncated or refused answer was still
        # billed, and that is exactly the call an operator most wants to see the cost of.
        # ``stop_reason`` travels with the counts, so the sink can tell the two apart.
        self._record_usage(payload, status=status, latency_ms=latency_ms, attempts=attempts)
        _check_stop_reason(payload)
        text = _extract_text(payload)
        if not text.strip():
            # A response with no text is not an empty answer, it is a missing one. Returning
            # "" would flow into an entity as a blank finding nobody can trace.
            raise AnthropicLLMError(LLMErrorCode.EMPTY_RESPONSE, status=status)
        return text

    def _body(self, system: str, user: str) -> dict:
        """The whole request. Four keys, always the same four — see :data:`REQUEST_BODY_KEYS`."""
        return {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }

    def _headers(self) -> dict[str, str]:
        return {
            "content-type": "application/json",
            "accept": "application/json",
            "anthropic-version": self._api_version,
            "x-api-key": self._api_key,
        }

    def _send(self, body: dict) -> tuple[dict, int, int, int]:
        """Up to ``max_attempts`` attempts. Returns the decoded payload and what it cost."""
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        started = time.monotonic()
        last: AnthropicLLMError = AnthropicLLMError(LLMErrorCode.NETWORK_FAILED)

        for attempt in range(1, self._retry.max_attempts + 1):
            retry_after: Optional[float] = None
            try:
                response = self._transport(
                    url=self._api_url,
                    headers=self._headers(),
                    body=encoded,
                    timeout=self._timeout_seconds,
                )
            except Exception as exc:  # noqa: BLE001 - classified, then the object is dropped
                last = AnthropicLLMError(
                    _transport_failure_code(exc),
                    exception_type=type(exc).__name__,
                    attempts=attempt,
                )
            else:
                if 200 <= response.status < 300:
                    latency_ms = int((time.monotonic() - started) * 1000)
                    return _decode_body(response.body), response.status, latency_ms, attempt
                last = AnthropicLLMError(
                    _status_code(response.status), status=response.status, attempts=attempt
                )
                retry_after = _retry_after_seconds(response.headers)

            if attempt >= self._retry.max_attempts or last.code not in self._retry.retry_on:
                raise last
            self._sleep(self._retry.delay_for(attempt, retry_after))

        raise last  # pragma: no cover - the loop either returns or raises

    def _record_usage(
        self, payload: dict, *, status: int, latency_ms: int, attempts: int
    ) -> None:
        if self._usage_sink is None:
            return
        usage = payload.get("usage") or {}
        message_id = payload.get("id")
        self._usage_sink(
            AnthropicUsage(
                model=str(payload.get("model") or self._model),
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                status=status,
                latency_ms=latency_ms,
                attempts=attempts,
                message_id=message_id if isinstance(message_id, str) else None,
                stop_reason=payload.get("stop_reason"),
            )
        )
