---
id: analysis/synthesize-claims
stage: analysis
output_schema: core.analysis.output_schemas.claim_batch_schema
requires: [organization, framework_id, our_solution, dimensions, findings, output_lang]
---

# Purpose

Answer one Master Note's worth of questions about one organization, citing the findings behind
each answer and saying plainly which questions the evidence does not settle.

# Required input

The organization's name, the framework being applied, our solution, the dimensions belonging to
this framework, and findings each prefixed with a reference key such as `[F1]` and annotated
with its evidence type and confidence.

# Expected output

An object matching the schema: one claim per dimension you can address. A dimension you cannot
address is better left out than filled in — the pipeline records it as unanswered, which is the
true state of affairs.

# Every claim needs a reference

A `statement` without an `evidence_refs` entry is discarded. Cite the reference keys of the
findings that actually support what you wrote, not every finding you were shown.

Where the evidence does not settle a dimension, leave `statement` null and put what would
settle it in `missing_evidence`. **A recorded gap is a useful result.** It tells a salesperson
what to go and find out, which is worth more than a confident sentence nobody can check.

# What you must not decide

| | |
|---|---|
| Evidence type | Derived from the dimension and the findings. Do not label anything a fact |
| Confidence | Derived. A stated confidence is a feeling, not information |
| Priority | Belongs to an earlier stage. There is no field for it |
| Our solution | Given to you. Do not extend it, improve it, or add features to it |

That last one matters. If the evidence shows a problem our stated solution does not address,
say so in `missing_evidence`. Do not quietly widen what we sell so that it fits.

# Named organizations

Some dimensions may name a company: the incumbent supplier, a competitor, a substitute, a
partner. When you name one:

- put the name in `organization_name`, **exactly as the cited passage writes it**;
- cite the passage it appears in;
- do not put any other organization's name in `statement`.

A name that is not in the cited passage is discarded along with the claim. Your own knowledge
of who operates in this market is not evidence — it is the thing this check exists to catch.

Where no organization is named in the evidence but the *kind* of partner matters, describe the
type ("a distributor holding local type approval") and name nobody.

# People

For buyer, decision maker and budget owner, describe the **role, department or function**:
"Procurement Manager", "Water Infrastructure Division", "Technical Evaluation Committee". A
named individual is almost never what makes a proposal work, and this harness is not a contact
database.

# Telling the four alternatives apart

These are four different things and collapsing them loses the analysis:

| | |
|---|---|
| Current solution | What they bought and use today |
| Current workaround | What they do because they have not bought anything |
| Competitor | Someone selling the same kind of answer we sell |
| Substitute | A different kind of answer, including doing nothing |

# Competitive advantage

The strictest dimension. Claim it only when the evidence shows **what the customer compares
on**, **who or what we are being compared with**, and **a difference between us**. A feature of
our product with no comparator named is a specification, not an advantage. When any of the
three is missing, leave the statement null and say which one.

# Value proposition

Connect their problem to what our solution does. It needs an established problem; without one
there is nothing to propose value against. Buying factors make it stronger — if they are
unknown, say so in `missing_evidence` rather than assuming what the customer cares about.

# Commercial context

Value driver, price sensitivity, budget evidence and procurement context describe the
commercial situation. **They are not pricing.** Do not produce a number, a range, a quotation,
a willingness to pay, or a budget you have not read in a document. Company size is not budget
evidence; being a public body is not a procurement constraint.

# Language

Write statements in the language given by `output_lang`, except where a proper noun or a
technical term is conventionally written otherwise.
