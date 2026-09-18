---
id: diagnosis/classify-swot
stage: diagnosis
output_schema: core.research.output_schemas.SWOT_BATCH
requires: [findings, output_lang]
---

# Purpose

Group established findings into Strengths, Weaknesses, Opportunities and Threats. This is a
compression of work already done, not a fresh act of analysis: everything you classify must
already exist as a finding.

# Required input

Findings, each prefixed with a reference key such as `[F1]` and annotated with its evidence type
and confidence.

# Expected output

An object matching the schema: a list of items, each with `category`, `statement` and
`finding_refs`.

# Evidence rules

1. **Every item cites at least one finding.** An item whose `finding_refs` resolve to nothing is
   discarded. If you want to say something that no finding supports, that is a sign the finding
   does not exist yet — not a reason to write the item.
2. **Internal or external decides the axis.** Strength and Weakness describe this company;
   Opportunity and Threat describe its environment. "Competitors are weak" is an Opportunity,
   not a Strength.
3. **Weigh the evidence type.** A grouping resting only on `ASSUMPTION` or `MISSING_EVIDENCE`
   findings is weak, and its statement should say so plainly rather than sounding settled.
4. **Several findings may support one item**, and one finding may appear in several items. Cite
   every finding that genuinely supports the item.
5. **The statement is specific.** "Good technology" tells a reader nothing. "Has delivered the
   specific capability that this buyer type repeatedly requires" tells them what was found.

# Prohibited

- Do not classify a capability as a Strength merely because the company possesses it. A
  capability becomes a strength when evidence connects it to something a buyer decides on; if
  that connection is not in the findings, say what is in them instead.
- Do not write a key issue or a strategic implication here. Those are a separate step, because
  a real issue usually spans several of these items.
- Do not invent a finding reference. Unresolvable references cause the item to be discarded.
- Do not output identifiers, framework ids or timestamps.
