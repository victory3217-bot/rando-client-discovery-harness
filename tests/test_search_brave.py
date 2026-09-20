# -*- coding: utf-8 -*-
"""The Brave search adapter: everything true of this provider and not of the contract.

``test_search_contract.py`` checks what every ``SearchProvider`` must do, against manual and
brave together. This file checks the things that only exist because this one talks to a paid,
remote, third-party index — credential handling, request construction, retry, error mapping,
response validation, and the leak surfaces that come with all three.

**No test here has a credential and none opens a socket.** The adapter takes its transport as a
constructor argument, so the whole of it can be driven from ``fake_search_transport.py``. The
one test that would use a real provider is skipped unless two environment variables are set
together, and there is a test below asserting that a stray ``BRAVE_API_KEY`` is not one of them.
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from adapters.search.brave import (
    DEFAULT_API_URL,
    DEFAULT_TIMEOUT_SECONDS,
    MAX_PUBLISHER_CHARS,
    MAX_RESULTS_PER_REQUEST,
    MAX_URL_CHARS,
    REQUEST_PARAM_KEYS,
    REQUEST_PARAMS,
    SEARCH_ERROR_CODES,
    BraveSearch,
    BraveSearchError,
    BraveSearchUsage,
    RetryPolicy,
    SearchErrorCode,
    reset_seconds,
)
from core.errors import ProviderError
from core.interfaces import SearchProvider
from core.interfaces.search import SearchResult
from core.models import Confidence, MarketScope
from core.research.sources import ingest_search_results
from fake_search_transport import FakeTransport, error, ok, raw, result, web_body

REPO_ROOT = Path(__file__).resolve().parent.parent
ADAPTER = REPO_ROOT / "adapters" / "search" / "brave.py"

#: Fictional. This repository is public (``HARNESS.md`` section 9) and a string shaped like a
#: credential is treated as one by a secret scanner and by a careless reader alike.
FAKE_KEY = "BSA-fictional-not-a-real-token-0000"

#: A fixed retrieval time, so that a test can assert the exact value that reaches the record
#: rather than "something that looks like a timestamp".
FIXED_NOW = "2026-09-20T09:15:00+00:00"


def build(*script, **kwargs) -> tuple[BraveSearch, FakeTransport]:
    """An adapter wired to a scripted transport. Every test starts here."""
    transport = FakeTransport(*(script or (ok(result()),)))
    kwargs.setdefault("api_key", FAKE_KEY)
    kwargs.setdefault("clock", lambda: FIXED_NOW)
    return BraveSearch(transport=transport, **kwargs), transport


def _code_tokens(path: Path) -> set[str]:
    """Every identifier and literal the module *runs*, with docstrings and comments left out.

    Several rules below are of the form "this concept does not appear in the adapter". Grepping
    the file text cannot express that: this adapter's whole job includes explaining, in prose,
    which neighbouring concepts it deliberately has nothing to do with, and a raw search reads
    those explanations as the violation they exist to prevent.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstrings = {
        ast.get_docstring(node, clean=False)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }

    tokens: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            tokens.add(node.id)
        elif isinstance(node, ast.Attribute):
            tokens.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            tokens.add(node.name)
        elif isinstance(node, ast.arg):
            tokens.add(node.arg)
        elif isinstance(node, ast.keyword) and node.arg:
            tokens.add(node.arg)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value not in docstrings:
                tokens.add(node.value)
    return tokens


# -- A: the protocol -------------------------------------------------------

def test_a_the_production_adapter_satisfies_the_protocol() -> None:
    adapter, _ = build()
    assert isinstance(adapter, SearchProvider)
    assert adapter.name == "brave"


# -- C: import side effects ------------------------------------------------

def test_c_importing_the_module_touches_nothing(tmp_path: Path) -> None:
    """Import must not read the environment, open a socket, or leave a file anywhere.

    A subprocess rather than ``importlib.reload``: a reload does not repeat import-time work and
    rebinds the exception classes, after which every ``pytest.raises`` in this file silently
    stops matching (see the same note in ``test_llm_anthropic.py``).
    """
    probe = tmp_path / "probe.py"
    probe.write_text(
        "\n".join(
            [
                "import pathlib, sys, tempfile",
                f"sys.path.insert(0, {str(REPO_ROOT)!r})",
                "import socket",
                # The class itself is left alone: ``ssl`` subclasses it at import time, so
                # replacing it breaks the import for a reason that has nothing to do with this
                # adapter. Patching the method that actually reaches the network says the same
                # thing without that.
                "def _refuse(*a, **k):",
                "    raise AssertionError('import opened a socket')",
                "socket.socket.connect = _refuse",
                "socket.create_connection = _refuse",
                "root = pathlib.Path(tempfile.gettempdir())",
                "cwd = pathlib.Path.cwd()",
                "before_temp, before_cwd = set(root.iterdir()), set(cwd.iterdir())",
                # The recorder goes in last so that what it records is the import and nothing
                # the probe itself did first (``gettempdir`` reads TEMP/TMP/TMPDIR).
                "import os",
                "seen = []",
                "real_get = os.environ.get",
                "os.environ.get = lambda k, *a: (seen.append(k), real_get(k, *a))[1]",
                "import adapters.search.brave",
                "print(sorted(p.name for p in set(root.iterdir()) - before_temp))",
                "print(sorted(p.name for p in set(cwd.iterdir()) - before_cwd))",
                "print(sorted(seen))",
            ]
        ),
        encoding="utf-8",
    )
    workdir = tmp_path / "work"
    workdir.mkdir()

    result_ = subprocess.run(
        [sys.executable, str(probe)], capture_output=True, text=True, cwd=workdir
    )
    assert result_.returncode == 0, result_.stderr
    temp_created, cwd_created, env_read = result_.stdout.strip().splitlines()
    assert temp_created == "[]", f"import touched the temp directory: {temp_created}"
    assert cwd_created == "[]", f"import touched the working directory: {cwd_created}"
    assert env_read == "[]", f"import read the environment: {env_read}"


def test_c2_no_module_level_call_can_do_anything() -> None:
    """The structural twin of the test above: nothing at import scope touches the outside."""
    safe_names = {"frozenset", "tuple", "list", "dict", "set"}

    def is_pure(call: ast.Call) -> bool:
        return isinstance(call.func, ast.Name) and call.func.id in safe_names

    tree = ast.parse(ADAPTER.read_text(encoding="utf-8"))
    offenders = [
        f"line {node.lineno}"
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and not is_pure(node.value)
    ]
    assert not offenders, offenders


