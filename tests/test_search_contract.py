# -*- coding: utf-8 -*-
"""The ``SearchProvider`` contract, run against manual and brave together.

``test_search_brave.py`` checks what is true of one provider because it talks to a paid remote
service. This file checks what has to be true of **any** of them, and it does it by
parametrising over both — the same arrangement ``test_llm_contract.py`` uses for ``echo`` and
``anthropic``, and for the same reason. "A production search adapter drops into the same slot
as the manual one" is a claim; running one body of assertions over both is a test.

Everything here is offline. ``BraveSearch`` takes its transport as a constructor argument, so
the production adapter answers from ``fake_search_transport.py`` with no credential and no
socket.
"""
from __future__ import annotations

import inspect

import pytest

from adapters.search.brave import BraveSearch
from adapters.search.manual import ManualSearch
from core.evidence import check_source_metadata
from core.interfaces import SearchProvider
from core.interfaces.search import SearchResult
from core.models import Confidence, EvidenceType, MarketScope, SourceOrigin
from core.research.confidence import ConfidenceSignals, ceiling_for
from core.research.policy import SNIPPET_LOCATOR
from core.research.sources import ingest_search_results
from fake_search_transport import FakeTransport, ok, result

FAKE_KEY = "fictional-subscription-token-0000"

#: What the fake provider returns and what the manual adapter is stocked with, kept deliberately
#: parallel so that one set of assertions can describe both. Fictional throughout
#: (``HARNESS.md`` section 9).
TITLE = "Fictional delta water authority tender"
SNIPPET = "a fictional authority is replacing manual sampling across three fictional provinces"
URL = "https://example.invalid/fictional-tender"
PUBLISHER = "Fictional Water Review"


def manual_provider() -> ManualSearch:
    return ManualSearch(
        [
            SearchResult(
                title=TITLE,
                snippet=SNIPPET,
                url=URL,
                publisher=PUBLISHER,
                retrieved_at="2026-09-20T00:00:00+00:00",
                market_scope=MarketScope.INTERNATIONAL,
            )
        ]
    )


def brave_provider() -> BraveSearch:
    transport = FakeTransport(
        ok(
            result(
                title=TITLE,
                url=URL,
                description=SNIPPET,
                profile={"name": PUBLISHER},
            )
        )
    )
    return BraveSearch(api_key=FAKE_KEY, transport=transport)


PROVIDERS = [pytest.param(manual_provider, id="manual"), pytest.param(brave_provider, id="brave")]


def run(build) -> list[SearchResult]:
    """One search, phrased so that both adapters return the fixture above."""
    return build().search("fictional", scope=MarketScope.INTERNATIONAL, limit=5)


# -- A / B: the slot -------------------------------------------------------

@pytest.mark.parametrize("build", PROVIDERS)
def test_a_each_provider_satisfies_the_protocol(build) -> None:
    assert isinstance(build(), SearchProvider)


@pytest.mark.parametrize("build", PROVIDERS)
def test_a2_each_provider_has_a_loggable_name(build) -> None:
    """``adapters/README.md`` rule 3. ``Harness.describe()`` puts this in a caller's log line."""
    name = build().name
    assert isinstance(name, str) and name and name.isascii() and " " not in name


def test_b_the_signatures_are_the_same_slot() -> None:
    """Not "both have a search method" — the same parameters, in the same order, same defaults.

    A production adapter that quietly required an extra argument would pass an ``isinstance``
    check against a ``runtime_checkable`` Protocol, which only looks for the attribute.
    """
    manual = inspect.signature(ManualSearch.search)
    brave = inspect.signature(BraveSearch.search)
    assert list(manual.parameters) == list(brave.parameters)

    for name, expected in manual.parameters.items():
        actual = brave.parameters[name]
        assert actual.kind is expected.kind, name
        assert actual.default == expected.default, name


@pytest.mark.parametrize("build", PROVIDERS)
def test_b2_a_harness_assembles_with_either(build, repo_root) -> None:
    """The integration surface is ``create_harness``, and nothing else changes."""
    from adapters.knowledge.static import StaticKnowledge
    from adapters.llm.echo import EchoLLM
    from adapters.storage.memory import MemoryStorage
    from core.harness import create_harness

    provider = build()
    harness = create_harness(
        storage=MemoryStorage(),
        knowledge=StaticKnowledge.from_directory(repo_root / "knowledge" / "master-notes"),
        llm=EchoLLM(),
        search=provider,
    )
    assert harness.describe()["search"] == provider.name


# -- result shape ----------------------------------------------------------

@pytest.mark.parametrize("build", PROVIDERS)
def test_c_a_search_returns_search_results(build) -> None:
    hits = run(build)
    assert hits and all(isinstance(hit, SearchResult) for hit in hits)


