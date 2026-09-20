---
id: proposal/anticipate-objections
stage: proposal
output_schema: core.proposal.output_schemas.PROPOSAL_OBJECTIONS
requires: [client, established_claims, gaps, output_lang]
---

# Purpose

Work out what this customer is likely to push back on, and what we would say — keeping apart
the concerns they have actually voiced and the ones we merely expect.

# Required input

The client's name, the settled analysis claims, and the recorded gaps.

# Expected output

An object matching the schema: a list of objections, each with its basis, the claims behind it
where there are any, a response, and what the response still needs.

# The two bases are not the same thing

| | |
|---|---|
| `EVIDENCE_BACKED` | A cited claim shows this customer holds this concern. Something in a document said so |
| `ANTICIPATED` | We expect it. A reasonable preparation, and not a fact about anyone |

**Default to `ANTICIPATED`.** Most objections worth preparing for have never been said out
loud, and that is fine — what is not fine is a record that reads as though they had. An
`EVIDENCE_BACKED` objection with no citation is demoted rather than kept, so citing loosely
gains nothing.

An anticipated objection is not weaker or less useful. It is differently sourced, and the
person reading this needs to know which they are looking at before they walk into a meeting.

# A response says what we know and what we do not

Cite the claims a response rests on in `response_dimensions`. Where it rests on nothing yet,
say so in `missing_evidence` — an answer with neither citation nor admission is an assertion
wearing the clothes of a position, and it is worse than an honest blank.

Good responses tend to have the shape: what we know, what supports it, what still has to be
checked. They are not persuasion copy; nobody outside the sales team will read this wording.

# What not to produce

- Do not invent a capability in order to answer an objection. If the honest answer is that we
  do not yet do the thing, that is the answer, and it belongs in `missing_evidence`.
- Do not answer with a figure the evidence does not contain.
- Do not manufacture objections to fill the list. An empty list is a legitimate result and is
  recorded as one; a fabricated concern sends somebody to prepare for a conversation nobody
  will have.

# Language

Write in the language given by `output_lang`, except where a proper noun or a technical term
is conventionally written otherwise.
