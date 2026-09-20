# -*- coding: utf-8 -*-
"""The Anthropic adapter: everything that is true of this provider and not of the contract.

``test_llm_contract.py`` checks what every ``LLMProvider`` must do. This file checks the
things that only exist because this one talks to a paid, remote, third-party service —
credential handling, request construction, retry, error mapping, and the leak surfaces that
come with all three.

**No test here has a credential and none opens a socket.** The adapter takes its transport as
a constructor argument, so the whole of it can be driven from ``fake_transport.py``. The one
test that would use a real provider is skipped unless two environment variables are set
together, and there is a test below asserting that a stray ``ANTHROPIC_API_KEY`` is not one of
them.
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

from adapters.llm.anthropic import (
    DEFAULT_API_URL,
    DEFAULT_API_VERSION,
    DEFAULT_TIMEOUT_SECONDS,
    EVIDENCE_DIRECTIVE,
    JSON_DIRECTIVE,
    LANGUAGE_DIRECTIVE,
    LLM_ERROR_CODES,
    REQUEST_BODY_KEYS,
    SUMMARY_DIRECTIVE,
    AnthropicLLM,
    AnthropicLLMError,
    AnthropicStructuredOutputError,
    AnthropicUsage,
    LLMErrorCode,
    RetryPolicy,
    build_system,
)
from core.errors import ProviderError, StructuredOutputError
from core.research.output_schemas import FINDING_BATCH
from fake_transport import FakeTransport, error, message_body, ok, raw, schema_responder

REPO_ROOT = Path(__file__).resolve().parent.parent
ADAPTER = REPO_ROOT / "adapters" / "llm" / "anthropic.py"

#: Fictional. This repository is public (``HARNESS.md`` section 9) and a string shaped like a
#: credential is treated as one by a secret scanner and by a careless reader alike.
FAKE_KEY = "sk-fictional-not-a-real-key-0000"
FAKE_MODEL = "fictional-model-1"

#: The budget these tests happen to use. A test fixture value, **not a default** — the adapter
#: has none, and every construction in this file passes one explicitly, exactly as an
#: application would have to.
TEST_MAX_TOKENS = 2048


def build(*script, **kwargs) -> tuple[AnthropicLLM, FakeTransport]:
    """An adapter wired to a scripted transport. Every test starts here."""
    transport = FakeTransport(*(script or (ok("[fake] answer"),)))
    kwargs.setdefault("api_key", FAKE_KEY)
    kwargs.setdefault("model", FAKE_MODEL)
    kwargs.setdefault("max_tokens", TEST_MAX_TOKENS)
    return AnthropicLLM(transport=transport, **kwargs), transport


# -- C: import side effects ------------------------------------------------

def test_c_importing_the_module_touches_nothing(tmp_path: Path) -> None:
    """Import must not read the environment, open a socket, or leave a file anywhere.

    A subprocess rather than ``importlib.reload``: a reload does not repeat import-time work
    and rebinds the exception classes, after which every ``pytest.raises`` in this file
    silently stops matching (see the same note in ``test_storage_sqlite.py``).
    """
    probe = tmp_path / "probe.py"
    probe.write_text(
        "\n".join(
            [
                "import pathlib, sys, tempfile",
                f"sys.path.insert(0, {str(REPO_ROOT)!r})",
                "import socket",
                # The class itself is left alone: ``ssl`` subclasses it at import time, so
                # replacing it breaks the import for a reason that has nothing to do with
                # this adapter. Patching the method that actually reaches the network says
                # the same thing without that.
                "def _refuse(*a, **k):",
                "    raise AssertionError('import opened a socket')",
                "socket.socket.connect = _refuse",
                "socket.create_connection = _refuse",
                "root = pathlib.Path(tempfile.gettempdir())",
                "cwd = pathlib.Path.cwd()",
                "before_temp, before_cwd = set(root.iterdir()), set(cwd.iterdir())",
                # The recorder goes in last so that what it records is the import and
                # nothing the probe itself did first (``gettempdir`` reads TEMP/TMP/TMPDIR).
                "import os",
                "seen = []",
                "real_get = os.environ.get",
                "os.environ.get = lambda k, *a: (seen.append(k), real_get(k, *a))[1]",
                "import adapters.llm.anthropic",
                "print(sorted(p.name for p in set(root.iterdir()) - before_temp))",
                "print(sorted(p.name for p in set(cwd.iterdir()) - before_cwd))",
                "print(sorted(seen))",
            ]
        ),
        encoding="utf-8",
    )
    workdir = tmp_path / "work"
    workdir.mkdir()

    result = subprocess.run(
        [sys.executable, str(probe)], capture_output=True, text=True, cwd=workdir
    )
    assert result.returncode == 0, result.stderr
    temp_created, cwd_created, env_read = result.stdout.strip().splitlines()
    assert temp_created == "[]", f"import touched the temp directory: {temp_created}"
    assert cwd_created == "[]", f"import touched the working directory: {cwd_created}"
    assert env_read == "[]", f"import read the environment: {env_read}"


def test_c2_no_module_level_call_can_do_anything() -> None:
    """The structural twin of the test above: nothing at import scope touches the outside.

    The allowed calls are pure constructors — the same ones ``core/errors.py`` uses to build
    its code set. Anything else evaluated at module scope is the thing this rule is about: a
    client built on import, a path read, a default looked up in the environment.
    """
    safe_names = {"frozenset", "tuple", "list", "dict", "set"}
    safe_attributes = {("re", "compile")}

    def is_pure(call: ast.Call) -> bool:
        if isinstance(call.func, ast.Name):
            return call.func.id in safe_names
        if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name):
            return (call.func.value.id, call.func.attr) in safe_attributes
        return False

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

    An adapter that reaches for ``ANTHROPIC_API_KEY`` bills whichever key happened to be
    exported in the shell that started the process — including the shell running the tests.
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


# -- D / E / F: credential and model ---------------------------------------

def test_d_construction_needs_a_key_and_makes_no_call() -> None:
    """The key is required at construction, and construction is not a network call."""
    llm, transport = build()
    assert transport.calls == 0

    for bad in ("", "   ", None):
        with pytest.raises(AnthropicLLMError) as raised:
            AnthropicLLM(
                api_key=bad,
                model=FAKE_MODEL,
                max_tokens=TEST_MAX_TOKENS,
                transport=FakeTransport(ok("x")),
            )
        assert raised.value.code == LLMErrorCode.NOT_CONFIGURED


def test_d2_there_is_no_default_key_anywhere_in_the_source() -> None:
    """A sample key in a public repository is a key, whatever the comment beside it says."""
    source = ADAPTER.read_text(encoding="utf-8")
    assert not re.search(r"sk-[A-Za-z0-9_\-]{8,}", source), "the adapter contains a key-shaped string"


def test_e_the_key_never_appears_in_repr_str_or_an_error() -> None:
    llm, _ = build(error(401))
    assert FAKE_KEY not in repr(llm)
    assert FAKE_KEY not in str(llm)
    assert FAKE_KEY not in str(vars(llm).get("_model", ""))

    with pytest.raises(AnthropicLLMError) as raised:
        llm.generate("무엇이든")
    exc = raised.value
    assert FAKE_KEY not in str(exc)
    assert FAKE_KEY not in repr(exc)

    import traceback

    formatted = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    assert FAKE_KEY not in formatted


def test_e2_the_key_goes_in_the_header_and_only_there() -> None:
    """It has to be transmitted — that is what it is for. It must be nowhere else."""
    llm, transport = build()
    llm.generate("무엇이든")
    request = transport.last
    assert request.headers["x-api-key"] == FAKE_KEY
    assert FAKE_KEY not in request.body.decode("utf-8")
    assert FAKE_KEY not in request.url


def test_f_the_model_is_the_callers_and_has_no_default() -> None:
    """No ``latest``, no ``best``, no default. The model changes what the analysis says."""
    import inspect

    parameters = inspect.signature(AnthropicLLM.__init__).parameters
    assert parameters["model"].default is inspect.Parameter.empty
    assert parameters["api_key"].default is inspect.Parameter.empty

    llm, transport = build(model="fictional-model-2")
    llm.generate("무엇이든")
    assert transport.last.payload["model"] == "fictional-model-2"

    source = ADAPTER.read_text(encoding="utf-8")
    for word in ("claude-", "-latest", "sonnet", "opus", "haiku"):
        assert word not in source.lower(), f"the adapter names a model: {word}"


# -- G: timeout ------------------------------------------------------------

def test_g_the_configured_timeout_reaches_the_transport() -> None:
    llm, transport = build(timeout_seconds=12.5)
    llm.generate("무엇이든")
    assert transport.last.timeout == 12.5


def test_g2_there_is_a_finite_default() -> None:
    """A provider call with no timeout hangs a background run for ever."""
    assert isinstance(DEFAULT_TIMEOUT_SECONDS, float) and 0 < DEFAULT_TIMEOUT_SECONDS < 600
    llm, transport = build()
    llm.generate("무엇이든")
    assert transport.last.timeout == DEFAULT_TIMEOUT_SECONDS


# -- H: retry --------------------------------------------------------------

def test_h_nothing_is_retried_by_default() -> None:
    """The default is one attempt. A retry re-transmits the client's evidence and bills again."""
    assert RetryPolicy().max_attempts == 1

    llm, transport = build(error(429), error(429), ok("late"))
    with pytest.raises(AnthropicLLMError) as raised:
        llm.generate("무엇이든")
    assert raised.value.code == LLMErrorCode.RATE_LIMITED
    assert transport.calls == 1, "the default policy re-sent the request"