def test_c3_the_adapter_never_reads_the_environment() -> None:
    """Credentials are injected. ``adapters/README.md``: reading env is the application's job.

    An adapter that reaches for ``BRAVE_API_KEY`` bills whichever key happened to be exported in
    the shell that started the process — including the shell running the tests.
    """
    tree = ast.parse(ADAPTER.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offenders += [
                f"line {node.lineno}: import {a.name}"
                for a in node.names
                if a.name.split(".")[0] == "os"
            ]
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] == "os":
                offenders.append(f"line {node.lineno}: from {node.module}")
        elif isinstance(node, ast.Attribute) and node.attr in {"environ", "getenv"}:
            offenders.append(f"line {node.lineno}: .{node.attr}")
        elif isinstance(node, ast.Name) and node.id in {"environ", "getenv"}:
            offenders.append(f"line {node.lineno}: {node.id}")
    assert not offenders, offenders


# -- D / E: the credential -------------------------------------------------

def test_d_construction_needs_a_key_and_makes_no_call() -> None:
    """Validated in the constructor, so a missing credential is found before work is batched."""
    for missing in ("", "   ", None):
        with pytest.raises(BraveSearchError) as raised:
            BraveSearch(api_key=missing, transport=FakeTransport(ok(result())))
        assert raised.value.code == SearchErrorCode.NOT_CONFIGURED

    transport = FakeTransport(ok(result()))
    BraveSearch(api_key=FAKE_KEY, transport=transport)
    assert transport.calls == 0, "constructing an adapter must not reach the provider"


def test_d2_there_is_no_default_key_anywhere_in_the_source() -> None:
    source = ADAPTER.read_text(encoding="utf-8")
    assert "api_key: str" in source or "api_key," in source
    assert not re.search(r"api_key\s*[:=]\s*[\"']", source), "a literal key-shaped default"
    assert not re.search(r"BS[A-Za-z]{2}[A-Za-z0-9_\-]{20,}", source), "a key-shaped string"


def test_e_the_key_never_appears_in_repr_str_or_an_error() -> None:
    adapter, _ = build(error(401, message=FAKE_KEY))
    assert FAKE_KEY not in repr(adapter)
    assert FAKE_KEY not in str(adapter)

    with pytest.raises(BraveSearchError) as raised:
        adapter.search("fictional query")

    exc = raised.value
    assert FAKE_KEY not in str(exc)
    assert FAKE_KEY not in repr(exc)


def test_e2_the_key_goes_in_the_header_and_only_there() -> None:
    adapter, transport = build()
    adapter.search("fictional query")

    request = transport.last
    assert request.headers["x-subscription-token"] == FAKE_KEY
    assert FAKE_KEY not in request.url
    assert FAKE_KEY not in json.dumps(request.params, ensure_ascii=False)
    assert [k for k, v in request.headers.items() if v == FAKE_KEY] == ["x-subscription-token"]


def test_e3_the_endpoint_and_the_version_are_the_callers_to_pin() -> None:
    """The version header is absent unless asked for; there is no guessed value in the source."""
    adapter, transport = build()
    adapter.search("fictional query")
    assert transport.last.url == DEFAULT_API_URL
    assert "api-version" not in transport.last.headers

    pinned, transport = build(api_version="2025-01-01")
    pinned.search("fictional query")
    assert transport.last.headers["api-version"] == "2025-01-01"


# -- F: the query ----------------------------------------------------------

@pytest.mark.parametrize(
    "query",
    [
        "베트남 수처리 설비 조달",
        "IoT-기반 수질 측정",
        'site:example.invalid "manual sampling"',
        "desalination   tender  2026",
    ],
)
def test_f_the_query_is_sent_exactly_as_the_core_wrote_it(query: str) -> None:
    """No expansion, no trimming, no lowercasing, no added terms — byte for byte."""
    adapter, transport = build()
    adapter.search(query)
    assert transport.last.query == query


def test_f2_the_request_is_a_closed_set_of_parameters() -> None:
    """A denylist leaks quietly every time the API grows a field; this is the allowlist."""
    adapter, transport = build()
    adapter.search("fictional query", country="VN", limit=7)
    assert set(transport.last.params) == set(REQUEST_PARAM_KEYS)

    plain, transport = build()
    plain.search("fictional query")
    assert set(transport.last.params) == set(REQUEST_PARAM_KEYS) - {"country"}


def test_f3_the_two_defaults_that_would_rewrite_the_request_are_turned_off() -> None:
    """The point of the whole parameter block, stated as an assertion.

    ``spellcheck`` substitutes a corrected query and searches that; ``operators`` reads
    punctuation in the query as syntax; ``text_decorations`` wraps matched terms in markup that
    would end up inside an evidence passage. All three default to on at the provider.
    """
    adapter, transport = build()
    adapter.search("fictional query")

    params = transport.last.params
    assert params["spellcheck"] == "false"
    assert params["operators"] == "false"
    assert params["text_decorations"] == "false"
    assert params["result_filter"] == "web"
    assert REQUEST_PARAMS == {
        "operators": "false",
        "result_filter": "web",
        "spellcheck": "false",
        "text_decorations": "false",
    }


def test_f4_nothing_that_would_generate_content_is_ever_requested() -> None:
    """A summariser or a rich callback would put generated text where a retrieval belongs."""
    adapter, transport = build()
    adapter.search("fictional query", country="VN")

    for forbidden in ("summary", "enable_rich_callback", "extra_snippets", "goggles",
                      "goggles_id", "freshness", "offset"):
        assert forbidden not in transport.last.params, forbidden


def test_f5_an_empty_query_is_refused_before_the_transport() -> None:
    adapter, transport = build()
    for empty in ("", "   ", "\n"):
        with pytest.raises(BraveSearchError) as raised:
            adapter.search(empty)
        assert raised.value.code == SearchErrorCode.INVALID_REQUEST
    assert transport.calls == 0


def test_f6_no_provider_side_query_ceiling_is_enforced_locally() -> None:
    """The party that knows the limit answers. A local guess rejects valid input when it moves."""
    adapter, transport = build()
    adapter.search("가" * 4000)
    assert len(transport.last.query) == 4000


