# -*- coding: utf-8 -*-
"""
Core entities for the Client Discovery Harness.

Every persisted entity in this harness is defined here, and only here. The JSON Schema files
in ``schemas/`` mirror these dataclasses field for field; ``tests/test_schemas.py`` fails if the
two drift apart. Adding a field means touching three places at once — this module, the matching
schema, and ``docs/data-model.md`` (see ARCHITECTURE.md section 5).

This module is deliberately free of side effects: no file access, no environment lookup, no
network, no logging. ``tests/test_core_purity.py`` enforces that for the whole ``core`` package.

Design notes that are easy to get wrong later:

* **No user-facing prose in enums.** Enum values are stable codes (``HIGH``, ``STRONG``,
  ``FACT``). Labels for people live in ``locales/ko.json`` and ``locales/en.json`` and are
  applied by the application layer, never here.
* **No invented numbers.** Fit and confidence are ordinal enums, not scores. ``UNKNOWN`` and
  ``EVIDENCE_NEEDED`` are first-class values precisely so that a missing answer stays visible
  instead of being rounded into a percentage.
* **SourceMetadata holds no original filename and no document text**, by design — see
  ``docs/privacy.md``.
"""
from __future__ import annotations

import dataclasses
import types
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Union, get_args, get_origin, get_type_hints
from uuid import uuid4

SCHEMA_VERSION = "0.1"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def new_id(prefix: str) -> str:
    """Random, opaque identifier.

    Identifiers never encode anything about their origin — in particular a source identifier
    must not be derived from the uploaded filename (``docs/privacy.md``).
    """
    return f"{prefix}_{uuid4().hex}"


