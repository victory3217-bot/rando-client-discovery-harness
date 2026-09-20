# -*- coding: utf-8 -*-
"""Brave Search API — the first production ``SearchProvider`` in this repository.

``manual`` returns only what a person pasted in, which is why every finding it produces has a
provenance somebody can vouch for. This one is the opposite: it reaches an index nobody in this
process controls and turns what comes back into the start of an evidence trail. Four things
follow from that, and they are why this file looks the way it does.

**A search result is a provenance record, not a reading.** What the adapter maps is what the
provider *stated*: a title, a URL, an extract, and — when it is there — the name of the site.
Nothing is derived. A publisher is not guessed from a hostname, a date is not read out of a URL
path, and ``evidence_quality`` stays ``UNKNOWN`` because an adapter knows where it fetched from
and not whether the source is any good. The one field this adapter *adds* is ``retrieved_at``,
which it is the only party in a position to know.

**The query that runs is the query the core wrote.** Two of this provider's defaults would
quietly break that, and both are turned off in :data:`REQUEST_PARAMS`: ``spellcheck`` replaces
the query with a corrected one and searches *that*, and ``operators`` reinterprets punctuation
in the query as search syntax, so a hyphen in ``IoT-기반 수질 측정`` becomes an exclusion. A
harness whose queries are generated prose cannot afford either. Nothing else is added: no
keyword expansion, no site filter, no region inferred from the machine this runs on.

**Snippets stay snippets.** ``core/research/policy.py`` gives search evidence the locator
``snippet`` and ``core/research/confidence.py`` caps it at MEDIUM for exactly one reason —
nothing has opened the page. This adapter does not open it either. It asks the web-search
endpoint, which returns extracts, and it does not follow a single URL it receives. The
provider's own "LLM Context" endpoint, which returns page content prepared for machine
consumption, is deliberately not the one used here: it would put material into evidence that
the harness would then be describing as an unread snippet.

**It does not log, and it does not keep anything.** There is no logger in this module, no
cache, no transcript, no temp file. Counts reach the caller only through an opt-in
``usage_sink`` carrying numbers and a status — never the query, never a URL, never a snippet.
Provider error bodies are discarded like ``IntakeError`` discards its own: a 422 from a search
API quotes the query that caused it, and the query describes the client.

Retention and what the provider does with a query are properties of the deployment, not of
this file. Nothing here asserts either; ``docs/privacy.md`` says what an operator has to check.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

from core.errors import ProviderError
from core.interfaces.search import SearchResult
from core.models import Confidence, MarketScope, utc_now

#: Web search endpoint. Overridable per instance so a gateway or proxy can be used without
#: editing this file; there is no other reason to change it.
DEFAULT_API_URL = "https://api.search.brave.com/res/v1/web/search"

#: Per-socket-operation timeout, in seconds. See :class:`BraveSearch` for why this is not an
#: overall deadline.
DEFAULT_TIMEOUT_SECONDS = 30.0

#: Results this endpoint will return for one request.
#:
#: A ``limit`` above this is **refused**, not quietly reduced. Silently returning twenty for a
#: caller who asked for twenty-five would make the adapter answer a question nobody asked: the
#: caller's ``limit`` is a research decision made in ``core/analysis/policy.py``, and an
#: adapter that trims it hides the fact that the deployment's policy is not satisfiable by the
#: wired provider. Refusing says so at the point the value is wrong, before anything is billed.
#:
#: Pagination is not the answer either and is not implemented — one ``search()`` is one
#: provider request, always.
MAX_RESULTS_PER_REQUEST = 20

#: Longest URL the source record can hold (``schemas/source_metadata.schema.json``). A result
#: whose URL will not fit is rejected rather than truncated — half a URL is not a provenance.
MAX_URL_CHARS = 2048

#: Longest publisher the source record can hold (same schema). Over it, the publisher is
#: dropped rather than cut: a truncated name is a different organisation's name.
MAX_PUBLISHER_CHARS = 200

#: What this adapter puts in ``SearchResult.publisher``, and the audit behind it.
#:
#: The provider's field is ``profile.name`` — "the name of the profile", which its contract
#: guarantees to be a **site identity**, not a publishing organisation. Whether that may be
#: mapped depends entirely on what ``publisher`` means to the core, so that was read rather
#: than assumed:
#:
#: * ``core/research/confidence.py`` is the only place the value is *used*, through
#:   ``_authority_known``, whose own docstring says it is "deliberately weak: this asks **can
#:   we tell who is speaking**, not are they right".
#: * The same module's header says in as many words that "a named publisher is not the same as
#:   a checked claim", and that nothing there grants HIGH on the strength of this field.
#: * ``core/evidence.py`` requires ``title`` and ``retrieved_at`` for a ``SEARCH_RESULT`` and
#:   does not require or constrain ``publisher`` at all.
#: * ``schemas/source_metadata.schema.json`` describes it only as "its absence limits
#:   confidence".
#:
#: So the core's operative meaning is *source identity* — can a reader tell who is speaking —
#: and a site profile name answers that question honestly. It is mapped.
#:
#: What is **not** done, because it would turn identity into a claim: no publisher is derived
#: from a hostname or a URL, none is taken from the page title, and none is inferred from a
#: ``profile.url``. A value over :data:`MAX_PUBLISHER_CHARS` is dropped rather than truncated.
#: Absence is a working answer — ``_authority_known`` returns ``False`` and the ceiling falls —
#: and filling it on a guess to avoid that is exactly the trade this harness refuses.
#:
#: Note also what this cannot affect today: a result from this adapter reaches the core as
#: snippet evidence, and ``_is_unverified_snippet`` caps it at MEDIUM *before*
#: ``_authority_known`` is consulted. The field is therefore provenance a reader sees, not a
#: lever on confidence.
PUBLISHER_SOURCE_FIELD = "profile.name"

#: Request parameters whose value this adapter fixes, and the entire reason each is here.
#:
#: A closed set, stated as what *is* sent rather than what is not — the same rule
#: ``REQUEST_BODY_KEYS`` follows in the LLM adapter, and for the same reason: a list of things
#: to avoid leaks quietly every time the API grows a field.
#:
#: * ``spellcheck=false`` — **the provider's default is true, and it does not merely suggest.**
#:   Its own documentation: "If the spell checker is enabled, the modified query is always used
#:   for search." A corrected query is a different query, and the core would never see that it
#:   had been substituted.
#: * ``operators=false`` — the default is true, which reads ``-``, ``site:`` and quotes in the
#:   query as syntax. ``core/analysis/research.py`` passes query *terms* produced from criteria,
#:   not hand-written search expressions; leaving this on lets a hyphen silently delete results.
#: * ``text_decorations=false`` — the default wraps matched terms in highlight markup. That
#:   markup is the engine's, not the document's, and it would land inside an
#:   ``EvidenceCandidate`` and split organisation names across tags, which is precisely what
#:   ``core/client/discover.py``'s token-boundary check reads.
#: * ``result_filter=web`` — only web results are read by this adapter, so only web results are
#:   asked for. It also keeps the provider's summarizer, infobox and location blocks out of the
#:   response entirely; anything AI-generated that arrived could be mistaken for a retrieval.
#:
#: What is deliberately absent, and why:
#:
#: * ``summary`` / ``enable_rich_callback`` — both default off, and both are left off. They
#:   enable generated content. An adapter that turned one on would be putting something no
#:   document says into a record whose whole purpose is to say where things came from.
#: * ``extra_snippets`` — more extracts per page is closer to reading the page, which is the
#:   line this adapter does not cross. One snippet per result, as the contract models it.
#: * ``freshness`` / ``goggles`` — a date window and a re-ranking are *research policy*. The
#:   contract has no parameter for either, so an adapter that set one would be choosing what
#:   counts as relevant on the core's behalf.
#: * ``safesearch`` — not sent. Filtering policy is the provider's default or the operator's
#:   decision, not something a transport picks silently in either direction.
#: * ``x-loc-*`` headers — latitude, city, timezone and country of *this machine*. Never sent.
#:   That is the implicit region selection ``adapters/README.md`` and the contract both forbid.
REQUEST_PARAMS = {
    "operators": "false",
    "result_filter": "web",
    "spellcheck": "false",
    "text_decorations": "false",
}

#: Every parameter key a request may carry, fixed and caller-supplied together. A test asserts
#: the built request matches this set exactly.
REQUEST_PARAM_KEYS = ("count", "country", "operators", "q", "result_filter", "spellcheck",
                      "text_decorations")


# -- error taxonomy ---------------------------------------------------------

class SearchErrorCode:
    """The closed set of reasons a search call can fail.

    Codes rather than messages, for the reason :class:`~core.errors.IntakeErrorCode` exists:
    what the provider says went wrong is a sentence that quotes the request, and the request
    carries the query — which names the client, the industry and the market being looked into.

    There is no ``EMPTY_RESPONSE`` here on purpose. For a model, no text is a *missing* answer;
    for a search, no results is a real one, and ``core/analysis/research.py`` already reads it
    as such (``if not hits: continue``). Raising on it would turn "nothing was found" into an
    outage.
    """

    NOT_CONFIGURED = "SEARCH_NOT_CONFIGURED"
    AUTH_FAILED = "SEARCH_AUTH_FAILED"
    RATE_LIMITED = "SEARCH_RATE_LIMITED"
    TIMEOUT = "SEARCH_TIMEOUT"
    NETWORK_FAILED = "SEARCH_NETWORK_FAILED"
    PROVIDER_UNAVAILABLE = "SEARCH_PROVIDER_UNAVAILABLE"
    INVALID_REQUEST = "SEARCH_INVALID_REQUEST"
    MALFORMED_RESPONSE = "SEARCH_MALFORMED_RESPONSE"


#: Every code an adapter error may carry. A test asserts no failure path invents one.
SEARCH_ERROR_CODES = frozenset(
    value
    for name, value in vars(SearchErrorCode).items()
    if not name.startswith("_") and isinstance(value, str)
)


class BraveSearchError(ProviderError):
    """A search call failed, described without describing what was searched for.

    Defined here rather than in ``core/errors.py`` because it is an adapter's concern — the
    core has no business knowing one of its providers speaks HTTP. It subclasses
    :class:`~core.errors.ProviderError` so a caller can catch every provider failure in one
    place regardless of which adapter is wired.

    The provider's own message is **discarded**. A ``422`` from a search API quotes the query
    that produced it, and the query is a description of a client's market. What survives is a
    stable code, the HTTP status when there was one, and the originating exception's *class
    name* — the same rule, for the same reason, as :class:`~core.errors.IntakeError`.
    """

    code = SearchErrorCode.NETWORK_FAILED

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
            f"BraveSearchError(code={self.code!r}, status={self.status!r}, "
            f"exception_type={self.exception_type!r}, attempts={self.attempts!r})"
        )


# -- transport --------------------------------------------------------------

@dataclass(frozen=True)
class TransportResponse:
    """One HTTP response, reduced to what this adapter reads.

    ``headers`` is kept because one of them drives behaviour — ``x-ratelimit-reset`` — and for
    no other reason. The adapter never stores the mapping and never passes it on.
    """

    status: int
    headers: dict[str, str]
    body: bytes


class Transport(Protocol):
    """How a request reaches the provider.

    Declared here rather than imported from ``adapters/llm/anthropic.py`` even though the two
    are nearly the same shape. An adapter that imported another adapter would make a search
    deployment depend on an LLM vendor's module, and the rule in ``adapters/README.md`` is that
    each of these is replaceable on its own.

    ``params`` is passed as a mapping rather than a pre-encoded URL so that the query string is
    the transport's business: the adapter never builds one, tests assert on values instead of
    parsing, and an injected transport that takes ``params=`` natively needs no adapting.

    A transport **returns** a :class:`TransportResponse` for anything that produced an HTTP
    status, including 4xx and 5xx — those are answers, not transport failures. It **raises**
    ``TimeoutError`` when the deadline passed and ``OSError`` when the request could not be
    completed at all. Any other exception is treated as a network failure and only its class
    name is kept.
    """

    def __call__(
        self,
        *,
        url: str,
        headers: dict[str, str],
        params: dict[str, str],
        timeout: float,
    ) -> TransportResponse: ...


def urllib_transport(
    *, url: str, headers: dict[str, str], params: dict[str, str], timeout: float
) -> TransportResponse:
    """The default transport: one GET, standard library only.

    Nothing about a search call needs more than this. There is no official SDK worth the
    dependency here — the request is a query string and four fixed parameters — and a
    general-purpose HTTP client would bring a retry policy this harness needs to own itself
    (see :class:`RetryPolicy`).

    ``Accept-Encoding: gzip`` is **not** sent although the provider's examples do: ``urlopen``
    does not decompress, so asking for gzip means reading compressed bytes and calling them
    malformed JSON.

    The ``HTTPError`` branch matters more than it looks: converting the exception into a status
    and a body here means the rest of the adapter never handles a provider exception object at
    all, so there is no path by which one reaches a traceback.

    ``urllib`` is imported here rather than at module scope because importing it pulls in
    ``http.client`` and through it ``ssl``, which loads a TLS library. Nothing about defining
    this adapter needs that to have happened; a deployment that injects its own transport never
    needs it at all. Same reasoning as the lazily imported intake parsers.
    """
    import urllib.error
    import urllib.parse
    import urllib.request

    query = urllib.parse.urlencode(params, encoding="utf-8")
    request = urllib.request.Request(f"{url}?{query}", headers=headers, method="GET")
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
    """When a failed search may be sent again, and how often.

    **The default is not to retry.** ``max_attempts`` counts attempts, not retries, so ``1``
    means the request goes out once and a failure is a failure. The reasoning is the one
    ``adapters/llm/anthropic.py`` gives — a re-send transmits the query to a third party a
    second time, and that is an operator's decision rather than a library default.

    **Read this before deploying, though.** Search plans are commonly rate-limited *per second*
    rather than per month alone, and ``core/analysis/research.py`` calls :meth:`BraveSearch
    .search` once per query in a tight loop. On such a plan the second query of a run returns
    ``429`` with the default policy and the stage simply finds nothing. The default is still
    one attempt, because a policy that silently waits and re-sends is not something this file
    should decide for a deployment; but an operator on a per-second limit almost certainly
    wants ``RetryPolicy(max_attempts=3)`` and should set it deliberately.

    ``retry_on`` holds codes, not statuses. ``SEARCH_AUTH_FAILED`` and
    ``SEARCH_INVALID_REQUEST`` will fail identically however many times they are sent, and
    ``SEARCH_MALFORMED_RESPONSE`` is the provider's shape having changed — re-asking hides that
    rather than fixing it.
    """

    max_attempts: int = 1
    backoff_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    max_backoff_seconds: float = 30.0

    #: Whether a ``429``'s ``x-ratelimit-reset`` decides the wait. This provider does not send
    #: ``retry-after``; the reset header is the equivalent, and :func:`reset_seconds` reads it.
    respect_rate_limit_reset: bool = True

    retry_on: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                SearchErrorCode.RATE_LIMITED,
                SearchErrorCode.PROVIDER_UNAVAILABLE,
                SearchErrorCode.TIMEOUT,
                SearchErrorCode.NETWORK_FAILED,
            }
        )
    )

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts is a number of attempts and cannot be below 1")

    def delay_for(self, attempt: int, reset_after: Optional[float]) -> float:
        """Seconds to wait before attempt ``attempt + 1`` (1-based ``attempt``)."""
        if self.respect_rate_limit_reset and reset_after is not None:
            return min(max(reset_after, 0.0), self.max_backoff_seconds)
        planned = self.backoff_seconds * (self.backoff_multiplier ** (attempt - 1))
        return min(max(planned, 0.0), self.max_backoff_seconds)


@dataclass(frozen=True)
class BraveSearchUsage:
    """What one search call cost and what came back, in counts. Never the content.

    Safe to log in full, on the same terms as
    :class:`~core.transmission.TransmissionRecord`: every field is a number or a status. The
    query is present only as ``query_chars``, which is how ``TransmissionRecord`` represents
    what was sent to a model, and for the same reason — a length says how much went out without
    saying what.

    ``rejected_count`` is the one worth watching. It counts results this adapter refused to map
    because they were missing a title, missing a usable URL, or not a JSON object at all. A
    number that is suddenly non-zero means the provider's response shape moved, and without
    this there would be no way to notice short of the findings quietly thinning out.

    **Only a call this adapter could read is reported here.** A failed one raises instead, and
    :class:`BraveSearchError` carries its own ``status`` and ``attempts`` — including for a
    ``200`` whose body turned out to be unreadable, which was billed and says so through
    ``status``. So every call reaches the operator as numbers either way, and this type does not
    have to describe a call whose counts do not exist.
    """

    status: int
    latency_ms: int
    attempts: int
    limit: int
    #: Results the provider returned in ``web.results``.
    returned_count: int
    #: Results this adapter turned into a :class:`~core.interfaces.search.SearchResult`.
    mapped_count: int
    #: Results refused by :func:`_map_result` because they were unusable as provenance.
    rejected_count: int
    query_chars: int
    #: The country restriction that was applied, or ``None``. A code, not a location.
    country: Optional[str] = None

    def as_log_fields(self) -> dict:
        return {
            "provider": "brave",
            "status": self.status,
            "latency_ms": self.latency_ms,
            "attempts": self.attempts,
            "limit": self.limit,
            "returned_count": self.returned_count,
            "mapped_count": self.mapped_count,
            "rejected_count": self.rejected_count,
            "query_chars": self.query_chars,
            "country": self.country,
        }


# -- response reading -------------------------------------------------------

def _decode_body(body: bytes, *, status: int) -> dict:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise BraveSearchError(
            SearchErrorCode.MALFORMED_RESPONSE,
            status=status,
            exception_type=type(exc).__name__,
        ) from None
    if not isinstance(payload, dict):
        raise BraveSearchError(SearchErrorCode.MALFORMED_RESPONSE, status=status)
    return payload


def _web_results(payload: dict, *, status: int) -> list:
    """The ``web.results`` list, or an empty list when the provider found nothing.

    ``web`` is documented as nullable and is absent for a query with no web results, so its
    absence is an answer rather than a fault. ``web`` present but shaped differently is not:
    reading that as "no results" would turn a changed API into a silent zero-findings run.
    """
    web = payload.get("web")
    if web is None:
        return []
    if not isinstance(web, dict):
        raise BraveSearchError(SearchErrorCode.MALFORMED_RESPONSE, status=status)
    results = web.get("results")
    if results is None:
        return []
    if not isinstance(results, list):
        raise BraveSearchError(SearchErrorCode.MALFORMED_RESPONSE, status=status)
    return results


def _text(value: Any, *, limit: Optional[int] = None) -> Optional[str]:
    """A non-empty string, or ``None``. Never a coerced one and never a truncated one.

    ``str(value)`` on a dict would put ``{'name': ...}`` into a provenance field, so anything
    that is not already a string is absent. Over ``limit`` is also absent rather than cut: the
    fields this guards are names and addresses, and half of either is a different one.
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if limit is not None and len(stripped) > limit:
        return None
    return stripped