def test_h2_an_explicit_policy_retries_and_stops() -> None:
    waits: list[float] = []
    llm, transport = build(
        error(429),
        error(503),
        ok("recovered"),
        retry=RetryPolicy(max_attempts=3, backoff_seconds=2.0, backoff_multiplier=3.0),
        sleep=waits.append,
    )
    assert llm.generate("무엇이든") == "recovered"
    assert transport.calls == 3
    assert waits == [2.0, 6.0], "backoff should be exponential from the configured base"


def test_h3_backoff_is_capped_and_retry_after_wins() -> None:
    policy = RetryPolicy(max_attempts=9, backoff_seconds=1.0, max_backoff_seconds=5.0)
    assert policy.delay_for(8, None) == 5.0
    assert policy.delay_for(1, 3.0) == 3.0
    assert policy.delay_for(1, 999.0) == 5.0, "retry-after is still capped"

    waits: list[float] = []
    llm, transport = build(
        error(429, headers={"retry-after": "4"}),
        ok("ok"),
        retry=RetryPolicy(max_attempts=2, backoff_seconds=1.0),
        sleep=waits.append,
    )
    llm.generate("무엇이든")
    assert waits == [4.0]


def test_h4_only_the_listed_codes_are_retried() -> None:
    """Auth and invalid-request fail the same way however often they are sent."""
    for status in (400, 401, 403, 404, 422):
        llm, transport = build(error(status), ok("never reached"), retry=RetryPolicy(max_attempts=4))
        with pytest.raises(AnthropicLLMError):
            llm.generate("무엇이든")
        assert transport.calls == 1, f"{status} was retried"


