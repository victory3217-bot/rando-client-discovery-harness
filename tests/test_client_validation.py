# -*- coding: utf-8 -*-
"""What client discovery refuses to keep.

The failure this phase exists to prevent has a particular shape. Ask a model for companies in a
market and it will give you companies in that market — fluent, specific, often real, and not
evidence of anything. Every organization here is invented so that a model reaching for real
firms produces a name the fixtures do not contain, which is exactly what should be rejected.
"""
from __future__ import annotations

import pytest

from adapters.intake import IntakeSession
from adapters.prompts import load_client_prompt_set
from adapters.storage.memory import MemoryStorage
from core import evidence
from core.client import (
    assess_fit,
    build_criteria,
    find_organizations,
    name_appears_in,
    persist,
    run_discovery,
    strip_legal_suffix,
    verify_mentions,
)
from core.client.fit import FlagCodes
from core.client.models import OrganizationMention
from core.models import (
    MAX_FIT_REASON_CHARS,
    ClientCandidate,
    Confidence,
    EvidenceType,
    FileType,
    FitAssessment,
    FitCriterion,
    FitLevel,
    MarketScope,
    PriorityDecision,
    Project,
    ResearchFinding,
    SourceCategory,
    aggregate_finding_ids,
    aggregate_missing_evidence,
)
from core.research.models import RejectionCode
from scripted_llm import ScriptedLLM

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

PROJECT = "prj_client_validation"
ALPHA = "Fictional Alpha Water Systems"


@pytest.fixture
def prompts(repo_root):
    return load_client_prompt_set(repo_root / "prompts")


@pytest.fixture
def uploaded():
    body = f"{ALPHA}의 2026년 조달 공고에 수질 계측 설비 교체가 포함되어 있다.\n"
    with IntakeSession(PROJECT) as session:
        return session.ingest(
            bytearray(body.encode("utf-8")),
            file_type=FileType.TXT,
            source_category=SourceCategory.EXTERNAL_BUSINESS_DATA,
            source_date="2026-04-02",
        )


def _finding(mn: str, source_id: str) -> ResearchFinding:
    return ResearchFinding(
        project_id=PROJECT,
        finding="조달 공고에 계측 설비 교체가 포함되어 있다",
        evidence_type=EvidenceType.FACT,
        mn_basis=[mn],
        confidence=Confidence.MEDIUM,
        source_id=source_id,
    )


def _find(uploaded, prompts, payload):
    llm = ScriptedLLM({"organizations": [payload]})
    return find_organizations(
        uploaded.candidates,
        llm=llm,
        prompts=prompts,
        sources_by_id={uploaded.source.source_id: uploaded.source},
    )


# -- invented organizations -------------------------------------------------

def test_a_company_the_evidence_does_not_name_is_refused(uploaded, prompts) -> None:
    """The characteristic failure: a name the model knows from pretraining, not from evidence.

    The name below is fictional, because a public repository should not carry real firms even
    as examples of rejection. Nothing in the check depends on it being famous — the passage
    either contains the string or it does not.
    """
    organizations, _, rejections, _ = _find(
        uploaded, prompts, {"mentions": [{"name": "Pan-Asia Heavy Electronics", "evidence_ref": "E1"}]}
    )
    assert organizations == []
    assert rejections and rejections[0].code == RejectionCode.NAME_NOT_IN_EVIDENCE


def test_a_plausible_local_sounding_name_is_refused_just_the_same(uploaded, prompts) -> None:
    organizations, _, rejections, _ = _find(
        uploaded,
        prompts,
        {"mentions": [{"name": "Vietnam Water Supply Corporation", "evidence_ref": "E1"}]},
    )
    assert organizations == []
    assert rejections[0].code == RejectionCode.NAME_NOT_IN_EVIDENCE


def test_a_fabricated_evidence_reference_is_refused(uploaded, prompts) -> None:
    organizations, _, rejections, _ = _find(
        uploaded, prompts, {"mentions": [{"name": ALPHA, "evidence_ref": "E99"}]}
    )
    assert organizations == []
    assert rejections[0].code == RejectionCode.UNKNOWN_EVIDENCE_REF


