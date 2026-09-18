---
id: diagnosis/derive-key-issues
stage: diagnosis
output_schema: core.research.output_schemas.KEY_ISSUE_BATCH
requires: [swot_issues, findings, output_lang]
---

# Purpose

Identify the decisions this evidence has brought into focus, and set out what it implies for
each. A key issue binds several SWOT items together — it is the question a person now has to
answer, not a summary of what was found.

# Required input

SWOT items, each prefixed with a reference key such as `[S1]`.

# Expected output

An object matching the schema: a list of issues, each with `statement`, `decision_area`,
`swot_refs`, and optionally `finding_refs`, `strategic_implication`, `missing_evidence` and
`confidence`.

# Evidence rules

1. **Every issue cites at least one SWOT item.** An issue that resolves to none is discarded.
2. **The statement is a question a person must decide**, such as which market to approach
   first, which buyer to target, whether a claimed advantage matches what buyers actually
   choose on, whether the current price structure fits this market, or what evidence is missing
   before any of that can be settled. "We are strong in sensors" is not an issue; it is a
   restatement.
3. **Prefer issues that span several SWOT items.** A strength and a threat together usually
   pose a sharper question than either alone.
4. **`decision_area`** is a short slug naming what the issue bears on — for example
   `market_priority`, `buyer_selection`, `competitive_position`, `pricing_fit`, `evidence_gap`.
5. **`missing_evidence`** lists what would have to be established before the decision could be
   made with any confidence. This is often the most useful part of the answer.
6. **Confidence** reflects the evidence behind the issue. It will be reduced to match the
   weakest supporting finding, so there is nothing to gain by overstating it.

# Strategic implication — required

Every issue must have one. An issue without a strategic implication is an observation, and a
candidate missing it is discarded whole rather than stored incomplete.

This is **decision support, never a decision**. The person reading it decides; your job is to
put the considerations in front of them. What makes it decision support is not which verbs it
avoids — it is that all four of these are present:

1. **What the current evidence suggests.** The direction the material points in.
2. **The conditions or constraints that qualify it.** What has to hold for that to matter.
3. **What is still unverified.** The gaps that stand between this and a safe decision.
4. **The next verification point.** What to check, and before what.

Not acceptable — asserts a decision and covers only the first element:

> Enter the Vietnamese market.

Acceptable — all four, and it is fine that it uses "필요하다" or "needs to be checked":

> On the current evidence the demand signal in this region looks favourable (1), though it rests
> on a single operations survey rather than on procurement records (2). Purchasing authority and
> certification requirements are both unverified (3), so they should be established before
> client discovery proceeds (4).

Saying that something *needs to be verified* is decision support, not an instruction to act.
Saying that the company *will enter a market* is not.

# Prohibited

- Do not assert that a course of action will be taken or has been decided.
- Do not omit the strategic implication. A candidate without one is discarded entirely.
- Do not invent a SWOT or finding reference.
- Do not output identifiers or timestamps.
- Do not produce numeric probabilities or scores.
