---
id: analysis/research-criteria
stage: analysis
output_schema: core.analysis.output_schemas.CLIENT_RESEARCH_CRITERIA
requires: [organization, capability, our_solution, known_gaps, findings, output_lang]
---

# Purpose

Say what still needs looking up about one organization that has already been selected for
deep analysis. Search terms, not answers.

# Required input

The organization's name, its country and industry, our capability and solution, the rationale
that made it a candidate, the gaps already recorded against it, and the findings the project
holds so far.

# Expected output

An object matching the schema: a list of queries, each optionally tagged with the dimension it
is meant to settle.

# What a good query is

A query names something a document could confirm. "Their procurement notices for measurement
equipment" is a query. "Whether they are a good fit for us" is not — no search result settles
it, and the question is the analyst's to answer from evidence.

Prefer queries that would close a recorded gap. If the candidate is missing its buyer, its
budget cycle and its access route, those are the three things worth spending searches on.

| Worth a query | Not worth a query |
|---|---|
| procurement notices, tenders, supplier announcements | whether they would like our product |
| organisational structure, named divisions | who the decision maker probably is |
| published budgets, investment plans, project announcements | how much they can afford |
| certification and regulatory requirements in their market | whether they would pass them |
| existing suppliers and installed equipment | which supplier they prefer |

# What this stage must not do

**Do not answer anything.** This stage produces queries. Whatever you already believe about
this organization from general knowledge is not usable here and writing it down as though it
were a finding is the failure this whole pipeline is built to prevent.

**Do not name other organizations.** If a competitor or a partner matters, ask for evidence
about them — "suppliers of continuous water quality monitoring in this market" — rather than
naming a company you have not read about in the supplied evidence.

**Do not ask for individuals.** Roles, departments and committees are what a proposal needs.
A named person's contact details are not this harness's business.

# Language

Write the queries in the language given by `output_lang`, except where a proper noun or a
technical term is conventionally written otherwise.