def test_h5_a_schema_failure_is_not_retried() -> None:
    """Resampling until the model agrees is not a transport concern, and hides a broken prompt."""
    llm, transport = build(
        ok("not json at all"), ok('{"findings": []}'), retry=RetryPolicy(max_attempts=3)
    )
    with pytest.raises(StructuredOutputError) as raised:
        llm.generate_structured("무엇이든", schema=FINDING_BATCH)
    assert raised.value.code == LLMErrorCode.OUTPUT_NOT_JSON
    assert transport.calls == 1


def test_h6_a_policy_cannot_ask_for_zero_attempts() -> None:
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=0)


# -- I / J / K: request mapping --------------------------------------------

def test_i_the_request_is_a_messages_call_with_the_expected_fields() -> None:
    llm, transport = build(max_tokens=321)
    llm.generate("본문")
    request = transport.last

    assert request.url == DEFAULT_API_URL
    assert request.headers["anthropic-version"] == DEFAULT_API_VERSION
    assert request.headers["content-type"] == "application/json"

    payload = request.payload
    assert payload["model"] == FAKE_MODEL
    assert payload["max_tokens"] == 321
    assert payload["messages"] == [{"role": "user", "content": "본문"}]


@pytest.mark.parametrize(
    "call",
    [
        lambda llm: llm.generate("본문", system="s"),
        lambda llm: llm.generate_structured("본문", schema=FINDING_BATCH),
        lambda llm: llm.analyze("본문", evidence=["[E1] a"], schema=FINDING_BATCH),
        lambda llm: llm.summarize("본문"),
    ],
    ids=["generate", "generate_structured", "analyze", "summarize"],
)
def test_i2_the_request_body_is_a_closed_set_of_keys(call) -> None:
    """An allowlist, not a list of things not to send.

    A denylist passes until the day somebody adds a field, which is exactly how a sampling
    control or a ``thinking`` block would arrive without anyone deciding it should.
    """
    llm, transport = build(schema_responder)
    call(llm)
    assert tuple(sorted(transport.last.payload)) == REQUEST_BODY_KEYS


def test_i3_no_sampling_control_and_no_thinking_block_is_ever_sent() -> None:
    """Stated by name as well, because the reason differs for each.

    Sampling semantics differ between providers and between models of one provider, and some
    models constrain or reject these outright. The adapter does not set them and does not
    translate between them. ``thinking`` is likewise the model's behaviour, not the harness's
    policy — see ``REQUEST_BODY_KEYS``.
    """
    llm, transport = build(schema_responder, schema_responder, schema_responder, ok("s"))
    llm.generate("본문", system="s")
    llm.generate_structured("본문", schema=FINDING_BATCH)
    llm.analyze("본문", evidence=["[E1] a"], schema=FINDING_BATCH)
    llm.summarize("본문")

    forbidden = (
        "temperature", "top_p", "top_k", "thinking",
        "tools", "tool_choice", "stream", "stop_sequences", "service_tier", "metadata",
    )
    for request in transport.requests:
        for key in forbidden:
            assert key not in request.payload, f"the adapter sent {key}"


def test_i4_the_constructor_has_no_sampling_knob_either() -> None:
    """Absent from the request because it is absent from the adapter, not merely defaulted off."""
    import inspect

    parameters = set(inspect.signature(AnthropicLLM.__init__).parameters)
    assert not parameters & {"temperature", "top_p", "top_k", "thinking", "tools", "stream"}

    source = ADAPTER.read_text(encoding="utf-8")
    body_region = source.split("def _body", 1)[1].split("def ", 1)[0]
    for key in ("temperature", "top_p", "top_k", "thinking"):
        assert key not in body_region


# -- generation budget: the caller supplies it, and there is no default ----
#
# How many tokens an answer may cost follows from what a deployment is for and what it is
# willing to spend. That is a policy, and policy selection is the application layer's job —
# a default here would be the adapter making it for every deployment that forgot to.

def test_budget_a_max_tokens_cannot_be_omitted() -> None:
    """Required, on the same terms as ``api_key`` and ``model``."""
    import inspect

    parameters = inspect.signature(AnthropicLLM.__init__).parameters
    for name in ("api_key", "model", "max_tokens"):
        assert parameters[name].default is inspect.Parameter.empty, f"{name} has a default"
        assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY, name

    with pytest.raises(TypeError):
        AnthropicLLM(
            api_key=FAKE_KEY, model=FAKE_MODEL, transport=FakeTransport(ok("x"))
        )


def test_budget_a2_no_module_level_budget_survives_anywhere() -> None:
    """``DEFAULT_MAX_TOKENS`` is gone. Nothing may reintroduce "the adapter's budget"."""
    import adapters.llm.anthropic as module

    assert not hasattr(module, "DEFAULT_MAX_TOKENS")
    assert not [
        name
        for name in vars(module)
        if "MAX_TOKEN" in name.upper() or "BUDGET" in name.upper()
    ]


def test_budget_b_caller_supplied_1024_is_sent_exactly() -> None:
    llm, transport = build(max_tokens=1024)
    llm.generate("본문")
    assert transport.last.payload["max_tokens"] == 1024