def _usable_url(value: Any) -> Optional[str]:
    """The URL exactly as the provider gave it, if it can serve as provenance.

    Checked, not rewritten. No tracking parameter is stripped, no redirect is unwrapped and no
    host is canonicalised: this provider returns the destination page's own address, and an
    adapter that edited it would be asserting that two addresses are the same page — a judgement
    it cannot make and that ``HARNESS.md`` section 7 keeps out of this layer. The core has no
    URL normalisation for the same reason, and this step does not add one.

    What *is* checked is that the value can survive the rest of the trail: a string, a scheme
    the record is about, and short enough for ``SourceMetadata.url``.
    """
    url = _text(value, limit=MAX_URL_CHARS)
    if url is None:
        return None
    lowered = url.lower()
    if not (lowered.startswith("https://") or lowered.startswith("http://")):
        return None
    return url


def _map_result(
    raw: Any,
    *,
    retrieved_at: str,
    scope: MarketScope,
    country: Optional[str],
    provider_name: str,
) -> Optional[SearchResult]:
    """One provider result as a provenance record, or ``None`` if it cannot be one.

    Rejection is per result, not per call: one unusable entry among ten must not lose the other
    nine, and ``search`` returns a list with no channel to report a partial failure. Nothing
    malformed becomes evidence either way — the count reaches an operator through
    :class:`BraveSearchUsage`.

    Two fields are rejected rather than patched. A result with no title cannot be stored at all
    (``core.evidence.check_source_metadata`` requires one for ``SEARCH_RESULT``), and a result
    with no usable URL has nothing for a reader to check the claim against. An absent publisher
    is different: the contract says its absence limits confidence, and
    ``core/research/confidence.py`` already acts on that — so it stays ``None`` and the ceiling
    handles it. :data:`PUBLISHER_SOURCE_FIELD` records what the provider's field actually
    guarantees and why the core's meaning of ``publisher`` admits it.

    **``published_date`` is left unset, and this is the most consequential line in the file.**
    This endpoint's date field is documented as "the page's date, based on its published *or
    last modified* date". That is not a publication date, and writing it into one would make a
    six-year-old page that was touched last month look current in the record a reader trusts.
    Nothing else is available to derive one from that would not be a guess: a year in a snippet
    is a year the snippet mentions, a date in a URL path is a convention some sites follow, and
    the time of the search is ``retrieved_at`` and already recorded. So the harness records that
    it does not know, which is true. The provider's news endpoint does carry a real publication
    date; that is a different endpoint with different semantics and not this step's contract.
    """
    if not isinstance(raw, dict):
        return None

    title = _text(raw.get("title"))
    url = _usable_url(raw.get("url"))
    if title is None or url is None:
        return None

    # ``profile.name`` is a site identity, which is what the core means by ``publisher`` —
    # see :data:`PUBLISHER_SOURCE_FIELD` for the audit. Nothing else is consulted: no hostname,
    # no ``profile.url``, no fallback to the title.
    profile = raw.get("profile")
    publisher = (
        _text(profile.get("name"), limit=MAX_PUBLISHER_CHARS)
        if isinstance(profile, dict)
        else None
    )

    description = raw.get("description")
    if description is not None and not isinstance(description, str):
        # The snippet is the citable passage. A non-string in its place means this entry is not
        # the shape the adapter was read against, and guessing at it would put an invented
        # quotation into an EvidenceCandidate.
        return None

    return SearchResult(
        title=title,
        # Empty is allowed and is not an error: `core/research/sources.py` already drops a
        # result with no snippet, because there is nothing to cite. That rule lives there, and
        # repeating it here would give it a second home to drift from.
        snippet=(description or "").strip(),
        url=url,
        publisher=publisher,
        published_date=None,  # see this function's docstring
        retrieved_at=retrieved_at,
        # Both of these are echoes of the *request*, not claims about the document: this result
        # was retrieved under that scope and under that country restriction. It is also what
        # keeps the invariant `ManualSearch` satisfies — every result carries the scope it was
        # searched under — true of this adapter, so one contract test covers both.
        country=country,
        market_scope=scope,
        provider=provider_name,
        # An adapter knows where it fetched from, not whether the source is any good.
        evidence_quality=Confidence.UNKNOWN,
    )


