---
id: discovery/assess-fit
stage: discovery
output_schema: core.client.output_schemas.FIT_ASSESSMENT
requires: [organization, findings, output_lang]
---

# Purpose

Judge one organization against eight criteria, citing the findings behind each judgement, and
state what of ours could be sold to which problem of theirs.

# Required input

The organization's name, and findings from the diagnosis each prefixed with a reference key
such as `[F1]` and annotated with its evidence type and confidence.

# Expected output

An object matching the schema: a `discovery_rationale` and one assessment per criterion.

# The eight criteria all point the same way

`STRONG` always means **favourable for business development**. It never means "a lot of"
whatever the criterion measures.

| Criterion | What STRONG means |
|---|---|
| Problem fit | Evidence shows this organization has the problem we address |
| Solution fit | Evidence shows our approach matches how that problem has to be solved |
| Capability fit | Evidence shows we can actually deliver this |
| Market attractiveness | The diagnosis supports an opportunity in this market |
| Purchasing potential | Evidence shows this organization buys things of this kind |
| Accessibility | A specific, evidenced route to the buyer exists |
| **Competitive situation** | **The competitive landscape favours us, or a clear differentiation is evidenced** |
| Evidence quality | The evidence behind these judgements is direct and sufficient |

**Competitive situation is the one people invert.** Strong competition is `WEAK`: an entrenched
incumbent with high switching costs is an unfavourable situation, however impressive. `STRONG`
means the field is open to us.

# Levels

- `STRONG` — favourable, with evidence cited
- `MODERATE` — some favourable evidence, with limits
- `WEAK` — clearly unfavourable, with evidence cited
- `UNKNOWN` — not enough to judge
- `EVIDENCE_NEEDED` — judging it needs a specific piece of evidence, which you name

Return **all eight**. A criterion nobody could judge says `UNKNOWN`; leaving it out makes
"we looked and could not tell" indistinguishable from "nobody looked".

# Purchasing potential and accessibility

These two are where a judgement most easily replaces evidence.

**Purchasing potential** — "they are large, so they can afford it" is not evidence. `STRONG` or
`MODERATE` requires a `signal_type` from the closed list: procurement activity, budget
evidence, a project announcement, purchase history, an RFP, an investment plan or an expansion
plan. Size, fame and sector are not signals. Without one the level is lowered.

**Accessibility** — "they are a public body so we can contact them" and "they have a website"
are not routes. `STRONG` or `MODERATE` requires an `access_route` from the closed list: a known
channel, a partner, a procurement portal, a buyer contact route, an industry event or a public
tender. Without one the level is lowered.

# Evidence rules

1. **Cite the findings behind each level.** A favourable rating with no `evidence_refs` is an
   opinion, and the pipeline lowers it to `EVIDENCE_NEEDED`.
2. **`EVIDENCE_NEEDED` must name what would settle it.** "Needs more evidence" without saying
   what evidence is a shrug.
3. **`reason` is your reading, briefly.** It is stored. Do not paste a passage into it — a
   sentence or two of interpretation, not a copy of the source.
4. **`discovery_rationale`** answers: what of ours can be sold to which problem of theirs. A
   name with eight ratings and no rationale is an industry list entry.

# Prohibited

- Do not assign a priority. The band is computed from these levels by a rule.
- Do not invent a reference key.
- Do not output identifiers, source ids, framework ids or timestamps.
- Do not use numeric scores, percentages or probabilities.
- Do not state facts about this organization that the findings do not contain.