def test_one_invented_name_does_not_cost_the_real_one(uploaded, prompts) -> None:
    organizations, _, rejections, _ = _find(
        uploaded,
        prompts,
        {"mentions": [
            {"name": "Invented Holdings", "evidence_ref": "E1"},
            {"name": ALPHA, "evidence_ref": "E1"},
        ]},
    )
    assert len(organizations) == 1 and organizations[0].name == ALPHA
    assert len(rejections) == 1


def test_an_empty_name_is_refused(uploaded, prompts) -> None:
    organizations, _, rejections, _ = _find(
        uploaded, prompts, {"mentions": [{"name": "   ", "evidence_ref": "E1"}]}
    )
    assert organizations == [] and rejections


# -- matching is literal, not semantic --------------------------------------

#: The acceptance matrix, as specified. Held in one place so that a change to the matcher has to
#: be argued against the whole table rather than one case at a time.
_MEKONG = "Mekong Aqua Utilities"
NAME_MATCHING = [
    (_MEKONG, _MEKONG, True, "the same tokens"),
    (f"{_MEKONG} Co., Ltd.", _MEKONG, True, "a tolerated legal form"),
    (f"{_MEKONG}가 사업을 발표했다.", _MEKONG, True, "a Korean particle, not a word"),
    (_MEKONG, "Mekong Aqua", False, "Utilities is part of a name, not the next word"),
    ("AlphaBeta Industrial", "Alpha", False, "not even a whole token"),
]


@pytest.mark.parametrize("evidence_text,model_name,accepted,why", NAME_MATCHING)
def test_the_name_matching_matrix(evidence_text, model_name, accepted, why) -> None:
    assert name_appears_in(model_name, evidence_text) is accepted, why


def test_a_partial_name_is_refused_but_the_whole_one_is_not() -> None:
    """The pair that shows the rule is about the name, not about what follows it.

    ``Utilities`` continues a proper noun and ``announced`` does not, which is a fact about
    orthography rather than about the water industry — the distinction is available without the
    harness knowing anything about either organization.
    """
    assert not name_appears_in("Mekong Aqua", "Mekong Aqua Utilities")
    assert name_appears_in("Mekong Aqua Utilities", "Mekong Aqua Utilities announced a tender")


def test_a_name_inside_a_longer_word_is_refused() -> None:
    """The substring hole. ``AlphaBeta Industrial`` is not ``Alpha``.

    A plain ``in`` test accepts this and reports the verification as passed, so the wrong
    organization arrives with provenance attached and nothing marks it as doubtful. Matching on
    token boundaries is what makes the control mean what it says.
    """
    assert not name_appears_in("Alpha", "AlphaBeta Industrial announced a programme")
    assert not name_appears_in("Alpha", "알파베타산업 AlphaBeta가 공고를 냈다")


def test_a_name_at_the_end_of_a_longer_word_is_refused() -> None:
    """The same failure from the other side, which a left-only boundary check would miss."""
    assert not name_appears_in("Beta Industrial", "AlphaBeta Industrial announced")


def test_the_full_name_still_matches() -> None:
    assert name_appears_in("AlphaBeta Industrial", "AlphaBeta Industrial announced")


def test_a_korean_particle_does_not_break_a_match() -> None:
    """Korean attaches particles with no space, so this is the same as a trailing space."""
    assert name_appears_in("Mekong Aqua Utilities", "Mekong Aqua Utilities가 공고를 냈다")
    assert name_appears_in("Mekong Aqua Utilities", "Mekong Aqua Utilities는 계측을 늘린다")
    assert name_appears_in("알파워터", "알파워터가 조달 공고를 냈다")


def test_a_korean_compound_is_not_a_match() -> None:
    """An unrecognised trailing run blocks it, so a compound word cannot pass as a name."""
    assert not name_appears_in("알파워터", "알파워터베타산업이 공고를 냈다")