# -- G: locale and region --------------------------------------------------

def test_g_country_is_passed_through_only_when_the_caller_gives_one() -> None:
    adapter, transport = build()
    adapter.search("fictional query", country="vn")
    assert transport.last.params["country"] == "VN", "the provider's parameter is upper case"

    plain, transport = build()
    plain.search("fictional query")
    assert "country" not in transport.last.params


def test_g2_the_result_echoes_the_callers_string_not_the_reshaped_one() -> None:
    """A record that disagreed with the request that produced it would be worse than useless."""
    adapter, _ = build()
    assert adapter.search("fictional query", country="vn")[0].country == "vn"


def test_g3_a_country_that_is_not_a_code_is_refused_locally() -> None:
    adapter, transport = build()
    for bad in ("Vietnam", "V", "VNM", "12", "v n"):
        with pytest.raises(BraveSearchError) as raised:
            adapter.search("fictional query", country=bad)
        assert raised.value.code == SearchErrorCode.INVALID_REQUEST, bad
    assert transport.calls == 0


def test_g4_no_location_or_locale_of_this_machine_is_ever_sent() -> None:
    """The implicit region selection the contract forbids, checked at the wire and in the source."""
    adapter, transport = build()
    adapter.search("fictional query")

    for header in transport.last.headers:
        assert not header.startswith("x-loc-"), header
    assert "search_lang" not in transport.last.params
    assert "ui_lang" not in transport.last.params

    source = ADAPTER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(a.name.split(".")[0] != "locale" for a in node.names), node.lineno
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] != "locale", node.lineno


def test_g5_scope_does_not_become_a_request_parameter() -> None:
    """``MarketScope`` is this harness's distinction, not the provider's.

    Mapping DOMESTIC onto a country code would be inventing a region; the two requests below are
    therefore identical, and the scope survives only on the result.
    """
    domestic, t1 = build()
    domestic.search("fictional query", scope=MarketScope.DOMESTIC)
    international, t2 = build()
    hits = international.search("fictional query", scope=MarketScope.INTERNATIONAL)

    assert t1.last.params == t2.last.params
    assert hits[0].market_scope is MarketScope.INTERNATIONAL


# -- H: result count -------------------------------------------------------

@pytest.mark.parametrize("limit", [1, 3, 5, 10, 20])
def test_h_the_callers_limit_is_what_is_requested(limit: int) -> None:
    """Passed through unchanged across the whole accepted range. Neither end is clamped."""
    adapter, transport = build()
    adapter.search("fictional query", limit=limit)
    assert transport.last.count == limit


@pytest.mark.parametrize("limit", [21, 25, 100, 1000])
def test_h2_a_limit_above_the_endpoint_maximum_is_refused_not_reduced(limit: int) -> None:
    """Silently returning twenty would answer a question nobody asked.

    ``limit`` is a research decision made in ``core/analysis/policy.py``. An adapter that
    trimmed it to what this provider happens to allow would hide the fact that the deployment's
    policy is not satisfiable by the wired provider — and would do it in the direction that
    looks like success. Lowering the policy or wiring a different provider is a decision for
    the layer that set the number.
    """
    adapter, transport = build()
    with pytest.raises(BraveSearchError) as raised:
        adapter.search("fictional query", limit=limit)

    assert raised.value.code == SearchErrorCode.INVALID_REQUEST
    assert transport.calls == 0, "refused before anything is billed"


def test_h2b_the_boundary_is_exactly_the_endpoint_maximum() -> None:
    """Twenty is accepted and sent as twenty; twenty-one is refused. No off-by-one either way."""
    assert MAX_RESULTS_PER_REQUEST == 20

    adapter, transport = build()
    adapter.search("fictional query", limit=MAX_RESULTS_PER_REQUEST)
    assert transport.last.count == MAX_RESULTS_PER_REQUEST

    with pytest.raises(BraveSearchError):
        adapter.search("fictional query", limit=MAX_RESULTS_PER_REQUEST + 1)


def test_h3_a_limit_below_one_is_refused_rather_than_quietly_meaning_something() -> None:
    adapter, transport = build()
    for bad in (0, -1):
        with pytest.raises(BraveSearchError) as raised:
            adapter.search("fictional query", limit=bad)
        assert raised.value.code == SearchErrorCode.INVALID_REQUEST
    assert transport.calls == 0


def test_h3b_the_count_parameter_is_the_limit_and_nothing_computed_from_it() -> None:
    """The structural twin, read off the syntax tree rather than the behaviour.

    A clamp is easy to reintroduce and hard to see in a diff — ``min(limit, 20)`` looks like
    defensive coding. So this pins the shape: the assignment to ``count`` is ``str(limit)``,
    one call, one bare name argument. Any arithmetic, ``min``, ``max`` or conditional in that
    position fails here, whichever direction it moves the value.
    """
    tree = ast.parse(ADAPTER.read_text(encoding="utf-8"))
    params_fn = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_params"
    )

    assignments = [
        node for node in ast.walk(params_fn)
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Subscript)
        and getattr(node.targets[0].slice, "value", None) == "count"
    ]
    assert len(assignments) == 1, "count is set in exactly one place"

    value = assignments[0].value
    assert isinstance(value, ast.Call), ast.dump(value)
    assert isinstance(value.func, ast.Name) and value.func.id == "str", ast.dump(value)
    assert len(value.args) == 1 and isinstance(value.args[0], ast.Name), ast.dump(value)
    assert value.args[0].id == "limit", ast.dump(value)


def test_h4_the_core_default_reaches_the_provider_unchanged() -> None:
    """``core/analysis/policy.py`` sets ``max_results_per_query``; nothing here overrides it."""
    from core.analysis.policy import DEFAULT_ANALYSIS_POLICY

    adapter, transport = build()
    adapter.search("fictional query", limit=DEFAULT_ANALYSIS_POLICY.max_results_per_query)
    assert transport.last.count == DEFAULT_ANALYSIS_POLICY.max_results_per_query


def test_h5_one_search_is_one_provider_request() -> None:
    """Whatever the limit, whatever comes back. A hidden second page is a hidden second bill."""
    adapter, transport = build(ok(*[result(url=f"https://example.invalid/{i}") for i in range(20)]))
    adapter.search("fictional query", limit=20)
    assert transport.calls == 1