def test_budget_c_caller_supplied_4096_is_sent_exactly() -> None:
    llm, transport = build(max_tokens=4096)
    llm.generate("본문")
    assert transport.last.payload["max_tokens"] == 4096


@pytest.mark.parametrize("value", [1, 64, 1024, 4096, 8192, 64000])
def test_budget_c2_whatever_is_given_is_what_goes_out(value: int) -> None:
    llm, transport = build(max_tokens=value)
    llm.generate("본문")
    assert transport.last.payload["max_tokens"] == value


def test_budget_d_the_same_budget_survives_a_change_of_model() -> None:
    """Different models, one budget the caller chose. Nothing in between rewrites it."""
    for model in ("fictional-model-1", "fictional-model-2-xl", "some-other-vendor-model"):
        llm, transport = build(model=model, max_tokens=1234)
        llm.generate("본문")
        assert transport.last.payload["max_tokens"] == 1234, model


def test_budget_e_the_budget_is_never_derived_from_the_model_name() -> None:
    """Structural, not only behavioural: there is nothing here that could derive one.

    A per-model ceiling table is wrong on the day a model is added and silently wrong on the
    day one changes. This adapter does not know what any given model allows, and does not
    pretend to — the provider rejects what it will not accept, and that arrives as
    ``LLM_INVALID_REQUEST`` from the only party that actually knows.
    """
    source = ADAPTER.read_text(encoding="utf-8")
    body_region = source.split("def _body", 1)[1].split("    def ", 1)[0]
    assert '"max_tokens": self._max_tokens' in body_region

    tree = ast.parse(source)
    body_fn = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_body"
    )
    assert not [n for n in ast.walk(body_fn) if isinstance(n, ast.Call)], "_body computes"

    # ``_max_tokens`` is assigned once, from the parameter, and never touched again.
    assignments = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Attribute) and n.attr == "_max_tokens"
        and isinstance(n.ctx, ast.Store)
    ]
    assert len(assignments) == 1, "the budget is written more than once"

    # And no model name is mentioned anywhere near a number.
    for word in ("claude-", "sonnet", "opus", "haiku", "gpt-", "gemini"):
        assert word not in source.lower(), f"the adapter names a model: {word}"


@pytest.mark.parametrize(
    "value",
    [True, False, 0, -1, -4096, 1.5, 4096.0, "4096", None, [], object()],
    ids=[
        "True", "False", "zero", "negative", "very-negative",
        "float", "whole-float", "string", "None", "list", "object",
    ],
)
def test_budget_f_g_only_a_positive_int_is_accepted(value) -> None:
    """``bool`` first, because it is an ``int``: ``max_tokens=True`` would send ``true``.

    Checked rather than coerced — ``int("4096")`` and ``int(4096.9)`` both succeed, and both
    mean the caller did not send what they thought they sent.
    """
    with pytest.raises(AnthropicLLMError) as raised:
        AnthropicLLM(
            api_key=FAKE_KEY,
            model=FAKE_MODEL,
            max_tokens=value,
            transport=FakeTransport(ok("x")),
        )
    assert raised.value.code == LLMErrorCode.NOT_CONFIGURED


def test_budget_g2_validation_happens_before_any_call_is_made() -> None:
    transport = FakeTransport(ok("x"))
    with pytest.raises(AnthropicLLMError):
        AnthropicLLM(api_key=FAKE_KEY, model=FAKE_MODEL, max_tokens=0, transport=transport)
    assert transport.calls == 0


def test_budget_g3_no_per_model_ceiling_is_enforced_locally() -> None:
    """An implausibly large budget is accepted here and refused by the provider.

    The adapter guessing a ceiling would reject values that are in fact valid, on models it
    has never heard of. ``LLM_INVALID_REQUEST`` is the provider's answer, not ours.
    """
    llm, transport = build(error(400), max_tokens=99_000_000)
    assert transport.calls == 0

    with pytest.raises(AnthropicLLMError) as raised:
        llm.generate("본문")
    assert raised.value.code == LLMErrorCode.INVALID_REQUEST
    assert transport.requests[0].payload["max_tokens"] == 99_000_000


def test_budget_i_hitting_the_budget_is_still_refused_not_returned() -> None:
    """The existing RESPONSE_TRUNCATED handling, pinned against the budget contract."""
    llm, _ = build(raw(200, message_body('{"findings": []}', stop_reason="max_tokens")))
    with pytest.raises(AnthropicLLMError) as raised:
        llm.generate_structured("p", schema=FINDING_BATCH)
    assert raised.value.code == LLMErrorCode.RESPONSE_TRUNCATED

    llm, _ = build(raw(200, message_body("절반만 쓴 산문", stop_reason="max_tokens")))
    with pytest.raises(AnthropicLLMError) as raised:
        llm.generate("p")
    assert raised.value.code == LLMErrorCode.RESPONSE_TRUNCATED


def test_budget_i2_a_truncated_call_still_reports_its_usage() -> None:
    """Pinned here too: the budget being too small is exactly the cost worth seeing."""
    seen: list[AnthropicUsage] = []
    llm, _ = build(
        raw(200, message_body("절반만", stop_reason="max_tokens", output_tokens=64)),
        max_tokens=64,
        usage_sink=seen.append,
    )
    with pytest.raises(AnthropicLLMError):
        llm.generate("p")
    assert len(seen) == 1
    assert seen[0].output_tokens == 64 and seen[0].stop_reason == "max_tokens"


