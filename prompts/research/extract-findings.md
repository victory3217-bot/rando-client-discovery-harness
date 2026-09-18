---
id: research/extract-findings
stage: research
output_schema: core.research.output_schemas.FINDING_BATCH
requires: [framework, evidence_block, output_lang]
---

# Purpose

Read the supplied evidence passages through one Master Note framework and record what they
state. This is the first step of an analysis whose conclusions must remain traceable to the
documents they came from.

# Required input

- A framework: its id, title, and the question behind each dimension.
- Evidence passages, each prefixed with a reference key such as `[E1]`.

# Expected output

An object matching the schema: a list of findings, each with `finding`, `evidence_type`,
`confidence`, an optional `evidence_ref`, an optional `evidence_summary`, and an optional
`dimension` key.

# Evidence rules

1. **Answer only from the passages given.** You have no other information about this company,
   this market or these competitors. General knowledge about the industry is not evidence here.
2. **One passage, one finding.** A `FACT` cites exactly one reference key, and that key must be
   one that appears in the evidence. Do not merge two passages into a single fact; combining
   evidence happens in a later step.
3. **`FACT`** — the passage states this directly. Someone reading that passage would agree the
   finding is what it says.
4. **`ASSUMPTION`** — it is reasonable to suppose, but nothing here states it. Set
   `evidence_ref` to null and say in `evidence_summary` what it is assuming.
5. **`MISSING_EVIDENCE`** — this framework asks something the evidence does not answer. Set
   `evidence_ref` to null and use `evidence_summary` to say **what material would answer it**.
   A gap recorded without saying how to close it is of no use to anyone.
6. **A dimension with no answer is a `MISSING_EVIDENCE` finding, not silence.** Framework
   questions that the evidence cannot address are the most valuable thing this step produces:
   they become the research plan.
7. **Confidence** reflects how firmly the passage supports the finding — `HIGH`, `MEDIUM`,
   `LOW` or `UNKNOWN`. When unsure, choose lower. A later step may reduce your answer; it will
   never raise it.

# Prohibited

- Do not produce `INFERENCE`. Reasoning across findings is a separate step with its own input.
- Do not invent a reference key. A key not present in the evidence causes the finding to be
  discarded, and the analysis is worse off for the loss.
- Do not output identifiers, framework ids, dates, source names, page numbers or timestamps.
  Those are known already and will be attached to your answer; anything you write there would
  be overwritten at best and wrong at worst.
- Do not produce numeric probabilities, percentages or scores. Use the confidence values given.
- Do not restate a passage as a finding. A finding says what the passage establishes, in the
  terms the framework asks about.