# -- I: timeout ------------------------------------------------------------

def test_i_the_configured_timeout_reaches_the_transport() -> None:
    adapter, transport = build(timeout_seconds=4.5)
    adapter.search("fictional query")
    assert transport.last.timeout == 4.5


def test_i2_there_is_a_finite_default() -> None:
    assert 0 < DEFAULT_TIMEOUT_SECONDS < 600
    adapter, transport = build()
    adapter.search("fictional query")
    assert transport.last.timeout == DEFAULT_TIMEOUT_SECONDS


# -- J / K: retry ----------------------------------------------------------

def test_j_nothing_is_retried_by_default() -> None:
    """One attempt. A re-send transmits the query to a third party a second time."""
    assert RetryPolicy().max_attempts == 1

    adapter, transport = build(error(429), ok(result()))
    with pytest.raises(BraveSearchError) as raised:
        adapter.search("fictional query")

    assert raised.value.code == SearchErrorCode.RATE_LIMITED
    assert raised.value.attempts == 1
    assert transport.calls == 1


def test_k_an_explicit_policy_retries_and_stops() -> None:
    waits: list[float] = []
    adapter, transport = build(
        error(503),
        error(503),
        ok(result()),
        retry=RetryPolicy(max_attempts=3, backoff_seconds=0.5),
        sleep=waits.append,
    )
    assert len(adapter.search("fictional query")) == 1
    assert transport.calls == 3
    assert waits == [0.5, 1.0]


def test_k2_the_rate_limit_reset_header_decides_the_wait() -> None:
    """This provider sends no ``retry-after``; ``x-ratelimit-reset`` is the equivalent.

    Its first value is the burst window and the one a retry can wait out. The second is the
    monthly quota — a wait of sixteen days is not a retry, it is a bill.
    """
    assert reset_seconds({"x-ratelimit-reset": "1, 1419704"}) == 1.0
    assert reset_seconds({"x-ratelimit-reset": "  3 "}) == 3.0
    assert reset_seconds({"x-ratelimit-reset": "Mon, 21 Sep 2026 00:00:00 GMT"}) is None
    assert reset_seconds({}) is None

    waits: list[float] = []
    adapter, _ = build(
        error(429, headers={"x-ratelimit-reset": "2, 1419704"}),
        ok(result()),
        retry=RetryPolicy(max_attempts=2, backoff_seconds=9.0),
        sleep=waits.append,
    )
    adapter.search("fictional query")
    assert waits == [2.0], "the burst window, not the configured backoff and not the quota"


def test_k3_backoff_is_capped() -> None:
    policy = RetryPolicy(max_attempts=9, backoff_seconds=1.0, max_backoff_seconds=4.0)
    assert [policy.delay_for(n, None) for n in range(1, 6)] == [1.0, 2.0, 4.0, 4.0, 4.0]
    assert policy.delay_for(1, 999.0) == 4.0
    assert policy.delay_for(1, -5.0) == 0.0


@pytest.mark.parametrize(
    "status, code, retried",
    [
        (401, SearchErrorCode.AUTH_FAILED, False),
        (403, SearchErrorCode.AUTH_FAILED, False),
        (422, SearchErrorCode.INVALID_REQUEST, False),
        (404, SearchErrorCode.INVALID_REQUEST, False),
        (429, SearchErrorCode.RATE_LIMITED, True),
        (500, SearchErrorCode.PROVIDER_UNAVAILABLE, True),
        (503, SearchErrorCode.PROVIDER_UNAVAILABLE, True),
    ],
)
def test_k4_only_the_retryable_classes_are_retried(status: int, code: str, retried: bool) -> None:
    """A credential and a malformed query fail identically however many times they are sent."""
    assert (code in RetryPolicy().retry_on) is retried

    adapter, transport = build(
        error(status), ok(result()), retry=RetryPolicy(max_attempts=2), sleep=lambda _: None
    )
    with pytest.raises(BraveSearchError) if not retried else _nullcontext():
        adapter.search("fictional query")
    assert transport.calls == (2 if retried else 1)


def test_k5_a_malformed_response_is_not_retried() -> None:
    """Re-asking hides a changed response shape rather than fixing it."""
    assert SearchErrorCode.MALFORMED_RESPONSE not in RetryPolicy().retry_on

    adapter, transport = build(
        raw(200, {"web": "not an object"}),
        ok(result()),
        retry=RetryPolicy(max_attempts=3),
        sleep=lambda _: None,
    )
    with pytest.raises(BraveSearchError) as raised:
        adapter.search("fictional query")
    assert raised.value.code == SearchErrorCode.MALFORMED_RESPONSE
    assert transport.calls == 1


def test_k6_a_policy_cannot_ask_for_zero_attempts() -> None:
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=0)


class _nullcontext:
    def __enter__(self): return self
    def __exit__(self, *exc): return False


# -- L..Q: error mapping ---------------------------------------------------

def test_l_m_p_every_status_maps_to_a_stable_code() -> None:
    for status, code in (
        (401, SearchErrorCode.AUTH_FAILED),
        (403, SearchErrorCode.AUTH_FAILED),
        (429, SearchErrorCode.RATE_LIMITED),
        (500, SearchErrorCode.PROVIDER_UNAVAILABLE),
        (502, SearchErrorCode.PROVIDER_UNAVAILABLE),
        (400, SearchErrorCode.INVALID_REQUEST),
        (422, SearchErrorCode.INVALID_REQUEST),
    ):
        adapter, _ = build(error(status))
        with pytest.raises(BraveSearchError) as raised:
            adapter.search("fictional query")
        assert raised.value.code == code, status
        assert raised.value.status == status


def test_n_a_timeout_maps_to_a_timeout_however_it_arrives() -> None:
    """A read timeout is ``TimeoutError``; a connect timeout arrives wrapped in ``URLError``."""

    class Wrapped(OSError):
        def __init__(self) -> None:
            super().__init__("urlopen error")
            self.reason = TimeoutError("connect")

    for exc in (TimeoutError("read"), Wrapped()):
        adapter, _ = build(exc)
        with pytest.raises(BraveSearchError) as raised:
            adapter.search("fictional query")
        assert raised.value.code == SearchErrorCode.TIMEOUT, type(exc).__name__