def _status_code(status: int) -> str:
    if status in (401, 403):
        return SearchErrorCode.AUTH_FAILED
    if status == 429:
        return SearchErrorCode.RATE_LIMITED
    if status >= 500:
        return SearchErrorCode.PROVIDER_UNAVAILABLE
    return SearchErrorCode.INVALID_REQUEST


def _transport_failure_code(exc: BaseException) -> str:
    """A timeout reaches this adapter in two shapes, depending on when it happened.

    ``urlopen`` raises ``TimeoutError`` when a read runs out, but a connect timeout arrives
    wrapped in ``URLError``, whose ``reason`` is the original. Treating the second as a generic
    network failure would make a retry policy that excludes timeouts behave differently for the
    two.

    The wrapper is recognised by its ``reason`` attribute rather than by its class, so that the
    classification does not import ``urllib`` — and so that an injected transport wrapping its
    own timeout the same way is classified the same way.
    """
    if isinstance(exc, TimeoutError):
        return SearchErrorCode.TIMEOUT
    if isinstance(getattr(exc, "reason", None), TimeoutError):
        return SearchErrorCode.TIMEOUT
    return SearchErrorCode.NETWORK_FAILED


def reset_seconds(headers: dict[str, str]) -> Optional[float]:
    """Seconds until the soonest quota window resets, from ``x-ratelimit-reset``.

    This provider does not send ``retry-after``. It sends one reset value per window, comma
    separated and narrowest first — ``1, 1419704`` is "one second until the per-second limit
    clears, sixteen days until the monthly quota does". The first value is the one a retry can
    wait out; the second is not a wait, it is a bill.

    Anything unparseable falls back to the configured backoff, because a wrong wait is worse
    than a planned one.
    """
    raw = headers.get("x-ratelimit-reset")
    if not raw:
        return None
    try:
        return float(raw.split(",")[0].strip())
    except (AttributeError, TypeError, ValueError):
        return None


