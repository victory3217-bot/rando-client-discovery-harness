# -*- coding: utf-8 -*-
"""What each dimension is, what may establish it, and how far it may be trusted.

This is the rule table of Phase 5 and the file to read first. Three things live here and
nothing else does: which Master Note supplies the lens, what kind of statement a dimension
produces, and the highest confidence it may carry.

**Kind is the important one.** It decides whether a claim can ever be a FACT, and it is a
property of the *question*, not of the evidence answering it:

``DIRECT``
    The document says it. "Their procurement division issued a notice" is reported, not
    concluded, so a FACT finding behind it makes the claim a FACT.
``MIXED``
    Usually concluded, occasionally stated outright. A tender's published evaluation table
    really does say what the buying factors are; most of the time KBF is inferred. FACT needs a
    FACT finding read through this dimension's own framework.
``SYNTHESIS``
    Always a conclusion. Three FACT findings joined into "this is our competitive advantage"
    produce an inference, not a fact — the joining is the claim, and no document performed it.

That last rule is the one worth stating twice: a claim's evidence type is **not** a copy of its
supporting findings'. Deriving it as the weakest supporting type would promote every synthesis
to FACT as soon as its inputs were solid, which is exactly backwards.
"""
from __future__ import annotations

from enum import Enum

from core.models import AnalysisDimension, Confidence, InternationalDimension

D = AnalysisDimension
I = InternationalDimension


class Kind(str, Enum):
    """Whether a dimension reports, sometimes reports, or always concludes."""

    DIRECT = "DIRECT"
    MIXED = "MIXED"
    SYNTHESIS = "SYNTHESIS"


#: Which Master Note lens each dimension is read through.
#:
#: MN05 contributes only channel, customer relationship and partner: resource, activity and BM
#: alignment diagnose *our* business model and do not become per-client questions. MN06
#: contributes only price, revenue model and pricing structure as lenses on the client's
#: commercial situation — cost, margin and channel cost are ours, and belong to Phase 7.
DIMENSION_FRAMEWORK: dict[AnalysisDimension, str] = {
    D.USER: "MN03",
    D.BUYER: "MN03",
    D.DECISION_MAKER: "MN03",
    D.BUDGET_OWNER: "MN03",
    D.PROBLEM: "MN03",
    D.PROBLEM_SEVERITY: "MN03",
    D.CURRENT_WORKAROUND: "MN03",
    D.KBF: "MN03",
    D.CURRENT_SOLUTION: "MN04",
    D.COMPETITOR: "MN04",
    D.SUBSTITUTE: "MN04",
    D.VALUE_PROPOSITION: "MN04",
    D.COMPETITIVE_ADVANTAGE: "MN04",
    D.SALES_ACCESS_ROUTE: "MN05",
    D.PARTNER: "MN05",
    D.VALUE_DRIVER: "MN06",
    D.PRICE_SENSITIVITY: "MN06",
    D.BUDGET_EVIDENCE: "MN06",
    D.PROCUREMENT_CONTEXT: "MN06",
}

#: The four groups the analysis runs in. Nineteen answers in one response get the last few
#: filled in carelessly; four framework-shaped questions do not.
FRAMEWORK_GROUPS: tuple[str, ...] = ("MN03", "MN04", "MN05", "MN06")


def dimensions_for(framework_id: str) -> tuple[AnalysisDimension, ...]:
    """The dimensions belonging to one Master Note, in declaration order."""
    return tuple(d for d in AnalysisDimension if DIMENSION_FRAMEWORK[d] == framework_id)


DIMENSION_KIND: dict[AnalysisDimension, Kind] = {
    # -- DIRECT: a document states it ---------------------------------------
    D.USER: Kind.DIRECT,
    D.BUYER: Kind.DIRECT,
    D.DECISION_MAKER: Kind.DIRECT,
    D.BUDGET_OWNER: Kind.DIRECT,
    D.PROBLEM: Kind.DIRECT,
    D.CURRENT_WORKAROUND: Kind.DIRECT,
    D.CURRENT_SOLUTION: Kind.DIRECT,
    D.COMPETITOR: Kind.DIRECT,
    D.SUBSTITUTE: Kind.DIRECT,
    D.PARTNER: Kind.DIRECT,
    D.BUDGET_EVIDENCE: Kind.DIRECT,
    D.PROCUREMENT_CONTEXT: Kind.DIRECT,
    # -- MIXED: occasionally stated outright --------------------------------
    D.PROBLEM_SEVERITY: Kind.MIXED,
    D.KBF: Kind.MIXED,
    D.SALES_ACCESS_ROUTE: Kind.MIXED,
    # -- SYNTHESIS: the claim is the joining --------------------------------
    D.VALUE_DRIVER: Kind.SYNTHESIS,
    D.PRICE_SENSITIVITY: Kind.SYNTHESIS,
    D.VALUE_PROPOSITION: Kind.SYNTHESIS,
    D.COMPETITIVE_ADVANTAGE: Kind.SYNTHESIS,
}