@pytest.mark.parametrize("build", PROVIDERS)
def test_c2_the_same_fixture_maps_to_the_same_provenance(build) -> None:
    """The fields a reader checks a claim against, from both origins, identical."""
    hit = run(build)[0]
    assert hit.title == TITLE
    assert hit.snippet == SNIPPET
    assert hit.url == URL
    assert hit.publisher == PUBLISHER


@pytest.mark.parametrize("build", PROVIDERS)
def test_c3_every_result_names_the_adapter_that_produced_it(build) -> None:
    """Mixed-provenance research stays auditable only if each item says where it came from."""
    provider = build()
    assert all(hit.provider == provider.name for hit in run(lambda: provider))


@pytest.mark.parametrize("build", PROVIDERS)
def test_c4_every_result_carries_the_scope_it_was_searched_under(build) -> None:
    assert all(hit.market_scope is MarketScope.INTERNATIONAL for hit in run(build))


@pytest.mark.parametrize("build", PROVIDERS)
def test_c5_retrieval_time_is_present_and_publication_time_is_not_invented(build) -> None:
    """``retrieved_at`` is the one thing an adapter is entitled to state about a result.

    ``published_date`` is the opposite: neither adapter may produce one that nothing supplied.
    The manual adapter has none in this fixture and the brave adapter cannot derive one, so both
    leave it unset — and ``check_source_metadata`` below still passes, because a missing
    publication date is a recorded unknown rather than a broken record.
    """
    for hit in run(build):
        assert hit.retrieved_at, "a result with no retrieval time cannot be judged for recency"
        assert hit.published_date is None


@pytest.mark.parametrize("build", PROVIDERS)
def test_c6_an_adapter_does_not_judge_the_source(build) -> None:
    """``evidence_quality`` stays UNKNOWN: retrieval is not assessment."""
    assert all(hit.evidence_quality is Confidence.UNKNOWN for hit in run(build))


@pytest.mark.parametrize("build", PROVIDERS)
def test_d_limit_is_an_upper_bound_both_honour(build) -> None:
    assert len(build().search("fictional", scope=MarketScope.INTERNATIONAL, limit=1)) <= 1


# -- the trail the results feed -------------------------------------------

@pytest.mark.parametrize("build", PROVIDERS)
def test_e_results_from_either_pass_the_evidence_invariants(build) -> None:
    """The real interchangeability check: the core's own validator accepts both, unchanged."""
    sources, candidates = ingest_search_results(run(build), project_id="proj_fictional")

    assert sources and candidates
    for source in sources:
        assert source.source_origin is SourceOrigin.SEARCH_RESULT
        assert check_source_metadata(source) == []
        # A retrieved page is not a file, and neither adapter may pretend otherwise.
        assert source.file_type is None and source.file_size is None and source.page_count is None


@pytest.mark.parametrize("build", PROVIDERS)
def test_f_snippet_evidence_is_capped_at_medium_whichever_adapter_produced_it(build) -> None:
    """Phase 4's rule survives a production provider: a snippet is still not a read page.

    This is the one that would break quietly. An adapter that returned page text in ``snippet``,
    or that set ``evidence_quality`` itself, would still satisfy every assertion above — and the
    ceiling here would move to HIGH without anything else changing.
    """
    sources, candidates = ingest_search_results(run(build), project_id="proj_fictional")
    source = sources[0]

    assert candidates[0].locator == SNIPPET_LOCATOR
    ceiling = ceiling_for(
        EvidenceType.FACT,
        ConfidenceSignals(
            source=source,
            locator=candidates[0].locator,
            corroborating_source_count=9,
            today="2026-09-20",
        ),
    )
    assert ceiling is Confidence.MEDIUM, (
        "a search snippet cannot reach HIGH however well corroborated — nothing read the page"
    )


# -- where the two deliberately differ ------------------------------------

def test_g_the_one_documented_divergence_is_the_empty_query() -> None:
    """Not every difference is a defect, but an undocumented one is.

    ``ManualSearch`` treats an empty query as "no filter" and returns its whole collection,
    which is coherent for a local list somebody pasted in. A production adapter cannot do that:
    there is no collection, and an empty query is a billed round trip that means nothing. It is
    refused before the transport is touched. The core never sends one — ``research_client``
    iterates ``criteria.queries`` — so the divergence costs nothing and is stated here rather
    than discovered later.
    """
    from adapters.search.brave import BraveSearchError, SearchErrorCode

    assert manual_provider().search("", scope=MarketScope.INTERNATIONAL)

    transport = FakeTransport(ok(result()))
    with pytest.raises(BraveSearchError) as raised:
        BraveSearch(api_key=FAKE_KEY, transport=transport).search("   ")

    assert raised.value.code == SearchErrorCode.INVALID_REQUEST
    assert transport.calls == 0, "an empty query must not reach the provider at all"