def test_j_the_cores_system_and_prompt_arrive_verbatim_and_first() -> None:
    """The adapter adds an envelope. It does not edit, reorder or paraphrase what it wraps."""
    system = "당신은 근거만 사용한다. 추론과 사실을 섞지 않는다."
    prompt = "다음 근거에서 finding을 추출하라.\n\nEvidence rules: 근거 없는 숫자를 만들지 않는다."

    llm, transport = build()
    llm.generate(prompt, system=system)
    request = transport.last

    assert request.system.startswith(system), "the core's system text must come first"
    assert request.user == prompt, "a plain generate must send the prompt unchanged"


def test_j2_the_envelope_is_exactly_these_three_directives() -> None:
    """An envelope nobody can enumerate is a hidden system prompt by another name.

    Whatever the adapter adds beyond the core's own text is the difference computed here, and
    every line of it has to be one of the constants the module exports.
    """
    known = {
        LANGUAGE_DIRECTIVE.format(language="Korean"),
        LANGUAGE_DIRECTIVE.format(language="English"),
        EVIDENCE_DIRECTIVE,
        JSON_DIRECTIVE,
        SUMMARY_DIRECTIVE.format(max_sentences=3),
    }
    # Deliberately multi-paragraph: a real system prompt is, and the difference has to be
    # computed as a suffix rather than by splitting, or this test would only hold for
    # one-line inputs.
    core_system = "핵심 시스템 문장\n\n두 번째 문단"
    built = build_system(
        core_system, output_lang="ko", grounded=True, structured=True, max_sentences=3
    )
    assert built.startswith(core_system), "the core's system text must come first, unedited"

    added = [part for part in built[len(core_system):].split("\n\n") if part]
    assert set(added) <= known, f"the adapter added something undeclared: {set(added) - known}"


def test_j3_the_envelope_carries_no_domain_rule() -> None:
    """Evidence rules, personas and business vocabulary live in ``prompts/``, not here."""
    envelope = " ".join(
        [LANGUAGE_DIRECTIVE, EVIDENCE_DIRECTIVE, JSON_DIRECTIVE, SUMMARY_DIRECTIVE]
    ).lower()
    for word in (
        "swot", "finding", "client", "fit", "priority", "proposal", "pricing", "master note",
        "consultant", "expert", "you are", "confidence", "fact", "assumption", "inference",
    ):
        assert word not in envelope, f"the envelope states a domain rule: {word}"


def test_j4_evidence_is_data_and_goes_in_the_user_message() -> None:
    llm, transport = build(schema_responder)
    llm.analyze("근거에서 찾아라", evidence=["[E1] 첫째", "[E2] 둘째"], schema=FINDING_BATCH)
    request = transport.last

    assert "[E1] 첫째" in request.user and "[E2] 둘째" in request.user
    assert "[E1]" not in request.system, "evidence is data, not an instruction"
    assert EVIDENCE_DIRECTIVE in request.system
    assert request.user.startswith("근거에서 찾아라")


def test_j5_the_schema_is_transmitted_and_is_machine_readable() -> None:
    llm, transport = build(schema_responder)
    llm.generate_structured("무엇이든", schema=FINDING_BATCH)
    assert transport.last.schema == FINDING_BATCH


def test_j6_the_same_call_twice_builds_byte_identical_requests() -> None:
    """Otherwise a diff of two runs is unreadable and a replay is not one."""
    llm, transport = build(schema_responder)
    llm.analyze("p", evidence=["[E1] a"], schema=FINDING_BATCH, system="s")
    llm.analyze("p", evidence=["[E1] a"], schema=FINDING_BATCH, system="s")
    assert transport.requests[0].body == transport.requests[1].body


def test_k_output_lang_reaches_the_model_in_every_method() -> None:
    for lang, named in (("ko", "Korean"), ("en", "English")):
        directive = LANGUAGE_DIRECTIVE.format(language=named)

        llm, transport = build(schema_responder, schema_responder, schema_responder, ok("s"))
        llm.generate("p", output_lang=lang)
        llm.generate_structured("p", schema=FINDING_BATCH, output_lang=lang)
        llm.analyze("p", evidence=["[E1] a"], schema=FINDING_BATCH, output_lang=lang)
        llm.summarize("본문", output_lang=lang)

        for request in transport.requests:
            assert directive in request.system, f"{lang} missing from a request"


def test_k2_an_unknown_language_code_is_passed_through_not_guessed() -> None:
    llm, transport = build()
    llm.generate("p", output_lang="vi")
    assert LANGUAGE_DIRECTIVE.format(language="vi") in transport.last.system


def test_k3_summarize_carries_its_sentence_bound() -> None:
    llm, transport = build(ok("한 문장."))
    llm.summarize("긴 본문", max_sentences=1)
    assert SUMMARY_DIRECTIVE.format(max_sentences=1) in transport.last.system
    assert "긴 본문" in transport.last.user


# -- L / M: response mapping -----------------------------------------------

def test_l_text_blocks_are_joined_and_other_blocks_ignored() -> None:
    """A response can carry blocks nobody asked for. Rendering one puts it into an entity."""
    body = message_body(
        "",
        content=[
            {"type": "thinking", "thinking": "internal reasoning nobody asked for"},
            {"type": "text", "text": "첫 "},
            {"type": "text", "text": "번째"},
        ],
    )
    llm, _ = build(raw(200, body))
    assert llm.generate("p") == "첫 번째"


