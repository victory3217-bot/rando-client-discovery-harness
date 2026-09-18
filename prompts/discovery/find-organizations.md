---
id: discovery/find-organizations
stage: discovery
output_schema: core.client.output_schemas.ORGANIZATION_MENTIONS
requires: [evidence_block, criteria, output_lang]
---

# Purpose

Report the organizations that the supplied evidence **names**, and separately describe types of
organization worth looking for that it does not.

# Required input

Evidence passages, each prefixed with a reference key such as `[E1]`, and a description of what
kind of organization is being looked for.

# Expected output

An object matching the schema: `mentions` (names found in the evidence) and optionally
`hypotheses` (types of organization to look for next).

# Rules

1. **Report only names that appear in the passages.** Write each one exactly as the passage
   writes it, and cite the reference key of the passage it appears in.
2. **Your own knowledge of this industry is not evidence here.** You may well know real firms
   in this market. Unless a passage names one, it does not belong in `mentions`.
3. **Every name is checked against the passage you cite.** A name that is not there is
   discarded and the analysis is worse off for the wasted slot — so do not guess, and do not
   cite a passage you are unsure of.
4. **Do not merge names.** If one passage says "Delta Holdings" and another says "Delta
   Corporation", report both as written. Deciding they are the same organization is a claim
   about the world and needs its own evidence.
5. **Hypotheses describe a type.** "Regional public water utilities with a stated replacement
   programme" is a hypothesis. There is no field for a company name in a hypothesis, because a
   named client only ever arrives through evidence.

# Prohibited

- Do not produce a company name from general knowledge, however confident you are that it is a
  real firm operating in this market.
- Do not invent a reference key.
- Do not name a specific organization in a hypothesis.
- Do not output identifiers, source ids or timestamps.
