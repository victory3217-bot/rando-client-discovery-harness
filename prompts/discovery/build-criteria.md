---
id: discovery/build-criteria
stage: discovery
output_schema: core.client.output_schemas.DISCOVERY_CRITERIA
requires: [findings, key_issues, capability, solution, output_lang]
---

# Purpose

Describe the *kind* of organization worth approaching, before anyone looks for a particular one.
Searching for companies first and justifying them afterwards is how an industry list gets
mistaken for a discovery result.

# Required input

Findings and key issues from the diagnosis, each with a reference key, plus a statement of what
this company can do and what it sells.

# Expected output

An object matching the schema. Every field is a description of what to look for, not a name.

# Rules

1. **Answer from the findings and key issues supplied.** They are the result of the diagnosis;
   anything not traceable to them is speculation about a market you have not been shown.
2. **`relevant_problem` is the customer's problem, in their terms** — not a description of the
   product. "Measurement intervals have to increase but sampling is manual" is a problem;
   "needs multi-parameter sensors" is a product description wearing a problem's clothes.
3. **`purchase_signal` and `access_signal` come from the closed lists in the schema.** They say
   what evidence would show that an organization can buy and can be reached. If the findings do
   not suggest any, leave the lists empty rather than filling them.
4. **`exclusion_condition`** says what would rule an organization out. This is as useful as the
   inclusion criteria and is usually left out.
5. **`required_evidence`** lists what would have to be found about a specific organization
   before it could be judged. This becomes the research plan for the next step.

# Prohibited

- **Do not name any organization.** Not as an example, not as an illustration. This step
  describes a type; naming companies happens only where evidence names them.
- Do not output identifiers, framework ids or timestamps. They are known already.
- Do not invent market facts. If the findings do not establish a country, industry or buyer
  type, leave that field null.