def test_o_a_network_failure_maps_to_a_network_failure() -> None:
    for exc in (OSError("connection reset"), ConnectionRefusedError("refused")):
        adapter, _ = build(exc)
        with pytest.raises(BraveSearchError) as raised:
            adapter.search("fictional query")
        assert raised.value.code == SearchErrorCode.NETWORK_FAILED
        assert raised.value.exception_type == type(exc).__name__


@pytest.mark.parametrize(
    "body",
    [
        b"<html>gateway</html>",
        b"",
        [1, 2, 3],
        {"web": "not an object"},
        {"web": {"results": "not a list"}},
    ],
)
def test_q_a_response_that_is_not_a_search_body_is_malformed(body) -> None:
    adapter, _ = build(raw(200, body))
    with pytest.raises(BraveSearchError) as raised:
        adapter.search("fictional query")
    assert raised.value.code == SearchErrorCode.MALFORMED_RESPONSE
    assert raised.value.status == 200, "a 200 that could not be read was still billed"


def test_m2_a_rate_limit_is_an_exception_and_never_an_empty_result() -> None:
    """The failure this adapter must not have, stated on its own.

    ``core/analysis/research.py`` reads an empty list as "this query found nothing" and moves
    to the next one. If a ``429`` were mapped to ``[]``, a run that never reached the provider
    at all would be indistinguishable from a run that searched honestly and found nothing — and
    it would be indistinguishable in the direction that produces a confident-looking report
    resting on no retrieval. The whole stage would come back empty and quiet.

    Both halves are asserted together deliberately: an empty *answer* stays an empty answer, and
    a rate limit stays an exception. A change that collapsed the two would have to break one of
    the two lines below.
    """
    limited, _ = build(error(429, headers={"x-ratelimit-reset": "1, 1419704"}))
    with pytest.raises(BraveSearchError) as raised:
        limited.search("fictional query")
    assert raised.value.code == SearchErrorCode.RATE_LIMITED
    assert raised.value.status == 429

    empty, _ = build(ok())
    assert empty.search("fictional query") == []


def test_m3_no_failure_path_anywhere_returns_an_empty_list() -> None:
    """The general form: every failure raises, so no caller can mistake one for "nothing found"."""
    for script in (
        (error(401),),
        (error(403),),
        (error(422),),
        (error(429),),
        (error(500),),
        (error(503),),
        (TimeoutError("read"),),
        (OSError("reset"),),
        (raw(200, b"not json"),),
        (raw(200, {"web": {"results": "not a list"}}),),
    ):
        adapter, _ = build(*script)
        with pytest.raises(BraveSearchError):
            adapter.search("fictional query")


def test_q2_no_results_is_an_answer_not_an_error() -> None:
    """``core/analysis/research.py`` reads an empty list as "nothing found" and moves on.

    Raising here would turn that into an outage, and a stage that found nothing would look
    exactly like one whose credential expired.
    """
    for body in (web_body(), {"type": "search", "query": {}}, {"type": "search", "web": None}):
        adapter, _ = build(raw(200, body))
        assert adapter.search("fictional query") == []


def test_q3_the_providers_own_message_is_never_surfaced() -> None:
    """A 422 quotes the query that produced it, and the query describes the client."""
    import traceback

    secret = "베트남 수처리 조달 fictional-client-name"
    adapter, _ = build(error(422, message=secret))

    with pytest.raises(BraveSearchError) as raised:
        adapter.search(secret)

    exc = raised.value
    rendered = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    for surface in (str(exc), repr(exc), rendered):
        assert secret not in surface
    assert exc.__cause__ is None and exc.__context__ is None


def test_q4_every_raised_code_belongs_to_the_declared_set() -> None:
    adapter, _ = build()
    raised_codes: set[str] = set()

    for script, call in (
        ((error(401),), lambda a: a.search("q")),
        ((error(429),), lambda a: a.search("q")),
        ((error(422),), lambda a: a.search("q")),
        ((error(500),), lambda a: a.search("q")),
        ((TimeoutError("t"),), lambda a: a.search("q")),
        ((OSError("n"),), lambda a: a.search("q")),
        ((raw(200, b"nope"),), lambda a: a.search("q")),
        ((ok(result()),), lambda a: a.search("")),
        ((ok(result()),), lambda a: a.search("q", limit=0)),
        ((ok(result()),), lambda a: a.search("q", country="Vietnam")),
    ):
        adapter, _ = build(*script)
        with pytest.raises(BraveSearchError) as raised:
            call(adapter)
        raised_codes.add(raised.value.code)

    with pytest.raises(BraveSearchError) as raised:
        BraveSearch(api_key="", transport=FakeTransport(ok(result())))
    raised_codes.add(raised.value.code)

    assert raised_codes <= SEARCH_ERROR_CODES, raised_codes - SEARCH_ERROR_CODES
    assert SearchErrorCode.NOT_CONFIGURED in raised_codes


def test_q5_a_provider_failure_is_catchable_as_a_provider_failure() -> None:
    """A caller written against ``core/errors.py`` keeps working whichever adapter is wired."""
    adapter, _ = build(error(500))
    with pytest.raises(ProviderError):
        adapter.search("fictional query")


# -- R..V: response mapping ------------------------------------------------

def test_r_s_t_u_the_four_provenance_fields_are_copied_not_derived() -> None:
    adapter, _ = build(
        ok(
            result(
                title="  Fictional delta tender  ",
                url="https://example.invalid/tender?ref=abc&utm_source=x",
                description="  a fictional authority replaces manual sampling  ",
                profile={"name": "  Fictional Water Review  "},
            )
        )
    )
    hit = adapter.search("fictional query")[0]

    assert hit.title == "Fictional delta tender"
    assert hit.snippet == "a fictional authority replaces manual sampling"
    assert hit.publisher == "Fictional Water Review"
    assert hit.retrieved_at == FIXED_NOW
    assert hit.provider == "brave"
    assert hit.evidence_quality is Confidence.UNKNOWN
    # The URL is checked, never edited: no tracking parameter is stripped and no host is
    # canonicalised. Two addresses being "the same page" is a judgement this layer cannot make.
    assert hit.url == "https://example.invalid/tender?ref=abc&utm_source=x"