def test_no_semantic_matching_exists_to_be_reached() -> None:
    """Stronger than testing that fuzzy matching is off: there is nothing to switch on.

    Checked against the imports rather than the file's words, because the module explains in
    prose what it refuses to do and a text scan cannot tell an explanation from a call.
    """
    import ast

    tree = ast.parse((ROOT / "core/client/verify.py").read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    for banned in ("difflib", "rapidfuzz", "fuzzywuzzy", "Levenshtein", "numpy", "sklearn"):
        assert banned not in imported, f"verify.py imports {banned}"

    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not {"get_close_matches", "ratio", "partial_ratio"} & called
    # And no provider reaches this module at all, so no model can resolve an entity here.
    assert "llm" not in {
        arg.arg
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        for arg in node.args.args + node.args.kwonlyargs
    }


def test_a_legal_suffix_difference_is_tolerated() -> None:
    assert name_appears_in(f"{ALPHA} Co., Ltd.", f"{ALPHA} 가 발표했다")
    assert name_appears_in(ALPHA, f"{ALPHA} Co., Ltd. 가 발표했다")


def test_whitespace_differences_are_tolerated() -> None:
    assert name_appears_in("Fictional  Alpha   Water Systems", ALPHA)


def test_an_alias_is_not_guessed() -> None:
    """Deciding two firms are one company is a claim about the world, not a string operation."""
    assert not name_appears_in("ABC Corporation", "ABC Holdings announced a programme")
    assert not name_appears_in("Delta Group", "Delta Holdings announced a programme")


def test_a_single_token_name_is_only_matched_in_full() -> None:
    """Otherwise stripping a suffix turns any 'X Corp' into a match for any 'X Anything'."""
    assert strip_legal_suffix("ABC Corporation") == "abc"
    assert not name_appears_in("ABC Corporation", "ABC Holdings")
    assert name_appears_in("ABC Corporation", "ABC Corporation announced")


def test_a_name_too_short_to_mean_anything_is_refused() -> None:
    assert not name_appears_in("Co", "Co announced")


# -- hypotheses cannot smuggle a name ---------------------------------------

def test_a_hypothesis_has_nowhere_to_put_a_company_name() -> None:
    import dataclasses

    from core.client.models import DiscoveryHypothesis
    from core.client.output_schemas import ORGANIZATION_MENTIONS

    fields = {f.name for f in dataclasses.fields(DiscoveryHypothesis)}
    assert "name" not in fields and "client_name" not in fields

    schema = ORGANIZATION_MENTIONS["properties"]["hypotheses"]["items"]
    assert "name" not in schema["properties"]
    assert schema["additionalProperties"] is False


def test_a_hypothesis_cannot_become_a_candidate() -> None:
    """There is no function that would do it, which is stronger than a rule saying not to."""
    import core.client as client_package

    names = [n for n in dir(client_package) if "hypoth" in n.lower()]
    assert not any("candidate" in n.lower() or "promote" in n.lower() for n in names)


def test_the_criteria_prompt_and_schema_hold_no_organization_field() -> None:
    from core.client.output_schemas import DISCOVERY_CRITERIA

    properties = DISCOVERY_CRITERIA["properties"]
    assert not any(key in properties for key in ("organization", "company", "client_name"))


# -- fit assessments --------------------------------------------------------

def _assess(uploaded, prompts, assessments, findings=None, direct=None):
    organizations = verify_mentions(
        [OrganizationMention(name=ALPHA, evidence_ref="E1",
                             source_id=uploaded.source.source_id, locator="line 1")]
    )
    llm = ScriptedLLM({"fit": [{"discovery_rationale": "우리 센서를 그들의 측정 문제에",
                                "assessments": assessments}]})
    return assess_fit(
        organizations[0],
        findings or [],
        llm=llm,
        prompts=prompts,
        sources_by_id={uploaded.source.source_id: uploaded.source},
        direct_source_ids=direct if direct is not None else {uploaded.source.source_id},
    )


def test_a_favourable_level_with_no_reference_is_lowered(uploaded, prompts) -> None:
    """A STRONG nobody can check is an opinion."""
    assessments, _, rejections, _, _ = _assess(
        uploaded, prompts, [{"criterion": "SOLUTION_FIT", "level": "STRONG", "evidence_refs": []}]
    )
    solution = next(a for a in assessments if a.criterion is FitCriterion.SOLUTION_FIT)
    assert solution.level is FitLevel.EVIDENCE_NEEDED
    assert solution.missing_evidence, "and it says what would settle it"
    assert any(r.code == RejectionCode.NO_FINDING_RESOLVED for r in rejections)


def test_an_unresolvable_reference_is_recorded(uploaded, prompts) -> None:
    findings = [_finding("MN03", uploaded.source.source_id)]
    _, _, rejections, _, _ = _assess(
        uploaded,
        prompts,
        [{"criterion": "PROBLEM_FIT", "level": "STRONG", "evidence_refs": ["F1", "F77"]}],
        findings=findings,
    )
    assert any(r.code == RejectionCode.UNKNOWN_EVIDENCE_REF for r in rejections)


def test_purchasing_potential_needs_a_named_signal(uploaded, prompts) -> None:
    """"They are large, so they can afford it" is not evidence."""
    findings = [_finding("MN03", uploaded.source.source_id)]
    assessments, _, rejections, _, _ = _assess(
        uploaded,
        prompts,
        [{"criterion": "PURCHASING_POTENTIAL", "level": "STRONG", "evidence_refs": ["F1"],
          "reason": "대기업이라 예산이 있을 것이다"}],
        findings=findings,
    )
    purchasing = next(a for a in assessments if a.criterion is FitCriterion.PURCHASING_POTENTIAL)
    assert purchasing.level is FitLevel.EVIDENCE_NEEDED
    assert any(r.code == RejectionCode.NO_QUALIFYING_SIGNAL for r in rejections)


def test_purchasing_potential_with_a_named_signal_is_kept(uploaded, prompts) -> None:
    findings = [_finding("MN03", uploaded.source.source_id)]
    assessments, _, rejections, _, _ = _assess(
        uploaded,
        prompts,
        [{"criterion": "PURCHASING_POTENTIAL", "level": "STRONG", "evidence_refs": ["F1"],
          "signal_type": "PROCUREMENT_ACTIVITY"}],
        findings=findings,
    )
    purchasing = next(a for a in assessments if a.criterion is FitCriterion.PURCHASING_POTENTIAL)
    assert purchasing.level is FitLevel.STRONG
    assert not any(r.code == RejectionCode.NO_QUALIFYING_SIGNAL for r in rejections)


def test_accessibility_needs_a_named_route(uploaded, prompts) -> None:
    """"They are a public body so we can contact them" is the absence of a route."""
    findings = [_finding("MN05", uploaded.source.source_id)]
    assessments, _, rejections, _, _ = _assess(
        uploaded,
        prompts,
        [{"criterion": "ACCESSIBILITY", "level": "STRONG", "evidence_refs": ["F1"],
          "reason": "공공기관이므로 연락할 수 있다"}],
        findings=findings,
    )
    access = next(a for a in assessments if a.criterion is FitCriterion.ACCESSIBILITY)
    assert access.level is FitLevel.EVIDENCE_NEEDED
    assert any(r.code == RejectionCode.NO_QUALIFYING_SIGNAL for r in rejections)


def test_a_snippet_only_strong_is_downgraded_and_flagged(uploaded, prompts) -> None:
    findings = [_finding("MN03", uploaded.source.source_id)]
    assessments, _, _, flags, _ = _assess(
        uploaded,
        prompts,
        [{"criterion": "PROBLEM_FIT", "level": "STRONG", "evidence_refs": ["F1"]}],
        findings=findings,
        direct=set(),  # nothing here has document provenance
    )
    problem = next(a for a in assessments if a.criterion is FitCriterion.PROBLEM_FIT)
    assert problem.level is FitLevel.MODERATE
    assert any(f.code == FlagCodes.SNIPPET_ONLY_DOWNGRADE for f in flags)


def test_a_duplicate_assessment_is_refused(uploaded, prompts) -> None:
    _, _, rejections, _, _ = _assess(
        uploaded,
        prompts,
        [
            {"criterion": "PROBLEM_FIT", "level": "UNKNOWN"},
            {"criterion": "PROBLEM_FIT", "level": "STRONG"},
        ],
    )
    assert any(r.code == RejectionCode.DUPLICATE_ASSESSMENT for r in rejections)


def test_an_invented_criterion_is_refused(uploaded, prompts) -> None:
    _, _, rejections, _, _ = _assess(
        uploaded, prompts, [{"criterion": "VIBES_FIT", "level": "STRONG"}]
    )
    assert any(r.code == RejectionCode.UNUSABLE_CATEGORY for r in rejections)


def test_a_long_reason_is_refused_not_truncated(uploaded, prompts) -> None:
    """Cutting a provider's sentence at 500 characters stores a claim nobody made.

    The schema states the limit, so a longer string is a broken contract. Trimming it would
    change the meaning — possibly reverse it, if the clause that was cut carried the negation —
    and would do so silently, leaving a persisted reason that reads as though someone wrote it.
    So the assessment is refused and the criterion degrades instead.
    """
    long_reason = "가" * 2000
    assessments, _, rejections, _, _ = _assess(
        uploaded, prompts,
        [{"criterion": "PROBLEM_FIT", "level": "STRONG", "reason": long_reason}],
    )
    problem = next(a for a in assessments if a.criterion is FitCriterion.PROBLEM_FIT)

    assert problem.reason is None, "nothing is stored, not even a shortened version"
    assert problem.level is FitLevel.UNKNOWN, "the whole assessment went, not just its reason"
    assert any(r.code == RejectionCode.REASON_TOO_LONG for r in rejections)


def test_a_refused_reason_is_not_reported_as_a_research_gap(uploaded, prompts) -> None:
    """A provider fault is not something a person can go and research."""
    assessments, _, _, _, _ = _assess(
        uploaded, prompts,
        [{"criterion": "PROBLEM_FIT", "level": "STRONG", "reason": "가" * 2000}],
    )
    problem = next(a for a in assessments if a.criterion is FitCriterion.PROBLEM_FIT)
    assert problem.missing_evidence == []


def test_a_refused_reason_leaves_no_trace_of_its_text(uploaded, prompts) -> None:
    assessments, _, rejections, _, _ = _assess(
        uploaded, prompts,
        [{"criterion": "PROBLEM_FIT", "level": "STRONG", "reason": "기밀" * 400}],
    )
    for record in (*assessments, *rejections):
        assert "기밀" not in repr(record) and "기밀" not in str(record)


def test_the_schema_states_the_limit_the_pipeline_enforces() -> None:
    """Otherwise a provider is refused for breaking a rule it was never given."""
    from core.client.output_schemas import FIT_ASSESSMENT

    properties = FIT_ASSESSMENT["properties"]
    assert properties["assessments"]["items"]["properties"]["reason"]["maxLength"] == (
        MAX_FIT_REASON_CHARS
    )
    assert properties["discovery_rationale"]["maxLength"] == MAX_FIT_REASON_CHARS


def test_no_truncation_remains_in_the_fit_stage() -> None:
    """A slice is exactly what this correction removed, so it should not reappear."""
    source = (ROOT / "core/client/fit.py").read_text(encoding="utf-8")
    assert "[:MAX_FIT_REASON_CHARS]" not in source
    assert "_capped" not in source


# -- the entity invariants --------------------------------------------------

def _candidate(**overrides) -> ClientCandidate:
    base = dict(
        project_id=PROJECT,
        client_name=ALPHA,
        country="VN",
        industry="water",
        discovery_rationale="their problem matches our capability",
        source_ids=["src_1"],
        finding_ids=["fnd_1"],
        # The aggregate has to add up, so the finding sits on a criterion rather than only at
        # candidate level — which is the relationship these tests are about.
        fit=[
            FitAssessment(
                criterion=c, finding_ids=["fnd_1"] if c is FitCriterion.PROBLEM_FIT else []
            )
            for c in FitCriterion
        ],
    )
    base.update(overrides)
    return ClientCandidate(**base)


def test_candidate_finding_ids_must_be_the_union_of_the_assessments() -> None:
    """Two copies of the same relationship drift the moment one of them is revised."""
    fit = [
        FitAssessment(criterion=c, finding_ids=["fnd_1"] if c is FitCriterion.PROBLEM_FIT else [])
        for c in FitCriterion
    ]
    violations = evidence.check_client_candidate(
        _candidate(fit=fit, finding_ids=["fnd_1", "fnd_invented"])
    )
    assert any("sorted union" in v for v in violations)


def test_candidate_finding_ids_are_sorted_not_insertion_ordered() -> None:
    """So the same eight assessments always roll up to the same list."""
    fit = [FitAssessment(criterion=c) for c in FitCriterion]
    fit[0].finding_ids = ["fnd_c"]
    fit[3].finding_ids = ["fnd_a"]
    fit[5].finding_ids = ["fnd_b", "fnd_a"]
    assert aggregate_finding_ids(fit) == ["fnd_a", "fnd_b", "fnd_c"]
    assert evidence.check_client_candidate(
        _candidate(fit=fit, finding_ids=["fnd_a", "fnd_b", "fnd_c"])
    ) == []


def test_candidate_missing_evidence_must_be_the_union_of_the_assessments() -> None:
    fit = [FitAssessment(criterion=c) for c in FitCriterion]
    fit[0].missing_evidence = ["budget cycle"]
    violations = evidence.check_client_candidate(
        _candidate(fit=fit, missing_evidence=["something nobody recorded"])
    )
    assert any("missing_evidence is not the sorted union" in v for v in violations)


def test_priority_missing_evidence_cannot_diverge_from_the_assessments() -> None:
    """A gap stated twice must be stated the same way twice."""
    fit = [FitAssessment(criterion=c) for c in FitCriterion]
    fit[0].missing_evidence = ["budget cycle"]
    violations = evidence.check_client_candidate(
        _candidate(
            fit=fit,
            missing_evidence=["budget cycle"],
            priority=PriorityDecision(missing_evidence=["a different gap"]),
        )
    )
    assert any("priority.missing_evidence diverges" in v for v in violations)


def test_the_aggregates_deduplicate_and_ignore_blanks() -> None:
    fit = [FitAssessment(criterion=c) for c in FitCriterion]
    fit[0].missing_evidence = ["budget cycle", "  ", ""]
    fit[1].missing_evidence = ["budget cycle", "approval route"]
    assert aggregate_missing_evidence(fit) == ["approval route", "budget cycle"]


def test_the_llm_is_never_asked_for_candidate_level_aggregates() -> None:
    """They are derived, so asking would invite a second, disagreeing answer."""
    from core.client.output_schemas import ALL_OUTPUT_SCHEMAS

    for name, schema in ALL_OUTPUT_SCHEMAS.items():
        top = schema.get("properties", {})
        assert "finding_ids" not in top, f"{name} asks for candidate finding_ids"
        assert "missing_evidence" not in top, f"{name} asks for candidate missing_evidence"
        assert "priority" not in top and "band" not in top


def test_a_candidate_without_discovery_provenance_is_invalid() -> None:
    violations = evidence.check_client_candidate(_candidate(source_ids=[]))
    assert violations and "source_ids is empty" in violations[0]


def test_source_ids_are_checked_against_known_sources() -> None:
    violations = evidence.check_client_candidate(
        _candidate(source_ids=["src_invented"]), known_source_ids=["src_1"]
    )
    assert violations and "unknown source_ids" in violations[0]


def test_all_eight_criteria_must_be_present() -> None:
    partial = [FitAssessment(criterion=FitCriterion.PROBLEM_FIT)]
    violations = evidence.check_client_candidate(_candidate(fit=partial))
    assert violations and "no assessment for" in violations[0]


def test_a_duplicated_criterion_is_invalid() -> None:
    doubled = [FitAssessment(criterion=c) for c in FitCriterion]
    doubled.append(FitAssessment(criterion=FitCriterion.PROBLEM_FIT))
    violations = evidence.check_client_candidate(_candidate(fit=doubled))
    assert any("duplicate" in v for v in violations)


def test_a_favourable_level_without_references_is_invalid() -> None:
    fit = [FitAssessment(criterion=c) for c in FitCriterion]
    fit[0] = FitAssessment(criterion=FitCriterion.PROBLEM_FIT, level=FitLevel.STRONG)
    violations = evidence.check_client_candidate(_candidate(fit=fit))
    assert any("STRONG with no finding_ids or source_ids" in v for v in violations)


def test_evidence_needed_without_a_gap_is_invalid() -> None:
    fit = [FitAssessment(criterion=c) for c in FitCriterion]
    fit[0] = FitAssessment(criterion=FitCriterion.PROBLEM_FIT, level=FitLevel.EVIDENCE_NEEDED)
    violations = evidence.check_client_candidate(_candidate(fit=fit))
    assert any("what evidence would settle it" in v for v in violations)


# -- nothing invalid reaches storage ---------------------------------------

def test_an_invented_organization_never_reaches_storage(uploaded, prompts) -> None:
    """End to end: the model names companies the evidence never mentions, and nothing is stored."""
    llm = ScriptedLLM(
        {
            "criteria": [{"relevant_problem": "측정 주기", "our_capability": "다항목 측정"}],
            "organizations": [{"mentions": [
                {"name": "Pan-Asia Heavy Electronics", "evidence_ref": "E1"},
                {"name": "Northern Delta Engineering", "evidence_ref": "E1"},
            ]}],
        }
    )
    outcome = run_discovery(
        project=Project(project_id=PROJECT, company_name="Fictional Sensing",
                        market_scope=[MarketScope.INTERNATIONAL]),
        candidates=uploaded.candidates,
        sources=[uploaded.source],
        findings=[_finding("MN03", uploaded.source.source_id)],
        key_issues=[],
        llm=llm,
        prompts=prompts,
        capability="다항목 측정",
        solution="단일 모듈 센서",
    )

    storage = MemoryStorage()
    persist(outcome, storage)

    assert outcome.candidates == []
    assert storage.get_clients(PROJECT) == []
    assert len(outcome.rejections) == 2
    assert all(r.code == RejectionCode.NAME_NOT_IN_EVIDENCE for r in outcome.rejections)


def test_a_candidate_with_no_rationale_is_refused_whole(uploaded, prompts) -> None:
    llm = ScriptedLLM(
        {
            "organizations": [{"mentions": [{"name": ALPHA, "evidence_ref": "E1"}]}],
            "fit": [{"discovery_rationale": None, "assessments": []}],
        }
    )
    outcome = run_discovery(
        project=Project(project_id=PROJECT, company_name="Fictional Sensing"),
        candidates=uploaded.candidates,
        sources=[uploaded.source],
        findings=[_finding("MN03", uploaded.source.source_id)],
        key_issues=[],
        llm=llm,
        prompts=prompts,
        capability="c",
        solution="s",
    )
    assert outcome.candidates == []
    assert any(r.code == RejectionCode.EMPTY_STATEMENT for r in outcome.rejections)


def test_rejections_carry_no_company_name(uploaded, prompts) -> None:
    """A diagnostic that names the client defeats the logging rules."""
    _, _, rejections, _ = _find(
        uploaded, prompts, {"mentions": [{"name": "Invented Holdings", "evidence_ref": "E1"}]}
    )
    assert rejections
    for rejection in rejections:
        assert "Invented" not in str(rejection) and "Invented" not in repr(rejection)


def test_organization_mentions_do_not_print_their_span() -> None:
    mention = OrganizationMention(
        name=ALPHA, evidence_ref="E1", source_id="src_1", locator="line 1",
        verbatim="조달 공고에 계측 설비 교체가 포함되어 있다",
    )
    assert "조달" not in repr(mention)
    assert ALPHA not in repr(mention)