def test_l2_a_fenced_json_answer_is_accepted() -> None:
    """Models wrap JSON in a code fence. That is a response format, not a schema failure."""
    llm, _ = build(ok('```json\n{"findings": []}\n```'))
    assert llm.generate_structured("p", schema=FINDING_BATCH) == {"findings": []}


def test_l3_structured_output_is_validated_against_the_requested_schema() -> None:
    llm, _ = build(ok('{"findings": [{"finding": "no refs at all"}]}'))
    with pytest.raises(AnthropicStructuredOutputError) as raised:
        llm.generate_structured("p", schema=FINDING_BATCH)
    assert raised.value.code == LLMErrorCode.OUTPUT_SCHEMA_INVALID
    assert isinstance(raised.value, StructuredOutputError), "the core's contract must still catch it"


def test_l4_a_json_array_is_not_an_object() -> None:
    llm, _ = build(ok("[1, 2, 3]"))
    with pytest.raises(AnthropicStructuredOutputError) as raised:
        llm.generate_structured("p", schema=FINDING_BATCH)
    assert raised.value.code == LLMErrorCode.OUTPUT_NOT_JSON


def test_m_an_empty_answer_is_an_error_not_an_empty_result() -> None:
    for body in (ok(""), ok("   "), raw(200, message_body("", content=[]))):
        llm, _ = build(body)
        with pytest.raises(AnthropicLLMError) as raised:
            llm.generate("p")
        assert raised.value.code == LLMErrorCode.EMPTY_RESPONSE


def test_m2_a_truncated_answer_is_refused() -> None:
    """Half a classification is not a partial result, it is an unmarked one."""
    llm, _ = build(raw(200, message_body('{"findings": []}', stop_reason="max_tokens")))
    with pytest.raises(AnthropicLLMError) as raised:
        llm.generate_structured("p", schema=FINDING_BATCH)
    assert raised.value.code == LLMErrorCode.RESPONSE_TRUNCATED


def test_m3_a_refusal_maps_to_its_own_code() -> None:
    llm, _ = build(raw(200, message_body("", stop_reason="refusal")))
    with pytest.raises(AnthropicLLMError) as raised:
        llm.generate("p")
    assert raised.value.code == LLMErrorCode.CONTENT_REFUSED


def test_m4_a_response_that_is_not_a_messages_body_is_malformed() -> None:
    for body in (raw(200, b"<html>gateway</html>"), raw(200, [1, 2]), raw(200, {"content": "x"})):
        llm, _ = build(body)
        with pytest.raises(AnthropicLLMError) as raised:
            llm.generate("p")
        assert raised.value.code == LLMErrorCode.MALFORMED_RESPONSE


# -- N..S: error mapping ---------------------------------------------------

@pytest.mark.parametrize(
    "status, code",
    [
        (401, LLMErrorCode.AUTH_FAILED),
        (403, LLMErrorCode.AUTH_FAILED),
        (429, LLMErrorCode.RATE_LIMITED),
        (400, LLMErrorCode.INVALID_REQUEST),
        (404, LLMErrorCode.INVALID_REQUEST),
        (413, LLMErrorCode.INVALID_REQUEST),
        (422, LLMErrorCode.INVALID_REQUEST),
        (500, LLMErrorCode.PROVIDER_UNAVAILABLE),
        (502, LLMErrorCode.PROVIDER_UNAVAILABLE),
        (503, LLMErrorCode.PROVIDER_UNAVAILABLE),
        (529, LLMErrorCode.PROVIDER_UNAVAILABLE),
    ],
)
def test_nor_every_status_maps_to_a_stable_code(status: int, code: str) -> None:
    llm, _ = build(error(status))
    with pytest.raises(AnthropicLLMError) as raised:
        llm.generate("p")
    assert raised.value.code == code
    assert raised.value.status == status
    assert isinstance(raised.value, ProviderError), "callers catch ProviderError, not HTTP"


def test_p_a_timeout_maps_to_a_timeout_however_it_arrives() -> None:
    """``urlopen`` raises ``TimeoutError`` on a read and wraps it in ``URLError`` on a connect."""
    import urllib.error

    for exc in (TimeoutError("read"), urllib.error.URLError(TimeoutError("connect"))):
        llm, _ = build(exc)
        with pytest.raises(AnthropicLLMError) as raised:
            llm.generate("p")
        assert raised.value.code == LLMErrorCode.TIMEOUT


def test_q_a_network_failure_maps_to_a_network_failure() -> None:
    import urllib.error

    for exc in (urllib.error.URLError("no route"), OSError("connection reset"), ValueError("odd")):
        llm, _ = build(exc)
        with pytest.raises(AnthropicLLMError) as raised:
            llm.generate("p")
        assert raised.value.code == LLMErrorCode.NETWORK_FAILED
        assert raised.value.exception_type == type(exc).__name__


def test_s_the_providers_own_message_is_never_surfaced() -> None:
    """A 4xx body quotes the request that produced it, and the request is the document."""
    detail = "ZQX-PROVIDER-DETAIL-9f2a quoting the request body"
    llm, _ = build(error(400, message=detail))

    with pytest.raises(AnthropicLLMError) as raised:
        llm.generate("p")
    exc = raised.value

    import traceback

    formatted = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    for surface in (str(exc), repr(exc), formatted, str(exc.args)):
        assert detail not in surface
    # Without ``from None`` the original would hang off ``__cause__`` and its message would
    # print in full from ``traceback.format_exc()`` — the failure mode ``docs/privacy.md``
    # section 4 describes for parser exceptions.
    assert exc.__cause__ is None, "a provider exception must not be chained onto this one"
    assert detail not in str(exc.__context__ or "")