def test_s2_a_url_that_cannot_serve_as_provenance_rejects_its_result() -> None:
    """A reader checks a claim by opening the URL. Without a usable one there is nothing to open."""
    for bad in (None, "", "   ", "javascript:alert(1)", "example.invalid/x", 42,
                "https://example.invalid/" + "a" * MAX_URL_CHARS):
        adapter, _ = build(ok(result(url=bad), result(url="https://example.invalid/good")))
        hits = adapter.search("fictional query")
        assert [h.url for h in hits] == ["https://example.invalid/good"], bad


def test_r2_a_result_with_no_title_is_rejected() -> None:
    """``check_source_metadata`` requires one for SEARCH_RESULT, so an untitled result is unstorable."""
    for bad in (None, "", "   ", 7, {"text": "x"}):
        adapter, _ = build(ok(result(title=bad), result(title="Fictional good")))
        assert [h.title for h in adapter.search("q")] == ["Fictional good"], bad


def test_t2_an_empty_snippet_survives_the_adapter_and_the_core_drops_it() -> None:
    """The rule lives in ``core/research/sources.py``; a second copy here would drift from it."""
    from core.research.sources import ingest_search_results

    adapter, _ = build(ok(result(description=None), result(description="fictional passage")))
    hits = adapter.search("fictional query")
    assert [h.snippet for h in hits] == ["", "fictional passage"]

    sources, candidates = ingest_search_results(hits, project_id="proj_fictional")
    assert len(sources) == 1 and len(candidates) == 1


def test_t3_a_snippet_that_is_not_text_rejects_its_result() -> None:
    """Guessing at it would put an invented quotation into an evidence passage."""
    adapter, _ = build(ok(result(description={"text": "x"}), result(description="fictional")))
    assert [h.snippet for h in adapter.search("q")] == ["fictional"]


def test_u_one_retrieval_time_is_shared_by_a_batch_and_is_the_harness_clock() -> None:
    adapter, _ = build(ok(result(url="https://example.invalid/a"),
                          result(url="https://example.invalid/b")))
    hits = adapter.search("fictional query")
    assert {h.retrieved_at for h in hits} == {FIXED_NOW}


def test_u2_the_default_clock_is_the_one_every_other_timestamp_comes_from() -> None:
    """Injected for testability, not to invent a second time format."""
    from core.models import utc_now

    signature = __import__("inspect").signature(BraveSearch.__init__)
    assert signature.parameters["clock"].default is utc_now


def test_v_a_publication_date_is_never_invented() -> None:
    """The most consequential mapping decision in the adapter, asserted four ways.

    This endpoint's date field is documented as the page's "published **or last modified**"
    date, which is not a publication date. Writing it into one would make a six-year-old page
    touched last month look current in the record a reader trusts — and
    ``core/research/confidence.py`` reads ``source_date`` for exactly that judgement.
    """
    adapter, _ = build(
        ok(
            result(
                title="Fictional 2019 tender",
                description="published in 2019 according to this fictional passage",
                url="https://example.invalid/2019/03/tender",
                page_age="2026-08-01T00:00:00",
                page_fetched="2026-09-01T00:00:00",
                age="3 weeks ago",
            )
        )
    )
    hit = adapter.search("fictional query")[0]

    assert hit.published_date is None
    assert hit.retrieved_at == FIXED_NOW, "retrieval time is recorded; publication time is not"

    # The provider's date fields are not read at all, so there is nowhere a date could be
    # derived from even by accident.
    tokens = _code_tokens(ADAPTER)
    for derived in ("page_age", "page_fetched", "fetched_content_timestamp", "age"):
        assert derived not in tokens, (
            f"{derived} is read somewhere; nothing may derive a date from it"
        )
    assert "published_date" in tokens, "the field is set explicitly, to None, and not omitted"


def test_v2_the_source_record_keeps_retrieval_and_publication_apart() -> None:
    from core.research.sources import ingest_search_results

    adapter, _ = build(ok(result(page_age="2026-08-01T00:00:00")))
    sources, _ = ingest_search_results(adapter.search("q"), project_id="proj_fictional")

    assert sources[0].retrieved_at == FIXED_NOW
    assert sources[0].source_date is None


def test_v3a_publisher_carries_the_source_identity_the_core_asks_for() -> None:
    """The mapping is only legitimate because of what ``publisher`` means to the core.

    The provider guarantees ``profile.name`` to be a site identity, not a publishing
    organisation. The core's only *use* of the field is ``_authority_known``, whose question is
    "can we tell who is speaking" — an identity question — and whose module states that a named
    publisher is not a checked claim. This test pins that reading to the code it was read from,
    so that a future rewrite of either side cannot quietly turn identity into authority.
    """
    from core.research.confidence import _authority_known

    adapter, _ = build(ok(result(profile={"name": "Fictional Water Review"})))
    hit = adapter.search("fictional query")[0]
    assert hit.publisher == "Fictional Water Review"

    sources, _ = ingest_search_results([hit], project_id="proj_fictional")
    assert _authority_known(sources[0]) is True, "the core can tell who is speaking"

    # The core's own words, quoted from the two places the audit rested on. If either moves,
    # the mapping above has to be re-argued rather than inherited.
    # Whitespace-normalised, so that re-wrapping a docstring does not fail this for the wrong
    # reason — and does not let a rewording pass for the wrong reason either.
    confidence_src = re.sub(
        r"\s+",
        " ",
        (REPO_ROOT / "core" / "research" / "confidence.py").read_text(encoding="utf-8"),
    )
    assert "can we tell who is speaking" in confidence_src
    assert "a named publisher is not the same as a checked claim" in confidence_src


def test_v3b_a_publisher_never_raises_confidence_for_this_adapters_evidence() -> None:
    """And the safety net under the decision: snippet evidence is capped before authority runs.

    Even with a publisher present, corroboration high and the source recent, a result from this
    adapter cannot exceed MEDIUM — ``_is_unverified_snippet`` returns first. So a wrong or
    over-generous publisher value cannot buy confidence; it is provenance a reader sees.
    """
    from core.models import EvidenceType
    from core.research.confidence import ConfidenceSignals, ceiling_for
    from core.research.policy import SNIPPET_LOCATOR

    adapter, _ = build(ok(result(profile={"name": "Fictional Water Review"})))
    sources, candidates = ingest_search_results(
        adapter.search("fictional query"), project_id="proj_fictional"
    )
    assert candidates[0].locator == SNIPPET_LOCATOR

    ceiling = ceiling_for(
        EvidenceType.FACT,
        ConfidenceSignals(
            source=sources[0],
            locator=SNIPPET_LOCATOR,
            corroborating_source_count=9,
            today="2026-09-20",
        ),
    )
    assert ceiling is Confidence.MEDIUM