# -- the adapter ------------------------------------------------------------

class BraveSearch:
    """Brave Search API. Implements ``SearchProvider``.

    ``api_key`` is **supplied by the caller** and has no default. It is not read from the
    environment: ``adapters/README.md`` puts that on the application layer, and an adapter that
    reaches for a key on its own starts billing whichever one happened to be exported in the
    shell that ran the tests.

    **Scope does not become a request parameter.** ``MarketScope`` is this harness's
    distinction, not the provider's, and there is no honest mapping from ``DOMESTIC`` to a
    country code — inventing one would be the implicit region selection the contract forbids.
    The scope is carried onto each result as the scope the search ran under, and that is all.

    **Country is passed through only when the caller gives one.** When they do not, the
    provider applies *its own* documented default, which is not "everywhere". The adapter does
    not choose it and does not hide it: the operator who needs a specific market says so through
    the ``country`` argument, which ``core/analysis/research.py`` already threads from the
    project. Nothing about this machine's locale, timezone or address is ever sent.

    **Timeout.** ``timeout_seconds`` is passed to the transport, and the default transport hands
    it to ``urlopen``, where it bounds *each socket operation* — the connect, and each read —
    rather than the call as a whole. So a server that trickles bytes can exceed it in total, and
    this adapter does not claim an overall deadline it cannot enforce. A transport that can
    enforce one may be injected; the seam is there for exactly this kind of thing.

    **One call is one request.** No pagination, ever: ``offset`` is not sent and no loop reads a
    second page. A ``SearchProvider.search`` that quietly made four requests would multiply an
    operator's bill by four with nothing in the contract saying so.

    **Sharing an instance.** The instance holds configuration and nothing else — no client
    object, no connection, no counter — and each call builds its own request, so one instance
    may be used from several threads. That is a property of this implementation, not a claim
    about an injected transport or a ``usage_sink`` that is not itself thread-safe.
    """

    name = "brave"

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        retry: Optional[RetryPolicy] = None,
        transport: Optional[Transport] = None,
        api_url: str = DEFAULT_API_URL,
        api_version: Optional[str] = None,
        usage_sink: Optional[Callable[[BraveSearchUsage], None]] = None,
        clock: Callable[[], str] = utc_now,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """``api_version`` pins the provider's response contract, in its ``YYYY-MM-DD`` form.

        Left unset by default, in which case the provider serves its latest. The LLM adapter
        pins its version outright; this one cannot, because there is no published version string
        to hardcode that would not be a guess, and a wrong one fails every call. An operator who
        wants the response shape frozen against the day this adapter was read passes the version
        their dashboard shows.

        ``clock`` supplies ``retrieved_at``. Injected rather than called directly so a test can
        assert the exact value that reaches the record; the default is the same ``utc_now`` every
        other timestamp in this harness comes from, so the formats cannot drift apart.
        """
        if not api_key or not api_key.strip():
            # Fail here rather than at the first call: discovering a missing credential after a
            # stage has assembled its criteria wastes the part that cost something.
            raise BraveSearchError(SearchErrorCode.NOT_CONFIGURED)

        self._api_key = api_key
        self._timeout_seconds = float(timeout_seconds)
        self._retry = retry or RetryPolicy()
        self._transport: Transport = transport or urllib_transport
        self._api_url = api_url
        self._api_version = api_version
        self._usage_sink = usage_sink
        self._clock = clock
        self._sleep = sleep

    def __repr__(self) -> str:
        """No credential, here or anywhere else an object of this class is rendered."""
        return (
            f"BraveSearch(timeout_seconds={self._timeout_seconds!r}, "
            f"max_attempts={self._retry.max_attempts!r})"
        )

    # -- SearchProvider ----------------------------------------------------
    def search(
        self,
        query: str,
        *,
        scope: MarketScope = MarketScope.DOMESTIC,
        country: Optional[str] = None,
        limit: int = 10,
    ) -> list[SearchResult]:
        """Retrieve up to ``limit`` items for ``query``, in the order the provider ranked them.

        **That order is a search ranking and nothing else.** It is not a priority, and nothing
        downstream may read it as one: ``sales_priority`` comes from ``core/client/priority.py``
        working over evidence, and a result being first here says only that an index put it
        first. No score is mapped, because carrying one would invite exactly that confusion.

        ``limit`` must be between ``1`` and :data:`MAX_RESULTS_PER_REQUEST`, and anything else
        is refused before the transport is touched. Neither end is clamped. Below ``1`` is a
        caller's mistake rather than an instruction; above the maximum is a policy this
        provider cannot satisfy, and quietly returning twenty for a request of twenty-five
        would answer a different question while looking like success. Whether to lower the
        research policy or to wire a provider that returns more is a decision for the layer
        that set the number, not for this one.

        Results are returned exactly as the provider ordered them, **duplicates included.**
        Nothing here collapses two entries that share a URL, let alone two that look similar:
        deciding that two records are the same thing is entity resolution, which ``HARNESS.md``
        section 7 keeps out of this pipeline entirely.
        """
        if not query or not query.strip():
            raise BraveSearchError(SearchErrorCode.INVALID_REQUEST)
        if not 1 <= limit <= MAX_RESULTS_PER_REQUEST:
            raise BraveSearchError(SearchErrorCode.INVALID_REQUEST)

        params = self._params(query, country=country, limit=limit)
        payload, status, latency_ms, attempts = self._send(params)

        raw_results = _web_results(payload, status=status)
        mapped: list[SearchResult] = []
        retrieved_at = self._clock()
        for raw in raw_results:
            result = _map_result(
                raw,
                retrieved_at=retrieved_at,
                scope=scope,
                country=country,
                provider_name=self.name,
            )
            if result is not None:
                mapped.append(result)

        self._record_usage(
            status=status,
            latency_ms=latency_ms,
            attempts=attempts,
            limit=limit,
            returned_count=len(raw_results),
            mapped_count=len(mapped),
            query_chars=len(query),
            country=country,
        )
        return mapped

    # -- one round trip ----------------------------------------------------
    def _params(self, query: str, *, country: Optional[str], limit: int) -> dict[str, str]:
        """The whole request. :data:`REQUEST_PARAM_KEYS` is the closed list of what it holds.

        ``q`` is the caller's string **verbatim** — not stripped, not lowercased, not expanded,
        not given a site filter or a language. The provider's documented ceilings on query
        length and word count are not enforced here for the reason the LLM adapter does not
        enforce a token ceiling: the party that actually knows the limit is the one that should
        answer, and a local guess rejects valid input the day the limit moves.
        """
        params = dict(REQUEST_PARAMS)
        params["q"] = query
        params["count"] = str(limit)
        if country is not None:
            params["country"] = self._country_param(country)
        return params

    @staticmethod
    def _country_param(country: str) -> str:
        """The caller's country code in the form the provider's parameter takes.

        A shape check and a case change, and deliberately not a lookup: the provider accepts a
        subset of ISO-3166 codes, and hardcoding that subset here would reject a code the day it
        is added. Something that is not two letters is refused locally, because sending a
        country name where a code belongs is certainly wrong rather than possibly unsupported.

        Note that the *result* carries the caller's string as they wrote it, not this one — an
        adapter that echoed back a value it had reshaped would make the record disagree with the
        request that produced it.
        """
        code = country.strip()
        if len(code) != 2 or not code.isascii() or not code.isalpha():
            raise BraveSearchError(SearchErrorCode.INVALID_REQUEST)
        return code.upper()

    def _headers(self) -> dict[str, str]:
        headers = {
            "accept": "application/json",
            "x-subscription-token": self._api_key,
        }
        if self._api_version is not None:
            headers["api-version"] = self._api_version
        return headers

    def _send(self, params: dict[str, str]) -> tuple[dict, int, int, int]:
        """Up to ``max_attempts`` attempts. Returns the decoded payload and what it cost."""
        started = time.monotonic()
        last: BraveSearchError = BraveSearchError(SearchErrorCode.NETWORK_FAILED)

        for attempt in range(1, self._retry.max_attempts + 1):
            reset_after: Optional[float] = None
            try:
                response = self._transport(
                    url=self._api_url,
                    headers=self._headers(),
                    params=dict(params),
                    timeout=self._timeout_seconds,
                )
            except Exception as exc:  # noqa: BLE001 - classified, then the object is dropped
                last = BraveSearchError(
                    _transport_failure_code(exc),
                    exception_type=type(exc).__name__,
                    attempts=attempt,
                )
            else:
                if 200 <= response.status < 300:
                    latency_ms = int((time.monotonic() - started) * 1000)
                    payload = _decode_body(response.body, status=response.status)
                    return payload, response.status, latency_ms, attempt
                last = BraveSearchError(
                    _status_code(response.status), status=response.status, attempts=attempt
                )
                reset_after = reset_seconds(response.headers)

            if attempt >= self._retry.max_attempts or last.code not in self._retry.retry_on:
                raise last
            self._sleep(self._retry.delay_for(attempt, reset_after))

        raise last  # pragma: no cover - the loop either returns or raises

    def _record_usage(
        self,
        *,
        status: int,
        latency_ms: int,
        attempts: int,
        limit: int,
        returned_count: int,
        mapped_count: int,
        query_chars: int,
        country: Optional[str],
    ) -> None:
        if self._usage_sink is None:
            return
        self._usage_sink(
            BraveSearchUsage(
                status=status,
                latency_ms=latency_ms,
                attempts=attempts,
                limit=limit,
                returned_count=returned_count,
                mapped_count=mapped_count,
                rejected_count=returned_count - mapped_count,
                query_chars=query_chars,
                country=country,
            )
        )