def test_s2_every_raised_code_belongs_to_the_declared_set() -> None:
    """No failure path invents a code that nothing downstream can switch on."""
    raised_codes = {
        node.attr
        for node in ast.walk(ast.parse(ADAPTER.read_text(encoding="utf-8")))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "LLMErrorCode"
    }
    assert raised_codes, "the adapter should reference its own codes"
    assert {getattr(LLMErrorCode, name) for name in raised_codes} <= LLM_ERROR_CODES


# -- T / U / V / W: logging, persistence, canary ---------------------------

#: Fictional throughout — a filename, an address, a number, a passage and a key-shaped string.
CANARIES = {
    "filename": "2026년_메콩델타_고객제안_v3.docx",
    "email": "fictional.buyer@example.invalid",
    "phone": "+84-28-0000-0000",
    "document": "ZQX-LLM-CANARY-5b7e 현장 인력이 수동 채수에 의존한다",
    "api_key": FAKE_KEY,
}


def test_t_u_the_adapter_has_no_logger_and_no_output_channel() -> None:
    """The cheapest way not to log a prompt is to have nowhere to log it to."""
    source = ADAPTER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(a.name.split(".")[0] != "logging" for a in node.names), node.lineno
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] != "logging", node.lineno
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"print", "open", "input"}, f"line {node.lineno}"


def test_t_u2_no_canary_reaches_a_log_a_stream_or_an_error(caplog, capsys) -> None:
    """Prompt, evidence, response and credential, across every failure and success path."""
    caplog.set_level(0)
    prompt = " ".join(CANARIES[k] for k in ("filename", "email", "phone", "document"))

    llm, _ = build(ok(CANARIES["document"]), error(400, message=CANARIES["document"]))
    assert llm.generate(prompt, system=CANARIES["email"]) == CANARIES["document"]

    with pytest.raises(AnthropicLLMError) as raised:
        llm.generate(prompt)

    import traceback

    exc = raised.value
    surfaces = [
        caplog.text,
        capsys.readouterr().out,
        capsys.readouterr().err,
        str(exc),
        repr(exc),
        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        repr(llm),
    ]
    for surface in surfaces:
        for label, canary in CANARIES.items():
            assert canary not in surface, f"{label} leaked into a surface"


def test_t_u3_transmitted_is_not_the_same_as_leaked() -> None:
    """The control case, and the distinction the whole privacy story rests on.

    Evidence selected for analysis **is** sent to the provider — that is the contract, and
    ``docs/privacy.md`` section 0 says so in as many words. What must not happen is the same
    text appearing in a log line, an exception or a file. A canary test with no positive half
    proves nothing: it would pass on an adapter that sent an empty request.
    """
    llm, transport = build(schema_responder)
    llm.analyze(
        "근거에서 찾아라", evidence=[f"[E1] {CANARIES['document']}"], schema=FINDING_BATCH
    )
    assert CANARIES["document"] in transport.last.body.decode("utf-8"), (
        "selected evidence must actually be transmitted"
    )


def test_v_w_a_full_run_leaves_no_file_anywhere(tmp_path: Path, monkeypatch) -> None:
    """No cache, no transcript, no debug dump — on the success path or the failure paths."""
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    temp_root = Path(tempfile.gettempdir())
    before_temp = set(temp_root.iterdir())

    llm, _ = build(
        schema_responder,
        ok("한 문장."),
        error(500),
        TimeoutError("read"),
        ok("not json"),
    )
    llm.analyze("p", evidence=["[E1] a"], schema=FINDING_BATCH)
    llm.summarize("본문")
    for expected in (AnthropicLLMError, AnthropicLLMError, StructuredOutputError):
        with pytest.raises(expected):
            llm.generate_structured("p", schema=FINDING_BATCH)

    assert set(workdir.iterdir()) == set(), "the adapter wrote into the working directory"
    assert set(temp_root.iterdir()) - before_temp == set(), "the adapter wrote a temp file"


def test_v2_usage_is_opt_in_counts_only_and_kept_nowhere() -> None:
    seen: list[AnthropicUsage] = []
    llm, _ = build(ok("답", input_tokens=120, output_tokens=34), usage_sink=seen.append)
    llm.generate(CANARIES["document"])

    assert len(seen) == 1
    usage = seen[0]
    assert usage.input_tokens == 120 and usage.output_tokens == 34
    assert usage.status == 200 and usage.attempts == 1
    for value in usage.as_log_fields().values():
        assert CANARIES["document"] not in str(value)

    quiet, _ = build(ok("답"))
    quiet.generate("p")  # no sink: nothing is recorded at all, not even in memory
    assert not hasattr(quiet, "last_usage")


def test_v3_a_refused_call_still_reports_what_it_cost() -> None:
    """Truncation and refusal are billed. Hiding their cost hides the expensive failures."""
    seen: list[AnthropicUsage] = []
    llm, _ = build(
        raw(200, message_body("절반만", stop_reason="max_tokens", output_tokens=4096)),
        usage_sink=seen.append,
    )
    with pytest.raises(AnthropicLLMError) as raised:
        llm.generate("p")

    assert raised.value.code == LLMErrorCode.RESPONSE_TRUNCATED
    assert len(seen) == 1 and seen[0].output_tokens == 4096
    assert seen[0].stop_reason == "max_tokens", "the sink must be able to tell why"