def test_v3_a_publisher_is_absent_rather_than_guessed_or_truncated() -> None:
    """Its absence limits confidence, which is a working answer. A hostname would be a fiction."""
    for missing in (None, {}, {"name": ""}, {"name": 5}, {"name": "x" * (MAX_PUBLISHER_CHARS + 1)}):
        adapter, _ = build(ok(result(url="https://fictional-institute.invalid/a",
                                     profile=missing)))
        hit = adapter.search("fictional query")[0]
        assert hit.publisher is None, missing
        assert "fictional-institute" not in (hit.publisher or ""), "derived from the hostname"


# -- W: ranking is not priority --------------------------------------------

def test_w_provider_order_is_preserved_and_is_not_a_priority() -> None:
    """Result order is a search ranking. ``sales_priority`` comes from evidence, elsewhere.

    Both halves matter: the order is passed through unchanged (so nothing reorders on a guess),
    and no band, score or rank rides along with it.
    """
    urls = [f"https://example.invalid/{i}" for i in range(4)]
    adapter, _ = build(ok(*[result(url=u, title=f"Fictional {i}") for i, u in enumerate(urls)]))
    hits = adapter.search("fictional query")

    assert [h.url for h in hits] == urls

    # Checked against what the module *executes*, not against its prose. A docstring that names
    # ``sales_priority`` in order to say the adapter has nothing to do with it is the opposite
    # of a violation, and a grep over the raw text cannot tell the two apart.
    for forbidden in ("SalesPriority", "sales_priority", "PriorityDecision", "priority",
                      "P1", "P2", "P3", "rank", "score"):
        assert forbidden not in _code_tokens(ADAPTER), forbidden
    assert not hasattr(hits[0], "rank") and not hasattr(hits[0], "score")


def test_w2_no_provider_score_is_mapped_onto_a_result() -> None:
    adapter, _ = build(ok(result(score=0.99, rank=1)))
    hit = adapter.search("fictional query")[0]
    assert {f for f in vars(hit)} == {f for f in vars(SearchResult(title="t", snippet="s"))}


# -- X: no crawling, no dedupe ---------------------------------------------

def test_x_the_adapter_never_follows_a_url_it_received() -> None:
    """Search is not a crawler. One request per call, to the configured endpoint, and no other."""
    adapter, transport = build(ok(result(url="https://example.invalid/page")))
    adapter.search("fictional query")

    assert transport.calls == 1
    assert {r.url for r in transport.requests} == {DEFAULT_API_URL}


def test_x2_duplicate_results_are_returned_as_the_provider_sent_them() -> None:
    """Deciding two records are the same thing is entity resolution, which stays out of here."""
    adapter, _ = build(
        ok(
            result(url="https://example.invalid/same", title="Fictional A"),
            result(url="https://example.invalid/same", title="Fictional A"),
            result(url="https://example.invalid/same/", title="Fictional A "),
        )
    )
    assert len(adapter.search("fictional query")) == 3


def test_x3_the_source_of_the_adapter_contains_no_fuzzy_matching_machinery() -> None:
    tokens = {token.lower() for token in _code_tokens(ADAPTER)}
    for forbidden in ("difflib", "ratio", "embedding", "levenshtein", "fuzz", "dedupe",
                      "normalize", "canonicalize"):
        assert forbidden not in tokens, forbidden


# -- Y / Z / AD: logging, persistence, canary ------------------------------

#: Fictional throughout — a query, a company, a filename, an address, a number and a token.
CANARIES = {
    "query": "ZQX-SEARCH-CANARY-7f2a 가상삼각수처리공사 조달 계획",
    "company": "가상삼각수처리공사",
    "filename": "2026년_메콩델타_고객제안_v3.docx",
    "email": "fictional.buyer@example.invalid",
    "phone": "+84-28-0000-0000",
    "snippet": "ZQX-SNIPPET-CANARY-4d1c 현장 인력이 수동 채수에 의존한다",
    "api_key": FAKE_KEY,
}


def test_y_the_adapter_has_no_logger_and_no_output_channel() -> None:
    """The cheapest way not to log a query is to have nowhere to log it to."""
    tree = ast.parse(ADAPTER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(a.name.split(".")[0] != "logging" for a in node.names), node.lineno
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] != "logging", node.lineno
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"print", "open", "input"}, f"line {node.lineno}"


def test_ad_no_canary_reaches_a_log_a_stream_or_an_error(caplog, capsys) -> None:
    """Query, snippet, URL, publisher and credential, across a success and a failure path."""
    import traceback

    caplog.set_level(0)
    adapter, _ = build(
        ok(
            result(
                title=CANARIES["company"],
                url=f"https://example.invalid/{CANARIES['filename']}",
                description=CANARIES["snippet"],
                profile={"name": CANARIES["email"]},
            )
        ),
        error(422, message=CANARIES["snippet"]),
    )
    hits = adapter.search(CANARIES["query"], country="VN")
    assert hits[0].snippet == CANARIES["snippet"]

    with pytest.raises(BraveSearchError) as raised:
        adapter.search(CANARIES["query"])

    exc = raised.value
    surfaces = [
        caplog.text,
        capsys.readouterr().out,
        capsys.readouterr().err,
        str(exc),
        repr(exc),
        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        repr(adapter),
        str(adapter),
    ]
    for surface in surfaces:
        for label, canary in CANARIES.items():
            assert canary not in surface, f"{label} leaked into a surface"


def test_ad2_transmitted_is_not_the_same_as_leaked() -> None:
    """The control case, and the distinction the whole privacy story rests on.

    The query **is** sent to the provider — that is what a search is, and ``docs/privacy.md``
    section 0 says so. What must not happen is the same text appearing in a log line, an
    exception or a file. A canary test with no positive half proves nothing: it would pass on an
    adapter that sent an empty query.
    """
    adapter, transport = build()
    adapter.search(CANARIES["query"], country="VN")
    assert transport.last.query == CANARIES["query"], "the query must actually be transmitted"


