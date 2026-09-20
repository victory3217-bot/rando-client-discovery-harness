# -*- coding: utf-8 -*-
"""The ``LLMProvider`` contract, run against every adapter that claims to implement it.

``test_adapters.py`` does this for the three storage adapters — the same calls against all of
them, only what is *kept* allowed to differ. This is that test for the LLM side, and Phase 8
is when it starts to matter: until now there was one adapter, so "swapping the provider leaves
the core workflow intact" was an architectural claim with nothing to check it.

Everything here is offline. ``EchoLLM`` has no network by construction and ``AnthropicLLM``
is given a fake transport, so no test in this file has a credential or opens a socket.
Provider-specific behaviour — request shape, retries, error mapping, credential handling —
belongs in ``test_llm_anthropic.py``; what belongs here is only what both must do.
"""
from __future__ import annotations

import inspect
from typing import Callable

import pytest
from jsonschema import Draft202012Validator

from adapters.llm.anthropic import AnthropicLLM
from adapters.llm.echo import EchoLLM
from core import evidence
from core.interfaces import LLMProvider
from core.models import EvidenceType, MarketScope, Project
from core.research import run_research
from core.research.models import EvidenceBlock, EvidenceEntry
from core.research.output_schemas import FINDING_BATCH
from core.transmission import send
from fake_transport import FakeTransport, schema_responder

#: Fictional throughout: this repository is public, and a string shaped like a credential is a
#: credential as far as a secret scanner — and a careless reader — is concerned.
FAKE_KEY = "sk-fictional-not-a-real-key-0000"
FAKE_MODEL = "fictional-model-1"

#: A fixture value, not a default: ``AnthropicLLM`` has none and requires one, because the
#: generation budget is a policy the application layer picks.
FAKE_MAX_TOKENS = 2048


def _echo() -> EchoLLM:
    return EchoLLM()


def _anthropic() -> AnthropicLLM:
    """The production adapter with its network replaced, and nothing else changed."""
    return AnthropicLLM(
        api_key=FAKE_KEY,
        model=FAKE_MODEL,
        max_tokens=FAKE_MAX_TOKENS,
        transport=FakeTransport(schema_responder),
    )


#: Every adapter that claims to be an ``LLMProvider``. A new one is added here, not given its
#: own private definition of what the contract means.
PROVIDERS: dict[str, Callable[[], object]] = {"echo": _echo, "anthropic": _anthropic}

provider = pytest.fixture(params=sorted(PROVIDERS), ids=sorted(PROVIDERS))(
    lambda request: PROVIDERS[request.param]()
)


# -- A / B: both satisfy the protocol, and are interchangeable -------------

@pytest.mark.parametrize("build", list(PROVIDERS.values()), ids=list(PROVIDERS))
def test_a_every_llm_adapter_satisfies_the_protocol(build) -> None:
    assert isinstance(build(), LLMProvider)


def test_a2_the_signatures_match_the_protocol_not_only_the_names() -> None:
    """``runtime_checkable`` checks method *names*. Names are not a contract.

    A provider whose ``analyze`` took ``context`` instead of ``evidence`` would pass an
    ``isinstance`` check and fail at the first call from ``core.transmission.send``.
    """
    for method in ("generate", "generate_structured", "analyze", "summarize"):
        # The protocol's methods are unbound, so ``self`` is in their signature and not in a
        # bound adapter method's. Everything after it is the contract.
        declared = inspect.signature(getattr(LLMProvider, method)).parameters
        expected = {k: v for k, v in declared.items() if k != "self"}
        for name, build in PROVIDERS.items():
            actual = inspect.signature(getattr(build(), method)).parameters
            assert list(actual) == list(expected), (
                f"{name}.{method} has parameters {list(actual)}, "
                f"the protocol says {list(expected)}"
            )
            for parameter in expected.values():
                mine = actual[parameter.name]
                assert mine.kind == parameter.kind, f"{name}.{method}: {parameter.name}"
                assert mine.default == parameter.default, f"{name}.{method}: {parameter.name}"


def test_b_each_adapter_names_itself_and_no_two_share_a_name() -> None:
    names = [build().name for build in PROVIDERS.values()]
    for value in names:
        assert isinstance(value, str) and value
    assert len(set(names)) == len(names)


# -- the four methods ------------------------------------------------------

def test_generate_returns_text(provider) -> None:
    result = provider.generate("요약해 주세요", system="시스템", output_lang="ko")
    assert isinstance(result, str) and result.strip()


def test_summarize_returns_text(provider) -> None:
    result = provider.summarize("문단 하나", output_lang="ko", max_sentences=2)
    assert isinstance(result, str) and result.strip()


