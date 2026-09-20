# -*- coding: utf-8 -*-
"""Why a pricing hand-off was refused, and what a reader should look at.

The split between the two sets is the phase's central judgement about authority.

**Rejections are ours.** A solution element nobody selected, a value that is not one of the
contract's closed codes, a source reference that is not an opaque identifier — these are
breaches of a contract this repository owns, and the payload is not built.

**Flags are theirs.** ``dependency_rules.md`` in the pricing harness decides what its engine
treats as an error, and that authority does not move here just because we can see the same
condition earlier. A configuration that its engine will reject is flagged, passed through
untouched, and judged where it belongs. Nothing is auto-corrected, no value is dropped, and no
allocation is rewritten — a bridge that quietly fixes the other side's input makes the two
repositories disagree about what was actually asked.
"""
from __future__ import annotations

STAGE = "pricing_handoff"


class PricingRejectionCode:
    """Breaches of this repository's own contract. Codes, never the values that breached it."""

    #: A price component bound to a ref the strategy never selected. Refused whole rather than
    #: dropped: a payload missing one component silently under-prices the proposal.
    UNKNOWN_SOLUTION_ELEMENT = "UNKNOWN_SOLUTION_ELEMENT"
    #: No ``contract_version``. There is no default — the version belongs to the other
    #: repository and guessing it is how a payload gets validated against the wrong contract.
    MISSING_CONTRACT_VERSION = "MISSING_CONTRACT_VERSION"
    #: Their contract requires at least one price component.
    NO_PRICE_COMPONENT = "NO_PRICE_COMPONENT"
    DUPLICATE_COMPONENT_ID = "DUPLICATE_COMPONENT_ID"
    DUPLICATE_COST_ITEM_ID = "DUPLICATE_COST_ITEM_ID"
    #: A value outside one of the contract's closed sets.
    UNKNOWN_CONTRACT_VALUE = "UNKNOWN_CONTRACT_VALUE"
    #: A cost item pointing at a component that is not in this payload, and not "shared".
    COST_TARGETS_UNKNOWN_COMPONENT = "COST_TARGETS_UNKNOWN_COMPONENT"
    #: A required identifier or currency left blank.
    MISSING_CONTRACT_FIELD = "MISSING_CONTRACT_FIELD"
    #: A provenance reference that is not an opaque identifier. A filename, a path or a URL
    #: would travel out of this process inside the payload — docs/privacy.md section 3.
    UNSAFE_SOURCE_REF = "UNSAFE_SOURCE_REF"
    #: The strategy does not read the analysis it was given.
    UNKNOWN_ANALYSIS = "UNKNOWN_ANALYSIS"
    #: The strategy and the analysis belong to different clients.
    CLIENT_MISMATCH = "CLIENT_MISMATCH"
    #: More components or cost items than the policy allows.
    TOO_MANY_ITEMS = "TOO_MANY_ITEMS"
    #: The assembled payload failed this repository's own strict shape check.
    PAYLOAD_INVALID = "PAYLOAD_INVALID"
    #: The assembled record failed its Evidence invariants, so nothing is stored.
    RESULT_INVALID = "RESULT_INVALID"
    #: An engine result whose case or client is not this one. In a file contract the wrong
    #: file can be handed back, and a silently attached one is a wrong answer with a right
    #: shape.
    ENGINE_RESULT_MISMATCH = "ENGINE_RESULT_MISMATCH"
    #: An engine result that does not carry the ``source`` block its own contract requires.
    ENGINE_RESULT_MALFORMED = "ENGINE_RESULT_MALFORMED"
    #: An acknowledgement naming a gap this strategy does not have. The caller is working
    #: from a view that has changed, so the approval they believe they gave is not the one
    #: that would be recorded. Never ignored quietly.
    UNKNOWN_GAP_REF = "UNKNOWN_GAP_REF"


PRICING_REJECTION_CODES = frozenset(
    value
    for name, value in vars(PricingRejectionCode).items()
    if not name.startswith("_") and isinstance(value, str)
)


class PricingFlagCode:
    """Worth a reader's attention. Nothing here discards or alters anything."""

    #: Selected and offered, but no price component names it. Partial quoting is legitimate,
    #: so this is a flag; the reader decides whether the omission was intended.
    ELEMENT_NOT_PRICED = "ELEMENT_NOT_PRICED"
    #: An open BEFORE_PRICING gap held the hand-off back.
    BEFORE_PRICING_GAP_OPEN = "BEFORE_PRICING_GAP_OPEN"
    #: A person acknowledged every open BEFORE_PRICING gap and the hand-off proceeded.
    GAPS_ACKNOWLEDGED = "GAPS_ACKNOWLEDGED"
    #: A configuration the pricing harness's own dependency rules will reject or cannot use.
    #: Passed through unchanged — that engine is the authority on its rules.
    DEPENDENCY_RULE_RISK = "DEPENDENCY_RULE_RISK"
    #: The payload was checked against this repository's shape rules only, because no path to
    #: the real ``client_input.schema.json`` was supplied. Not the same as passing it.
    EXTERNAL_CONTRACT_NOT_CHECKED = "EXTERNAL_CONTRACT_NOT_CHECKED"
    #: A real gap was acknowledged that was never blocking. Nothing was unlocked by it; the
    #: flag stops a reader concluding the gate honoured it.
    NON_BLOCKING_GAP_ACKNOWLEDGED = "NON_BLOCKING_GAP_ACKNOWLEDGED"


PRICING_FLAG_CODES = frozenset(
    value
    for name, value in vars(PricingFlagCode).items()
    if not name.startswith("_") and isinstance(value, str)
)