#: The highest confidence each dimension may reach, applied on top of the ordinary research
#: rules in ``core/research/confidence.py``.
#:
#: Most dimensions have no ceiling here. A dimension is not capped for being part of Phase 5 —
#: if a dated, attributed, corroborated document states who the incumbent supplier is, the
#: existing rules may reach HIGH and nothing in this file overrides that.
#:
#: The listed ones are capped for a reason specific to them:
#:
#: * who buys, who decides, who owns the budget, and what the money and procurement rules are —
#:   these change without announcement, and a public document describes the arrangement on the
#:   day it was written. Sales calls have been wasted on org charts two reorganisations old.
#: * value driver and price sensitivity read a customer's willingness to pay off evidence that
#:   was not written about willingness to pay. They are readings, and useful ones, but LOW is
#:   what a reading of that kind is worth.
DIMENSION_CEILING: dict[AnalysisDimension, Confidence] = {
    D.BUYER: Confidence.MEDIUM,
    D.DECISION_MAKER: Confidence.MEDIUM,
    D.BUDGET_OWNER: Confidence.MEDIUM,
    D.BUDGET_EVIDENCE: Confidence.MEDIUM,
    D.PROCUREMENT_CONTEXT: Confidence.MEDIUM,
    D.COMPETITIVE_ADVANTAGE: Confidence.MEDIUM,
    D.VALUE_DRIVER: Confidence.LOW,
    D.PRICE_SENSITIVITY: Confidence.LOW,
}

#: VALUE_PROPOSITION is the one dimension whose ceiling depends on another claim: with the
#: buying factors established it is a reading of a known standard, without them a hypothesis
#: about an unknown one. See ``core/analysis/claims.py``.
VALUE_PROPOSITION_CEILING_WITH_KBF = Confidence.MEDIUM
VALUE_PROPOSITION_CEILING_WITHOUT_KBF = Confidence.LOW

#: Dimensions whose answer may be a specific organization. A name on one of these has to pass
#: ``core.client.verify`` against the passage cited for it, exactly as in discovery.
NAMED_ORGANIZATION_DIMENSIONS: frozenset[AnalysisDimension] = frozenset(
    {D.CURRENT_SOLUTION, D.COMPETITOR, D.SUBSTITUTE, D.PARTNER}
)

#: Dimensions that may carry a named :class:`~core.models.AccessRoute`.
ROUTE_DIMENSIONS: frozenset[AnalysisDimension] = frozenset({D.SALES_ACCESS_ROUTE})

#: A competitive advantage needs a comparison. One of these has to be established before the
#: claim can be, because "we are better" with nothing named on the other side is a description
#: of our product.
COMPARATOR_DIMENSIONS: tuple[AnalysisDimension, ...] = (
    D.CURRENT_SOLUTION,
    D.COMPETITOR,
    D.SUBSTITUTE,
)

#: International dimensions are all DIRECT: each one asks what a rule, a cost or a requirement
#: actually is. Inferring a tariff is not analysis, it is guessing at a published number.
INTERNATIONAL_FRAMEWORK: dict[InternationalDimension, str] = {
    I.LOCAL_BUYING_STRUCTURE: "MN03",
    I.REGULATION: "MN05",
    I.CERTIFICATION: "MN05",
    I.TARIFF: "MN06",
    I.LOGISTICS: "MN05",
    I.CURRENCY_FX: "MN06",
    I.ENTRY_BARRIER: "MN04",
    I.LOCAL_PARTNER_REQUIREMENT: "MN05",
}

INTERNATIONAL_CEILING: Confidence = Confidence.MEDIUM