def utc_now() -> str:
    """Current time as an ISO-8601 string with timezone, second resolution."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def as_dict(obj: Any) -> Any:
    """Convert an entity (or list/dict of entities) into plain JSON-ready data.

    Enum members become their string values so the result can be handed straight to
    ``json.dumps`` or to a JSON Schema validator.
    """
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: as_dict(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: as_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [as_dict(v) for v in obj]
    return obj


def _coerce(annotation: Any, value: Any) -> Any:
    """Turn plain JSON data into the type an entity field declares."""
    if value is None:
        return None

    origin = get_origin(annotation)

    if origin is Union or origin is types.UnionType:
        candidates = [a for a in get_args(annotation) if a is not type(None)]
        return _coerce(candidates[0], value) if candidates else value

    if origin in (list, tuple):
        args = get_args(annotation)
        inner = args[0] if args else Any
        return [_coerce(inner, item) for item in value]

    if isinstance(annotation, type):
        if issubclass(annotation, Enum):
            return annotation(value)
        if dataclasses.is_dataclass(annotation):
            return from_dict(annotation, value)

    return value


def from_dict(entity_cls: type, data: dict) -> Any:
    """Rebuild an entity from plain JSON data — the counterpart of :func:`as_dict`.

    Strict on purpose: an unexpected key raises rather than being dropped. A stored record that
    no longer matches the entity is a schema drift that someone needs to see, not something to
    silently discard half of.
    """
    hints = get_type_hints(entity_cls)
    known = {f.name for f in dataclasses.fields(entity_cls)}

    unknown = sorted(set(data) - known)
    if unknown:
        raise ValueError(
            f"{entity_cls.__name__}: unknown field(s) {unknown}. "
            f"Known fields: {sorted(known)}"
        )

    return entity_cls(
        **{key: _coerce(hints.get(key, Any), value) for key, value in data.items()}
    )


# ---------------------------------------------------------------------------
# enums
# ---------------------------------------------------------------------------

class EvidenceType(str, Enum):
    """Whether a finding is grounded, inferred, assumed, or still missing."""

    FACT = "FACT"
    INFERENCE = "INFERENCE"
    ASSUMPTION = "ASSUMPTION"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class FitLevel(str, Enum):
    """Ordinal fit rating. Never converted into a number or summed into a total."""

    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    UNKNOWN = "UNKNOWN"
    EVIDENCE_NEEDED = "EVIDENCE_NEEDED"


class MarketScope(str, Enum):
    DOMESTIC = "DOMESTIC"
    INTERNATIONAL = "INTERNATIONAL"


class SWOTCategory(str, Enum):
    STRENGTH = "STRENGTH"
    WEAKNESS = "WEAKNESS"
    OPPORTUNITY = "OPPORTUNITY"
    THREAT = "THREAT"


class SalesPriority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    DEFERRED = "DEFERRED"
    UNKNOWN = "UNKNOWN"


class SourceCategory(str, Enum):
    """What kind of material this is, in business terms."""

    CONSULTING_OUTPUT = "CONSULTING_OUTPUT"
    COMPANY_DATA = "COMPANY_DATA"
    EXTERNAL_BUSINESS_DATA = "EXTERNAL_BUSINESS_DATA"
    USER_PROVIDED = "USER_PROVIDED"


class SourceOrigin(str, Enum):
    """How the material reached the harness.

    Separate from :class:`SourceCategory`, which says what the material *is*. A market report
    can be EXTERNAL_BUSINESS_DATA whether somebody uploaded the PDF or a search returned the
    page, and the two cases need different provenance fields — a file has a type and a size, a
    retrieved page has a publisher and a URL. Giving a search result a fabricated ``file_type``
    so it fits a file-shaped record would be a lie in the provenance trail.
    """

    UPLOADED_FILE = "UPLOADED_FILE"
    SEARCH_RESULT = "SEARCH_RESULT"
    USER_PROVIDED = "USER_PROVIDED"


class FileType(str, Enum):
    PDF = "PDF"
    DOCX = "DOCX"
    PPTX = "PPTX"
    XLSX = "XLSX"
    HTML = "HTML"
    CSV = "CSV"
    TXT = "TXT"
    MD = "MD"


class ProcessingStatus(str, Enum):
    PENDING = "PENDING"
    EXTRACTED = "EXTRACTED"
    FAILED = "FAILED"
    PURGED = "PURGED"


class StorageMode(str, Enum):
    EPHEMERAL = "EPHEMERAL"
    PERSISTENT = "PERSISTENT"


class ClientStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    SCREENED = "SCREENED"
    PRIORITIZED = "PRIORITIZED"
    ANALYZED = "ANALYZED"
    PROPOSAL_DRAFTED = "PROPOSAL_DRAFTED"
    DEFERRED = "DEFERRED"
    REJECTED = "REJECTED"


class ProposalStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    STRATEGY_DRAFTED = "STRATEGY_DRAFTED"
    PRICING_REQUESTED = "PRICING_REQUESTED"
    PROPOSAL_DRAFTED = "PROPOSAL_DRAFTED"


class PricingStatus(str, Enum):
    NOT_REQUESTED = "NOT_REQUESTED"
    PAYLOAD_READY = "PAYLOAD_READY"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# value objects
# ---------------------------------------------------------------------------

@dataclass
class EvidenceRef:
    """A pointer from an analysis back to the finding (and source) it rests on."""

    finding_id: str
    source_id: Optional[str] = None
    note: Optional[str] = None


@dataclass
class FitScreening:
    """First three of the eight prioritisation criteria (HARNESS.md section 7)."""

    problem_fit: FitLevel = FitLevel.UNKNOWN
    solution_fit: FitLevel = FitLevel.UNKNOWN
    capability_fit: FitLevel = FitLevel.UNKNOWN


@dataclass
class PriorityEvaluation:
    """Remaining five criteria plus the human-assigned priority.

    ``sales_priority`` is a decision, not a computed value. Nothing in this harness derives it
    from the five ratings — a person does.
    """

    market_attractiveness: FitLevel = FitLevel.UNKNOWN
    purchasing_potential: FitLevel = FitLevel.UNKNOWN
    accessibility: FitLevel = FitLevel.UNKNOWN
    competitive_situation: FitLevel = FitLevel.UNKNOWN
    evidence_quality: FitLevel = FitLevel.UNKNOWN
    sales_priority: SalesPriority = SalesPriority.UNKNOWN
    rationale: Optional[str] = None


@dataclass
class InternationalContext:
    """Extra fields filled in only when ``market_scope`` is ``INTERNATIONAL``.

    Kept in its own object rather than as twelve optional columns so that a domestic project
    never carries empty international fields around.
    """

    local_buyer: Optional[str] = None
    local_competitor: Optional[str] = None
    regulation: Optional[str] = None
    certification: Optional[str] = None
    tariff: Optional[str] = None
    logistics: Optional[str] = None
    exchange_rate: Optional[str] = None
    local_partner: Optional[str] = None
    distribution_structure: Optional[str] = None
    local_price: Optional[str] = None
    purchasing_power: Optional[str] = None
    entry_barrier: Optional[str] = None


# ---------------------------------------------------------------------------
# entities
# ---------------------------------------------------------------------------

@dataclass
class Project:
    """One analysis engagement: a company, the markets it is aiming at, and language settings.

    The four language axes are deliberately independent: the operator may work in Korean while
    the sources are Vietnamese and the output is English.
    """

    company_name: str
    market_scope: list[MarketScope] = field(default_factory=lambda: [MarketScope.DOMESTIC])
    target_countries: list[str] = field(default_factory=list)  # ISO 3166-1 alpha-2
    target_industries: list[str] = field(default_factory=list)
    ui_lang: str = "ko"
    output_lang: str = "ko"
    storage_mode: StorageMode = StorageMode.EPHEMERAL
    project_id: str = field(default_factory=lambda: new_id("prj"))
    created_at: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION


@dataclass
class SourceMetadata:
    """Where a piece of evidence came from — for an uploaded file or a retrieved page alike.

    There is no ``filename`` field and no text field on purpose. The original file name can
    itself be sensitive (client names, project codes) and document text must never be persisted
    in ephemeral mode. See ``docs/privacy.md``.

    ``display_label`` is the one piece of human-chosen text kept here, and it is a different
    thing from a filename: it is what the person uploading typed in order to recognise this
    source later, and nothing derives it from the upload.

    The record covers both origins without pretending they are the same shape. A file has
    ``file_type``, ``file_size`` and ``page_count``; a search result has ``title``,
    ``publisher``, ``url`` and ``retrieved_at``. Whichever set does not apply stays ``None``
    rather than being filled with a plausible-looking value — a fabricated ``file_type`` on a
    web page would corrupt the provenance trail it exists to protect.
    ``core.evidence.check_source_metadata`` enforces that separation.
    """

    project_id: str
    source_origin: SourceOrigin
    source_category: SourceCategory
    source_id: str = field(default_factory=lambda: new_id("src"))
    display_label: Optional[str] = None

    # UPLOADED_FILE only
    file_type: Optional[FileType] = None
    file_size: Optional[int] = None
    page_count: Optional[int] = None

    # SEARCH_RESULT only
    title: Optional[str] = None
    publisher: Optional[str] = None
    url: Optional[str] = None
    retrieved_at: Optional[str] = None

    source_date: Optional[str] = None
    detected_lang: Optional[str] = None
    processing_status: ProcessingStatus = ProcessingStatus.PENDING
    error_code: Optional[str] = None
    ingested_at: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION


@dataclass
class ResearchFinding:
    """Evidence interpreted through a Master Note lens. The atom of this harness.

    ``mn_basis`` records which analysis framework produced the reading, so a finding can always
    be traced both back to its source and back to the question that prompted it.
    """

    project_id: str
    finding: str
    evidence_type: EvidenceType
    mn_basis: list[str] = field(default_factory=list)
    confidence: Confidence = Confidence.UNKNOWN
    market_scope: MarketScope = MarketScope.DOMESTIC
    #: For an INFERENCE: the findings it was reasoned from. Empty for every other type.
    #:
    #: An inference points at other findings rather than at a source, because that is what it
    #: actually rests on. Copying the first supporting finding's ``source_id`` onto it would
    #: make a conclusion look like something a document said.
    supporting_finding_ids: list[str] = field(default_factory=list)
    source_id: Optional[str] = None
    source_type: Optional[SourceCategory] = None
    page_or_section: Optional[str] = None
    source_date: Optional[str] = None
    evidence_summary: Optional[str] = None
    country: Optional[str] = None
    finding_id: str = field(default_factory=lambda: new_id("fnd"))
    lang: str = "ko"
    created_at: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION


@dataclass
class SWOTIssue:
    """A compressed conclusion, never a starting point.

    ``finding_ids`` must not be empty: a SWOT item that cannot name the findings behind it is
    rejected by ``core.evidence``.

    This holds the classification and nothing else. The key issue and its strategic implication
    are :class:`KeyIssue`, a separate record — a real issue ("which market do we go after
    first?") usually arises from several SWOT items at once, and a string field on one card
    cannot say that.
    """

    project_id: str
    category: SWOTCategory
    statement: str
    finding_ids: list[str] = field(default_factory=list)
    mn_basis: list[str] = field(default_factory=list)
    issue_id: str = field(default_factory=lambda: new_id("swt"))
    lang: str = "ko"
    created_at: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION


@dataclass
class KeyIssue:
    """A decision the evidence has brought into focus, and what it implies.

    Binds together the SWOT items and findings that create the question, which is why it is its
    own record rather than a field on a SWOT card. Phase 4 consumes these: client discovery
    needs a stable thing to point at when it says "we are pursuing this market because of that
    issue".

    ``strategic_implication`` is **required** and is decision *support*, not a decision.
    "Enter the Vietnamese market" is not an acceptable value; "on current evidence A looks
    favourable, but B and C are unverified, so they need checking before client discovery" is.

    Required because a key issue without it is an observation, and a record stored with the
    field blanked reads to a later reader exactly like a finished one. The pipeline refuses such
    a candidate outright rather than persisting part of it.
    """

    project_id: str
    statement: str
    decision_area: str
    swot_issue_ids: list[str] = field(default_factory=list)
    finding_ids: list[str] = field(default_factory=list)
    strategic_implication: Optional[str] = None
    missing_evidence: list[str] = field(default_factory=list)
    confidence: Confidence = Confidence.UNKNOWN
    mn_basis: list[str] = field(default_factory=list)
    key_issue_id: str = field(default_factory=lambda: new_id("kis"))
    lang: str = "ko"
    created_at: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION


@dataclass
class ClientCandidate:
    """A prospect found by capability/solution/opportunity/problem/purchasing alignment.

    ``discovery_rationale`` answers the only question that matters here: what of ours can be
    sold to which problem of theirs. A name with no rationale is a company list entry, not a
    candidate.
    """

    project_id: str
    client_name: str
    country: str
    industry: str
    discovery_rationale: str
    market_scope: MarketScope = MarketScope.DOMESTIC
    finding_ids: list[str] = field(default_factory=list)
    fit_screening: FitScreening = field(default_factory=FitScreening)
    priority: PriorityEvaluation = field(default_factory=PriorityEvaluation)
    status: ClientStatus = ClientStatus.CANDIDATE
    client_id: str = field(default_factory=lambda: new_id("cli"))
    lang: str = "ko"
    created_at: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION


@dataclass
class ClientAnalysis:
    """Deep analysis of one prioritised client, using MN03/MN04/MN05/MN06 only.

    MN02 and MN07 are company-level diagnoses and are not repeated per client — see
    HARNESS.md section 5.
    """

    project_id: str
    client_id: str
    client_name: str
    country: str
    industry: str

    # MN03 — customer, buyer, problem
    company_summary: Optional[str] = None
    business_issue: Optional[str] = None
    user: Optional[str] = None
    buyer: Optional[str] = None
    decision_maker: Optional[str] = None
    problem: Optional[str] = None
    problem_severity: Optional[str] = None

    # MN04 — value proposition, competitive advantage, positioning
    current_solution: Optional[str] = None
    competitor: Optional[str] = None
    substitute: Optional[str] = None
    kbf: Optional[str] = None
    our_solution: Optional[str] = None
    value_proposition: Optional[str] = None
    competitive_advantage: Optional[str] = None

    # MN05 — business model, access route
    sales_access_route: Optional[str] = None
    potential_partner: Optional[str] = None

    # MN06 — cost, price, revenue model
    pricing_implication: Optional[str] = None

    evidence: list[EvidenceRef] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    sales_priority: SalesPriority = SalesPriority.UNKNOWN
    market_scope: MarketScope = MarketScope.DOMESTIC
    international: Optional[InternationalContext] = None
    mn_basis: list[str] = field(default_factory=lambda: ["MN03", "MN04", "MN05", "MN06"])
    analysis_id: str = field(default_factory=lambda: new_id("cla"))
    lang: str = "ko"
    created_at: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION


@dataclass
class ProposalStrategy:
    """The strategy that precedes a proposal document.

    No proposal is drafted before this exists. ``pricing_input`` is the hand-off point to the
    pricing harness and stays ``None`` until Phase 7 fills it.
    """

    project_id: str
    client_id: str
    client_name: str
    country: str
    problem: Optional[str] = None
    buyer: Optional[str] = None
    decision_maker: Optional[str] = None
    proposal_objective: Optional[str] = None
    proposed_solution: Optional[str] = None
    value_proposition: Optional[str] = None
    competitive_advantage: Optional[str] = None
    key_message: Optional[str] = None
    proposal_storyline: list[str] = field(default_factory=list)
    expected_objection: list[str] = field(default_factory=list)
    response_logic: list[str] = field(default_factory=list)
    additional_evidence_required: list[str] = field(default_factory=list)
    evidence: list[EvidenceRef] = field(default_factory=list)
    pricing_input: Optional[dict] = None
    status: ProposalStatus = ProposalStatus.NOT_STARTED
    strategy_id: str = field(default_factory=lambda: new_id("prp"))
    lang: str = "ko"
    created_at: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION


@dataclass
class PricingResult:
    """Hand-off to, and answer from, the separate pricing harness.

    ``pricing_payload`` conforms to that harness's ``client_input.schema.json``.
    ``commercial_context`` carries the sales context (client, country, problem, buyer, value
    proposition, competitor, channel, conditions) that the pricing engine does **not** consume
    but the proposal does. Keeping them apart is what lets the two harnesses version
    independently — see ARCHITECTURE.md section 6.
    """

    project_id: str
    client_id: str
    pricing_payload: dict = field(default_factory=dict)
    commercial_context: dict = field(default_factory=dict)
    engine_result: Optional[dict] = None
    engine_version: Optional[str] = None
    status: PricingStatus = PricingStatus.NOT_REQUESTED
    error_code: Optional[str] = None
    pricing_result_id: str = field(default_factory=lambda: new_id("prc"))
    created_at: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION


ENTITIES = (
    Project,
    SourceMetadata,
    ResearchFinding,
    SWOTIssue,
    KeyIssue,
    ClientCandidate,
    ClientAnalysis,
    ProposalStrategy,
    PricingResult,
)
"""The nine persisted entities, in workflow order. ``tests/test_schemas.py`` walks this tuple."""