def test_l_generate_structured_returns_a_value_the_schema_accepts(provider, schemas) -> None:
    """Every schema this repository ships, through every adapter."""
    for name, schema in sorted(schemas.items()):
        result = provider.generate_structured("무엇이든", schema=schema)
        assert isinstance(result, dict), name
        Draft202012Validator(schema).validate(result)


def test_l2_analyze_returns_a_value_the_schema_accepts(provider) -> None:
    result = provider.analyze(
        "근거에서 찾아라",
        evidence=["[E1] 현장 인력이 수동 채수에 의존한다"],
        schema=FINDING_BATCH,
    )
    assert isinstance(result, dict)
    Draft202012Validator(FINDING_BATCH).validate(result)


# -- Y: the gateway works the same either way ------------------------------

def test_y_both_providers_go_through_the_transmission_gateway(provider) -> None:
    """``send()`` is the only way out of core. It must not care which adapter is behind it."""
    block = EvidenceBlock(
        entries=[EvidenceEntry(ref="E1", text="수동 채수", candidate=object())]
    )
    result, record = send(
        provider,
        stage="extract_findings",
        prompt="p",
        schema=FINDING_BATCH,
        evidence=block,
        framework_id="MN02",
    )
    assert isinstance(result, dict)
    assert record.grounded is True
    assert record.provider == provider.name
    assert record.item_count == 1 and record.char_count == len("수동 채수")

    _, ungrounded = send(
        provider, stage="classify_swot", prompt="p", schema=FINDING_BATCH, items=["[F1] x"]
    )
    assert ungrounded.grounded is False and ungrounded.provider == provider.name


def test_y2_the_record_carries_no_text_whichever_provider_ran(provider) -> None:
    canary = "ZQX-CONTRACT-CANARY-7c31"
    block = EvidenceBlock(entries=[EvidenceEntry(ref="E1", text=canary, candidate=object())])
    _, record = send(
        provider,
        stage="extract_findings",
        prompt=f"analyse {canary}",
        schema=FINDING_BATCH,
        evidence=block,
    )
    assert canary not in str(record)
    assert canary not in repr(record)
    assert canary not in str(record.as_log_fields())


# -- B: the pipeline itself runs on either ---------------------------------

def test_b2_the_research_pipeline_runs_unchanged_on_either_provider(
    provider, repo_root
) -> None:
    """The success criterion, executed rather than asserted.

    Not "the outcomes are identical" — two providers answer differently and that is the point
    of having two. What has to hold is that the pipeline completes, records its transmissions
    and produces entities that satisfy the evidence invariants, with nothing swapped but the
    adapter.
    """
    from adapters.intake import IntakeSession
    from adapters.knowledge.static import StaticKnowledge
    from adapters.prompts import load_prompt_set
    from core.models import FileType, SourceCategory

    body = (
        "메콩델타 상수도 사업자는 건기 염분 상승 구간에서 측정 주기를 늘려야 한다.\n\n"
        "현장 인력이 수동 채수에 의존하고 있어 주기를 늘리기 어렵다.\n"
    )
    with IntakeSession("prj_contract") as session:
        ingested = session.ingest(
            bytearray(body.encode("utf-8")),
            file_type=FileType.TXT,
            source_category=SourceCategory.EXTERNAL_BUSINESS_DATA,
            display_label="시장 메모 (가상)",
        )

    outcome = run_research(
        project=Project(
            project_id="prj_contract",
            company_name="Fictional Sensing",
            market_scope=[MarketScope.INTERNATIONAL],
            target_countries=["VN"],
        ),
        candidates=ingested.candidates,
        sources=[ingested.source],
        knowledge=StaticKnowledge.from_directory(repo_root / "knowledge" / "master-notes"),
        llm=provider,
        prompts=load_prompt_set(repo_root / "prompts"),
    )

    assert outcome.transmissions, "the pipeline must have made calls"
    assert {r.provider for r in outcome.transmissions} == {provider.name}
    for finding in outcome.findings:
        assert evidence.check_finding(finding) == []
        assert finding.evidence_type is not EvidenceType.FACT, (
            "neither of these providers has evidence to establish a fact with"
        )


# -- Z: none of this touched the network -----------------------------------

def test_z_no_contract_test_can_reach_the_network(monkeypatch, provider) -> None:
    """Belt and braces: with ``socket.socket`` removed, every method above still works.

    ``EchoLLM`` never had a socket and ``AnthropicLLM``'s is behind an injected transport, so
    this should pass trivially — which is the point. The day it stops passing, an adapter has
    grown a second way out.
    """
    import socket

    def refuse(*args, **kwargs):
        raise AssertionError("an offline test opened a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)

    assert provider.generate("x")
    assert provider.summarize("y")
    assert isinstance(provider.generate_structured("z", schema=FINDING_BATCH), dict)
    assert isinstance(
        provider.analyze("w", evidence=["[E1] a"], schema=FINDING_BATCH), dict
    )
