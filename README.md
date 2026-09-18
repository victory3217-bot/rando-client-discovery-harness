# Client Discovery Harness

**한국어 문서: [README.ko.md](README.ko.md)**

A reusable, modular AI harness that turns a company's own business material, consulting output
and market research into a prioritized list of **real prospective clients** — and a proposal
strategy for the top ones.

In one sentence:

> **What do we have, who in which market should we sell it to, and what should we propose?**

This is **not** a CRM and not a business-development platform. It is a small, portable core that
other systems embed.

---

## Status

**Phase 4 of 9 — client discovery and prioritisation.**
Version `0.4.0-alpha.1`. Research, diagnosis and client discovery run; deep analysis, proposal
strategy and pricing do not. See [docs/development-guide.md](docs/development-guide.md) for the
phase plan.

Intended uses: a standalone public harness, the analysis core behind a web application, and a
mobile-first practice tool for sales training. The core stays independent of all three — see
[HARNESS.md](HARNESS.md) section 12.

| Phase | Scope | State |
|---|---|---|
| 1 | Architecture, docs, interfaces, schemas, KO/EN, ephemeral storage | **done** |
| 2 | File intake (8 formats, in memory), evidence candidates | **done** |
| 3 | Master Note diagnosis, findings, SWOT, key issues | **done** |
| 4 | Client discovery, fit assessment, deterministic priority | **done** |
| 5 | Top-3 client deep analysis | planned |
| 6–7 | Proposal strategy, pricing adapter | planned |
| 8–9 | Reference dashboard, report output | planned |

---

## Design principles

| Principle | What it means in practice |
|---|---|
| Modular Core | The core knows interfaces, never implementations |
| Database Agnostic | No SQL, ORM, connection or transaction inside the core |
| Bilingual by Design | The core returns enums and codes; the app renders the words |
| Privacy by Default | `storage_mode = EPHEMERAL`; uploaded originals are deleted after processing |
| AI Platform Agnostic | One shared rule document; per-agent files are thin pointers |
| Evidence First | No finding, SWOT item or client without a traceable source |
| Structured Data First | HTML/DOCX/PDF are outputs, never the system of record |
| Embeddable | Delete the reference app and the core still works |
| Human Decision First | No invented scores standing in for a human judgement |

The full rules live in **[HARNESS.md](HARNESS.md)** — the single source of truth for this
repository. Structure and boundaries are in **[ARCHITECTURE.md](ARCHITECTURE.md)**.

---

## Quick start

```bash
pip install -r requirements.txt
pytest
python examples/run_example.py
```

`examples/run_example.py` runs the pipeline end to end with a **fully fictional** company —
ingesting documents it generates in memory, then walking the Phase 1 structures — using the
in-memory storage adapter and the deterministic `echo` LLM adapter. No API key and no network
required, and the intake path creates no temporary file.

Assembling a harness with your own adapters:

```python
from core.harness import create_harness
from adapters.storage.memory import MemoryStorage
from adapters.knowledge.static import StaticKnowledge
from adapters.llm.echo import EchoLLM
from adapters.search.manual import ManualSearch

harness = create_harness(
    storage=MemoryStorage(),
    knowledge=StaticKnowledge.from_directory("knowledge/master-notes"),
    llm=EchoLLM(),
    search=ManualSearch(),
)
```

Swapping in your own database, knowledge framework or LLM means writing one adapter module. The
core is never modified.

---

## Repository layout

```
HARNESS.md              rules — single source of truth
ARCHITECTURE.md         structure and boundaries
CLAUDE.md AGENTS.md GEMINI.md    thin per-agent entry points

core/                   pure logic: models, evidence invariants, intake, research,
                        client discovery, interfaces
adapters/               storage · knowledge · llm · search · intake implementations
schemas/                JSON Schema (Draft 2020-12) for all 9 entities
knowledge/master-notes/ public analysis-framework cards (MN02–MN07)
prompts/                provider-neutral prompts, separated from code
locales/                ko.json · en.json
examples/               fictional sample project
tests/                  including the architecture-boundary tests
docs/                   product-spec · privacy · data-model · development-guide
```

---

## Privacy

Uploaded originals are **not** persisted by default. Raw document text is never written to logs,
caches, backups or a vector store; only `source_id`, file type, size, status and timestamps are.
Note that Zero-persistence is **not** zero-transmission: extracted text is sent to whichever LLM
provider you configure. See [docs/privacy.md](docs/privacy.md).

## Related repositories

| Repository | Relationship |
|---|---|
| `pricing-harness-public` | Pricing calculation. Connected by a JSON file contract in Phase 7; no runtime dependency |
| `business-planning-handbook` | Public expression of the MN01–MN08 analysis framework; read by path injection |

## License

MIT — see [LICENSE](LICENSE).
