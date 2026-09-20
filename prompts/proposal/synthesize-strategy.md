---
id: proposal/synthesize-strategy
stage: proposal
output_schema: core.proposal.output_schemas.PROPOSAL_STRATEGY
requires: [client, established_claims, solution_elements, gaps, output_lang]
---

# Purpose

Decide what to propose to one analysed client: what to aim for next, which of our things to
offer, the central claim, and the order the argument runs in.

# Required input

The client's name, country and industry; the analysis claims that were actually settled, each
tagged with its dimension, evidence type and confidence; the solution elements we can offer,
each with a reference key such as `S1`; and the gaps the analysis recorded.

If an objective has already been chosen it is given to you. Work to it.

# Expected output

An object matching the schema. Every part is optional except the storyline — a part you cannot
support is better left out, because the pipeline records it as undecided, which is the true
state of affairs.

# You are writing a strategy, not a proposal

No document, no slide, no page of prose, no price. What comes out of this stage is the set of
decisions a proposal would later be written from.

# The objective is the next thing that can happen

Not the last thing. A candidate whose buyer has never been identified cannot be sent a formal
proposal; the objective there is a conversation that would identify one.

| Objective | When it fits |
|---|---|
| `DISCOVERY_MEETING` | We know there is a problem and little else |
| `TECHNICAL_REVIEW` | The problem is clear and the question is whether our approach suits it |
| `POC` | They would need to see it work before committing |
| `PILOT` | It works; the question is whether it works in their operation |
| `SUPPLIER_REGISTRATION` | Their procurement requires it before anything else can happen |
| `PARTNERSHIP_DISCUSSION` | The route runs through someone else |
| `FORMAL_PROPOSAL` | There is somebody to send it to and something to propose |
| `PROCUREMENT_RESPONSE` | There is an actual procurement to respond to |

Leave it null when the evidence supports none of them. **Do not reach for a safe-looking
middle option** — a null objective is a clear statement that the next step is not yet
determined, and the pipeline will not substitute one.

# What we can offer is a list, not a blank page

Cite the reference keys of the elements that apply. Those elements are the whole of what we
sell.

**Do not describe a capability that is not in the list**, and do not extend one that is. No
certification we have not claimed, no support arrangement, no local service network, no
integration, no timeline. If the client's problem needs something we have not got, that belongs
in `missing_evidence`, not in the offer.

# Every statement names what it rests on

`dimensions` carries the analysis dimensions behind a sentence. A statement citing nothing is
discarded, and so is a statement citing a dimension the analysis left open.

**The key message must rest on a settled problem and on a settled value proposition or value
driver.** Without those it is a sentence about our product addressed to nobody.

## Figures

Any number in the key message or the value proposition has to appear in one of the cited
claims. Do not produce a percentage saved, a multiple improved, or a payback period that no
document states — those are the most quotable sentences in a proposal and the easiest to
invent. A claim with no figure in the evidence is still a good claim; make it without one.

# The storyline is the order of the argument

Not a table of contents. Each step says one thing and names the claims behind it.

```
CONTEXT  PROBLEM  SOLUTION  VALUE  DIFFERENTIATION  NEXT_STEP
```

Use a step only where you have something to say. `DIFFERENTIATION` belongs only where the
analysis established a competitive advantage — if it did not, leave the step out rather than
arguing for one. `NEXT_STEP` describes the objective above and must not ask for something else.

# Gaps

Say when each recorded gap has to be closed: `BEFORE_PROPOSAL`, `BEFORE_PRICING`,
`BEFORE_CONTRACT` or `OPTIONAL`. A gap you do not classify is kept at the earliest timing
rather than dropped — nothing recorded by the analysis disappears here.

# Language

Write in the language given by `output_lang`, except where a proper noun or a technical term is
conventionally written otherwise.