def test_ad3_usage_is_opt_in_counts_only_and_kept_nowhere() -> None:
    seen: list[BraveSearchUsage] = []
    adapter, _ = build(
        ok(result(description=CANARIES["snippet"]), result(url="not-a-url")),
        usage_sink=seen.append,
    )
    adapter.search(CANARIES["query"], country="VN", limit=9)

    assert len(seen) == 1
    usage = seen[0]
    assert usage.returned_count == 2 and usage.mapped_count == 1 and usage.rejected_count == 1
    assert usage.status == 200 and usage.attempts == 1 and usage.limit == 9
    assert usage.query_chars == len(CANARIES["query"])
    assert usage.country == "VN"

    rendered = json.dumps(usage.as_log_fields(), ensure_ascii=False)
    for label, canary in CANARIES.items():
        assert canary not in rendered, f"{label} reached the usage record"

    quiet, _ = build(ok(result()))
    quiet.search("fictional query")  # no sink: nothing is recorded, not even in memory
    assert not hasattr(quiet, "last_usage")


def test_y_z_a_full_run_leaves_no_file_anywhere(tmp_path: Path, monkeypatch) -> None:
    """No cache, no transcript, no debug dump — on the success path or the failure paths."""
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    temp_root = Path(tempfile.gettempdir())
    before_temp = set(temp_root.iterdir())

    adapter, _ = build(
        ok(result()),
        error(500),
        TimeoutError("read"),
        raw(200, b"not json"),
        error(401),
    )
    adapter.search("fictional query")
    for _ in range(4):
        with pytest.raises(BraveSearchError):
            adapter.search("fictional query")

    assert set(workdir.iterdir()) == set(), "the adapter wrote into the working directory"
    assert set(temp_root.iterdir()) - before_temp == set(), "the adapter wrote a temp file"


def test_z2_the_adapter_holds_no_cache_between_calls() -> None:
    """The same query twice is two requests. A cache would make a stale snippet look retrieved."""
    adapter, transport = build(ok(result()))
    adapter.search("fictional query")
    adapter.search("fictional query")
    assert transport.calls == 2


# -- AA: the network boundary ----------------------------------------------

def test_aa_the_core_cannot_see_this_adapter_at_all() -> None:
    """The dependency runs one way: adapters -> core."""
    for path in sorted((REPO_ROOT / "core").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        assert "brave" not in path.read_text(encoding="utf-8").lower(), path.name


def test_aa2_this_adapter_does_not_import_another_adapter() -> None:
    """A search deployment must not acquire a dependency on an LLM vendor's module."""
    tree = ast.parse(ADAPTER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        module = None
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
        elif isinstance(node, ast.Import):
            module = node.names[0].name
        if module and module.startswith("adapters"):
            pytest.fail(f"line {node.lineno}: {module}")


def test_aa3_the_network_import_is_lazy() -> None:
    """``urllib`` pulls in ``ssl``. Defining this adapter does not need a TLS library loaded."""
    tree = ast.parse(ADAPTER.read_text(encoding="utf-8"))
    top_level = {
        alias.name.split(".")[0]
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "urllib" not in top_level


# -- AC: the real provider -------------------------------------------------
#
# Two gates, deliberately redundant, and deliberately *not* ``BRAVE_API_KEY``: an environment
# left over from another task must not be able to start billing. The same reasoning as
# ``test_llm_anthropic.py``'s live gate.

LIVE_FLAG = "HARNESS_SEARCH_LIVE_TEST"
LIVE_KEY = "HARNESS_SEARCH_LIVE_API_KEY"


def live_key(env) -> str | None:
    """The credential for a live run, or ``None`` — which is the normal answer."""
    if env.get(LIVE_FLAG, "").strip() != "1":
        return None
    return env.get(LIVE_KEY, "").strip() or None


def test_ac_a_credential_in_the_environment_does_not_enable_a_live_test() -> None:
    """Presence of a key is not consent to spend it."""
    assert live_key({}) is None
    assert live_key({"BRAVE_API_KEY": "whatever"}) is None
    assert live_key({"BRAVE_SEARCH_API_KEY": "whatever"}) is None
    assert live_key({LIVE_KEY: "whatever"}) is None
    assert live_key({LIVE_FLAG: "1"}) is None
    assert live_key({LIVE_FLAG: "1", LIVE_KEY: "  "}) is None
    assert live_key({LIVE_FLAG: "1", LIVE_KEY: "k"}) == "k"


@pytest.mark.skipif(
    live_key(__import__("os").environ) is None,
    reason=(
        f"live provider test not requested: set {LIVE_FLAG}=1 and {LIVE_KEY} together. "
        "Without both this is NOT_RUN, and the suite stays offline."
    ),
)
def test_ac2_the_real_provider_answers_the_contract() -> None:
    """The only search test that spends money. Opt-in, never in CI.

    It asks for the smallest result set the harness ever asks for, and checks the thing an
    offline test cannot: that a real response still maps onto the provenance fields this adapter
    claims it does — and that a real ``page_age`` still does not become a publication date.
    """
    import os

    from core.evidence import check_source_metadata
    from core.research.sources import ingest_search_results

    adapter = BraveSearch(
        api_key=live_key(os.environ),
        timeout_seconds=30.0,
        retry=RetryPolicy(max_attempts=3),
    )
    hits = adapter.search("water treatment tender", limit=3)

    assert hits, "a live search returned nothing; check the plan's quota"
    for hit in hits:
        assert hit.title and hit.snippet is not None and hit.url
        assert hit.retrieved_at and hit.published_date is None
        assert hit.provider == "brave"
        assert hit.evidence_quality is Confidence.UNKNOWN

    sources, _ = ingest_search_results(hits, project_id="proj_live")
    for source in sources:
        assert check_source_metadata(source) == []


# -- helpers this file relies on -------------------------------------------

def test_the_fake_transport_is_not_hiding_a_real_one() -> None:
    """If the fake ever stopped recording, most of this file would pass vacuously."""
    adapter, transport = build(ok(result(title="Fictional recorded")))
    hits = adapter.search("본문 질의", limit=2)

    assert transport.calls == 1
    assert transport.last.params["q"] == "본문 질의"
    assert transport.last.params["count"] == "2"
    assert hits[0].title == "Fictional recorded"