# -- X: the SDK boundary ---------------------------------------------------

#: Modules that can reach a network or belong to a provider. Only LLM adapters may name them.
NETWORK_MODULES = {
    "aiohttp", "anthropic", "google", "http", "httpcore", "httpx", "httpx2", "openai",
    "requests", "socket", "ssl", "urllib", "websockets",
}


def _python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def test_x_only_llm_adapters_may_import_a_network_module() -> None:
    """``test_core_purity.py`` keeps these out of ``core/``. This keeps them in one folder.

    The point is not that a search adapter will never need HTTP — Phase 3's ``search/web.py``
    will. It is that today exactly one module in this repository can open a socket, and a
    second one appearing should be a decision somebody made rather than one that happened.
    """
    allowed = REPO_ROOT / "adapters" / "llm"
    offenders: list[str] = []

    for root in (REPO_ROOT / "core", REPO_ROOT / "adapters"):
        for path in _python_files(root):
            if allowed in path.parents:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    names = [node.module]
                for name in names:
                    if name.split(".")[0] in NETWORK_MODULES:
                        offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno} {name}")

    assert not offenders, offenders


def test_x2_the_core_cannot_see_this_adapter_at_all() -> None:
    """The dependency runs one way. Stated here too, because this is the tempting one."""
    for path in _python_files(REPO_ROOT / "core"):
        source = path.read_text(encoding="utf-8")
        assert "anthropic" not in source.lower() or path.name == "llm.py", path.name


def test_x3_a_harness_can_be_assembled_with_this_adapter(repo_root: Path) -> None:
    """The integration surface is ``create_harness``, and nothing else changes."""
    from adapters.knowledge.static import StaticKnowledge
    from adapters.search.manual import ManualSearch
    from adapters.storage.memory import MemoryStorage
    from core.harness import create_harness

    llm, _ = build()
    harness = create_harness(
        storage=MemoryStorage(),
        knowledge=StaticKnowledge.from_directory(repo_root / "knowledge" / "master-notes"),
        llm=llm,
        search=ManualSearch(),
    )
    assert harness.llm.name == "anthropic"


# -- AA: the real provider -------------------------------------------------
#
# Two gates, deliberately redundant, and deliberately *not* ``ANTHROPIC_API_KEY``: an
# environment left over from another task must not be able to start billing. The same
# reasoning as ``scripts/spikes/phase8_runtime_spike.py``'s ``--real-provider``.

LIVE_FLAG = "HARNESS_LLM_LIVE_TEST"
LIVE_KEY = "HARNESS_LLM_LIVE_API_KEY"
LIVE_MODEL = "HARNESS_LLM_LIVE_MODEL"


def live_config(env) -> tuple[str, str] | None:
    """The credential and model for a live run, or ``None`` — which is the normal answer."""
    if env.get(LIVE_FLAG, "").strip() != "1":
        return None
    key = env.get(LIVE_KEY, "").strip()
    model = env.get(LIVE_MODEL, "").strip()
    return (key, model) if key and model else None


def test_aa_a_credential_in_the_environment_does_not_enable_a_live_test() -> None:
    """Presence of a key is not consent to spend it."""
    assert live_config({}) is None
    assert live_config({"ANTHROPIC_API_KEY": "sk-whatever", LIVE_MODEL: "m"}) is None
    assert live_config({LIVE_KEY: "sk-whatever", LIVE_MODEL: "m"}) is None
    assert live_config({LIVE_FLAG: "1", LIVE_KEY: "sk-whatever"}) is None
    assert live_config({LIVE_FLAG: "1", LIVE_MODEL: "m"}) is None
    assert live_config({LIVE_FLAG: "1", LIVE_KEY: "k", LIVE_MODEL: "m"}) == ("k", "m")


@pytest.mark.skipif(
    live_config(__import__("os").environ) is None,
    reason=(
        "live provider test not requested: set "
        f"{LIVE_FLAG}=1, {LIVE_KEY} and {LIVE_MODEL} together. "
        "Without all three this is NOT_RUN, and the suite stays offline."
    ),
)
def test_aa2_the_real_provider_answers_the_contract() -> None:
    """The only test in this repository that spends money. Opt-in, never in CI.

    It asks for the smallest structured answer the harness ever asks for, so that a live run
    costs as little as it can while still exercising the path that matters: a real request,
    a real response, and schema validation of what came back.
    """
    import os

    key, model = live_config(os.environ)
    llm = AnthropicLLM(api_key=key, model=model, max_tokens=1024, timeout_seconds=120.0)

    result = llm.analyze(
        "Extract findings from the evidence. If the evidence settles nothing, return an "
        "empty list.",
        evidence=["[E1] A fictional utility increased its sampling interval in 2026."],
        schema=FINDING_BATCH,
    )
    assert isinstance(result, dict) and "findings" in result
    Draft202012Validator = __import__(
        "jsonschema", fromlist=["Draft202012Validator"]
    ).Draft202012Validator
    Draft202012Validator(FINDING_BATCH).validate(result)


# -- helpers this file relies on -------------------------------------------

def test_the_fake_transport_is_not_hiding_a_real_one() -> None:
    """If the fake ever stopped recording, most of this file would pass vacuously."""
    llm, transport = build(ok("답"))
    llm.generate("본문")
    assert transport.calls == 1
    assert json.loads(transport.last.body.decode("utf-8"))["messages"][0]["content"] == "본문"
