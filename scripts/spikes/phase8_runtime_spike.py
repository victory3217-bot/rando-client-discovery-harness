# -*- coding: utf-8 -*-
"""Phase 8 runtime spike — how long is a Bootstrap Analysis Run, and what does it cost?

    python scripts/spikes/phase8_runtime_spike.py
    python scripts/spikes/phase8_runtime_spike.py --runs 5 --latency-ms 4000

**This is a reproducible architecture benchmark, not production code.** It exists to answer
one question before a web framework or a host is chosen: *can the research-plus-discovery run
that Phase 8 calls a Bootstrap Analysis Run finish inside one HTTP request, and how big does
the request have to be allowed to get?* Its numbers are quoted in ``docs/product-spec.md``, so
it is kept runnable: when a platform limit or a policy constant changes, the same command
re-derives the table. Nothing here is imported by ``core/`` or by any adapter, and nothing
here is a dependency of the test suite.

**The default mode reaches nothing.** ``EchoLLM``, no network, no credential, deterministic.
A real provider is an explicit opt-in (``--real-provider``) and cannot be reached by omission,
by an environment variable alone, or by a default value.

What it measures honestly:

* wall-clock for intake, ``run_research`` and ``run_discovery``, over N repeats;
* the number of provider calls and the characters sent, taken from
  ``outcome.transmissions`` — the records the core already produces and already considers
  safe to log;
* peak Python allocation via ``tracemalloc``;
* how all of the above move when the uploaded volume grows.

What it cannot measure here: **real provider latency.** No provider credential is configured
in this environment and inventing one is not an option, so the LLM is ``EchoLLM`` and the
figure that matters — seconds per real call — is reported as NOT_MEASURED. ``--latency-ms``
injects an artificial delay per call so the *shape* of the total can be projected from the
measured call count; a projection is labelled as one everywhere it appears.

No document text, no prompt text and no secret is written to stdout or to any log, in either
mode. Every printed field is a count, a character total, a byte total or a duration — the same
allowlist ``TransmissionRecord`` already uses. The fictional corpus below is input, never
output.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from adapters.intake import IntakeSession  # noqa: E402
from adapters.knowledge.static import StaticKnowledge  # noqa: E402
from adapters.llm.echo import EchoLLM  # noqa: E402
from adapters.prompts import load_client_prompt_set, load_prompt_set  # noqa: E402
from adapters.search.manual import ManualSearch  # noqa: E402
from adapters.storage.memory import MemoryStorage  # noqa: E402
from core.client import persist as persist_clients  # noqa: E402
from core.client import run_discovery  # noqa: E402
from core.harness import create_harness  # noqa: E402
from core.intake import IntakePolicy  # noqa: E402
from core.models import FileType, MarketScope, SourceCategory  # noqa: E402
from core.research import persist as persist_research  # noqa: E402
from core.research import run_research  # noqa: E402

# -- fictional corpus -------------------------------------------------------
# HARNESS.md section 9: examples use invented companies and invented markets only.

_MARKET_NOTE = """# 시장 개요

메콩델타 상수도 사업자는 건기 염분 상승 구간에서 측정 주기를 늘려야 한다.

## 운영 현황

현장 인력이 수동 채수에 의존하고 있어 주기를 늘리기 어렵다.
연 2회 조달 공고가 게시되며 사전 공급자 등록을 요구한다.

## 예산

계측 유지보수 예산 항목이 공시 자료에 편성되어 있다.
"""

_OPERATIONS_CSV = """utility,region,plants,note
Fictional Aqua Delta,Delta,2,수동 채수 의존
Fictional Utility Two,Delta,1,측정 주기 확대 검토
Fictional Riverside Water,Upstream,3,원격 계측 시범 도입
"""

_PROCUREMENT_HTML = (
    "<html><head><style>.x{}</style><script>var t='not evidence';</script></head><body>"
    "<!-- internal note, not evidence -->"
    "<h2>조달 일정</h2><p>연 2회 조달 공고가 게시된다.</p>"
    "<h2>기술 요건</h2><p>다항목 측정과 원격 조회를 요구한다.</p></body></html>"
)

#: Upload volumes to compare. The multiplier repeats the market note, which is the document
#: that actually produces evidence candidates.
VOLUMES: dict[str, int] = {"small": 1, "medium": 8, "large": 32}


def _uploads(multiplier: int) -> list[tuple]:
    return [
        (
            FileType.MD,
            SourceCategory.EXTERNAL_BUSINESS_DATA,
            "메콩델타 시장 메모 (가상)",
            _MARKET_NOTE * multiplier,
        ),
        (
            FileType.CSV,
            SourceCategory.EXTERNAL_BUSINESS_DATA,
            "사업자 운영 집계 (가상)",
            _OPERATIONS_CSV,
        ),
        (FileType.HTML, SourceCategory.USER_PROVIDED, None, _PROCUREMENT_HTML),
    ]


class TimingLLM:
    """Counts and times provider calls, and can pretend to be slow.

    Structural typing only — it satisfies ``LLMProvider`` by having the four methods, which is
    the whole point of the core using ``Protocol`` (``ARCHITECTURE.md`` section 3).

    ``latency_ms`` is a **simulation knob**, not a measurement. It exists so the projected
    total for a real provider can be read off the measured call count instead of guessed.
    """

    def __init__(self, inner, latency_ms: int = 0) -> None:
        self._inner = inner
        self._latency = latency_ms / 1000.0
        self.name = getattr(inner, "name", "unknown")
        self.calls: list[tuple[str, float]] = []

    def _timed(self, method: str, fn, *args, **kwargs):
        started = time.perf_counter()
        if self._latency:
            time.sleep(self._latency)
        result = fn(*args, **kwargs)
        self.calls.append((method, time.perf_counter() - started))
        return result

    def generate(self, *a, **k):
        return self._timed("generate", self._inner.generate, *a, **k)

    def generate_structured(self, *a, **k):
        return self._timed("generate_structured", self._inner.generate_structured, *a, **k)

    def analyze(self, *a, **k):
        return self._timed("analyze", self._inner.analyze, *a, **k)

    def summarize(self, *a, **k):
        return self._timed("summarize", self._inner.summarize, *a, **k)

    @property
    def count(self) -> int:
        return len(self.calls)

    def by_method(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for method, _ in self.calls:
            out[method] = out.get(method, 0) + 1
        return out


#: Environment variable naming the adapter to use under ``--real-provider``, as
#: ``module:factory`` (e.g. ``adapters.llm.anthropic:AnthropicLLM``). Read only when the flag
#: is passed: an environment left over from another task must not silently start billing.
REAL_PROVIDER_ENV = "PHASE8_SPIKE_LLM"


def resolve_llm(real_provider: bool, latency_ms: int):
    """The provider for this run, and the label the report prints.

    Two gates, deliberately redundant. The flag has to be passed *and* the environment has to
    name an adapter. Either alone leaves the spike offline, because the failure this guards
    against is a benchmark that quietly makes paid network calls — and because a spike that
    can reach a provider by accident will eventually do it in CI.
    """
    if not real_provider:
        return TimingLLM(EchoLLM(), latency_ms=latency_ms), "EchoLLM (offline)"

    import os

    target = os.environ.get(REAL_PROVIDER_ENV, "").strip()
    if not target or ":" not in target:
        raise SystemExit(
            f"--real-provider needs {REAL_PROVIDER_ENV}=module:factory. "
            "No provider adapter is configured, and this spike does not invent one."
        )
    module_name, _, factory_name = target.partition(":")
    import importlib

    factory = getattr(importlib.import_module(module_name), factory_name)
    # The adapter reads its own credential. This spike never handles, prints or logs one.
    return TimingLLM(factory(), latency_ms=latency_ms), f"{target} (real provider)"


class CountingSearch:
    """Wraps a SearchProvider to prove how many external searches a stage makes."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.name = getattr(inner, "name", "unknown")
        self.count = 0

    def search(self, *a, **k):
        self.count += 1
        return self._inner.search(*a, **k)


def bootstrap_once(volume: str, latency_ms: int, *, real_provider: bool = False) -> dict:
    """One Bootstrap Analysis Run: intake → research → discovery, candidates discarded after."""
    llm_provider, _ = resolve_llm(real_provider, latency_ms)
    harness = create_harness(
        storage=MemoryStorage(),
        knowledge=StaticKnowledge.from_directory(REPO_ROOT / "knowledge" / "master-notes"),
        llm=llm_provider,
        search=CountingSearch(ManualSearch()),
    )
    llm, search = harness.llm, harness.search
    prompts = load_prompt_set(REPO_ROOT / "prompts")
    client_prompts = load_client_prompt_set(REPO_ROOT / "prompts")

    project = harness.create_project(
        "Fictional Sensor Works",
        market_scope=[MarketScope.INTERNATIONAL],
        target_countries=["VN"],
        target_industries=["water utilities"],
    )

    tracemalloc.start()
    timings: dict[str, float] = {}
    started_total = time.perf_counter()

    # -- intake: the only point at which document bytes exist ---------------
    started = time.perf_counter()
    candidates: list = []
    upload_bytes = 0
    with IntakeSession(project.project_id, policy=IntakePolicy()) as intake:
        for file_type, category, label, body in _uploads(VOLUMES[volume]):
            payload = bytearray(body.encode("utf-8"))
            upload_bytes += len(payload)
            result = intake.ingest(
                payload,
                file_type=file_type,
                source_category=category,
                display_label=label,
            )
            harness.storage.save_source_metadata(result.source)
            candidates.extend(result.candidates)
    timings["intake"] = time.perf_counter() - started

    sources = harness.storage.get_source_metadata(project.project_id)
    calls_after_intake = llm.count

    # -- research ------------------------------------------------------------
    started = time.perf_counter()
    research = run_research(
        project=project,
        candidates=candidates,
        sources=sources,
        knowledge=harness.knowledge,
        llm=llm,
        prompts=prompts,
        today="2026-09-20",
    )
    persist_research(research, harness.storage)
    timings["research"] = time.perf_counter() - started
    calls_after_research = llm.count

    # -- discovery: the same candidates, still in memory ---------------------
    started = time.perf_counter()
    discovery = run_discovery(
        project=project,
        candidates=candidates,
        sources=sources,
        findings=harness.storage.get_findings(project.project_id),
        key_issues=harness.storage.get_key_issues(project.project_id),
        llm=llm,
        prompts=client_prompts,
        capability="상시 수질 계측 모듈 설계·제조",
        solution="다항목 수질 측정을 단일 모듈로 처리하는 상시 계측 장비",
        market_scope=MarketScope.INTERNATIONAL,
        country="VN",
    )
    persist_clients(discovery, harness.storage)
    timings["discovery"] = time.perf_counter() - started

    # -- the candidates die here, by design ----------------------------------
    candidate_count = len(candidates)
    candidate_chars = sum(c.char_count for c in candidates)
    candidates.clear()

    timings["total"] = time.perf_counter() - started_total
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    transmissions = list(research.transmissions) + list(discovery.transmissions)
    stored = {
        "findings": len(harness.storage.get_findings(project.project_id)),
        "swot_issues": len(harness.storage.get_swot_issues(project.project_id)),
        "key_issues": len(harness.storage.get_key_issues(project.project_id)),
        "clients": len(harness.storage.get_clients(project.project_id)),
    }
    harness.storage.clear()

    return {
        "volume": volume,
        "upload_bytes": upload_bytes,
        "candidates": candidate_count,
        "candidate_chars": candidate_chars,
        "timings": timings,
        "llm_calls": {
            "intake": calls_after_intake,
            "research": calls_after_research - calls_after_intake,
            "discovery": llm.count - calls_after_research,
            "total": llm.count,
        },
        "llm_by_method": llm.by_method(),
        "search_calls": search.count,
        "sent_chars": sum(r.char_count for r in transmissions),
        "grounded_calls": sum(1 for r in transmissions if r.grounded),
        "peak_python_kb": round(peak / 1024),
        "stored": stored,
        "rejections": len(research.rejections) + len(discovery.rejections),
    }


def _stat(values: list[float]) -> dict:
    return {
        "min": round(min(values), 4),
        "median": round(statistics.median(values), 4),
        "max": round(max(values), 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument(
        "--latency-ms",
        type=int,
        default=0,
        help="Artificial delay per provider call. A simulation knob, never a measurement.",
    )
    parser.add_argument("--json", action="store_true", help="Machine-readable output.")
    parser.add_argument(
        "--real-provider",
        action="store_true",
        help=(
            f"Opt in to a real provider named by {REAL_PROVIDER_ENV}=module:factory. "
            "Off by default; makes paid network calls when on."
        ),
    )
    args = parser.parse_args()

    _, provider_label = resolve_llm(args.real_provider, 0)
    report: dict = {
        "runs": args.runs,
        "latency_ms": args.latency_ms,
        "provider": provider_label,
        "real_provider_latency": (
            "MEASURED — see the per-stage seconds below"
            if args.real_provider
            else "NOT_MEASURED — offline mode; no credential is configured and none is invented"
        ),
        "volumes": {},
    }

    for volume in VOLUMES:
        results = [
            bootstrap_once(volume, args.latency_ms, real_provider=args.real_provider)
            for _ in range(args.runs)
        ]
        first = results[0]
        report["volumes"][volume] = {
            "upload_bytes": first["upload_bytes"],
            "candidates": first["candidates"],
            "candidate_chars": first["candidate_chars"],
            "llm_calls": first["llm_calls"],
            "llm_by_method": first["llm_by_method"],
            "search_calls": first["search_calls"],
            "sent_chars": first["sent_chars"],
            "grounded_calls": first["grounded_calls"],
            "stored": first["stored"],
            "rejections": first["rejections"],
            "peak_python_kb": _stat([float(r["peak_python_kb"]) for r in results]),
            "seconds": {
                stage: _stat([r["timings"][stage] for r in results])
                for stage in ("intake", "research", "discovery", "total")
            },
            "deterministic": len({r["llm_calls"]["total"] for r in results}) == 1
            and len({r["candidates"] for r in results}) == 1,
        }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print(f"Phase 8 runtime spike — {args.runs} runs per volume")
    print(f"provider: {report['provider']}   injected latency: {args.latency_ms} ms/call")
    print(f"real provider latency: {report['real_provider_latency']}\n")

    for volume, data in report["volumes"].items():
        print(f"── {volume}  upload {data['upload_bytes']:,} B "
              f"→ {data['candidates']} candidates / {data['candidate_chars']:,} chars")
        for stage in ("intake", "research", "discovery", "total"):
            s = data["seconds"][stage]
            print(f"     {stage:<10} min {s['min']:>8.4f}s   median {s['median']:>8.4f}s   "
                  f"max {s['max']:>8.4f}s")
        calls = data["llm_calls"]
        print(f"     llm calls  research {calls['research']} + discovery {calls['discovery']} "
              f"= {calls['total']}   ({data['llm_by_method']})")
        print(f"     grounded {data['grounded_calls']}   sent {data['sent_chars']:,} chars   "
              f"search calls {data['search_calls']}")
        print(f"     peak python  median {data['peak_python_kb']['median']:,.0f} KB")
        print(f"     stored  {data['stored']}   rejections {data['rejections']}   "
              f"deterministic {data['deterministic']}")
        if args.latency_ms:
            projected = calls["total"] * args.latency_ms / 1000.0
            print(f"     projection at {args.latency_ms} ms/call: "
                  f"{projected:.1f}s of provider wait (simulated, not measured)")
        print()

    _print_populated_model(report)
    return 0


#: Policy constants the call count is a function of. Read from the code, not assumed.
def _policy_constants() -> dict:
    from core.analysis.policy import DEFAULT_ANALYSIS_POLICY
    from core.client.policy import DEFAULT_DISCOVERY_POLICY
    from core.research.policy import DEFAULT_RESEARCH_POLICY as R

    return {
        "max_candidates_per_batch": R.max_candidates_per_batch,
        "frameworks": len(R.frameworks),
        "max_findings_per_batch": R.max_findings_per_batch,
        "max_organizations": DEFAULT_DISCOVERY_POLICY.max_organizations,
        "max_queries_per_client": DEFAULT_ANALYSIS_POLICY.max_queries_per_client,
        "max_results_per_query": DEFAULT_ANALYSIS_POLICY.max_results_per_query,
    }


def _print_populated_model(report: dict) -> None:
    """What the call count becomes once a provider actually establishes findings.

    The measured numbers above are a **floor**: ``EchoLLM`` answers "not established", so the
    inference pass finds no facts to reason from, no SWOT items are classified, no key issues
    are synthesised, and discovery stops after building criteria. A provider that returns
    findings walks all of those paths.

    This block is a **model derived from the code's loop structure and its policy constants**,
    not a measurement. Each term names where it comes from so it can be checked.
    """
    c = _policy_constants()
    print("── populated-run call model (derived from code, NOT measured)")
    print(f"     policy: batch={c['max_candidates_per_batch']} candidates · "
          f"{c['frameworks']} frameworks · findings batch={c['max_findings_per_batch']} · "
          f"max organizations={c['max_organizations']}")
    print("     research   extract      B x F        core/research/extract.py:84   [measured]")
    print("     research   infer        B x F        core/research/extract.py:199  [0 here: no facts]")
    print("     research   classify     ceil(K/40)   core/research/classify.py:47  [0 here]")
    print("     research   key issues   ceil(S/40)   core/research/synthesize.py:88 [0 here]")
    print("     discovery  criteria     1            core/client/discover.py:49    [measured]")
    print("     discovery  organizations B           core/client/discover.py:113   [1 here]")
    print("     discovery  fit          min(M, 20)   core/client/fit.py:123        [0 here]")
    print("       B = batches, F = frameworks, K = findings, S = SWOT issues, M = organizations")
    print()
    for volume, data in report["volumes"].items():
        measured = data["llm_calls"]["total"]
        batches = data["llm_calls"]["research"] // max(c["frameworks"], 1)
        # Upper bound with every path walked and the organization cap reached.
        upper = (
            batches * c["frameworks"] * 2      # extract + infer
            + 2                                 # one classify + one key-issue batch
            + 1                                 # criteria
            + batches                           # organizations
            + c["max_organizations"]            # fit, capped
        )
        print(f"     {volume:<7} batches {batches:>2}   measured {measured:>3} calls   "
              f"modelled upper bound {upper:>3} calls")
    print()
    print("     Projected provider wait for the large upper bound, by per-call latency:")
    batches_large = report["volumes"]["large"]["llm_calls"]["research"] // max(c["frameworks"], 1)
    upper_large = batches_large * c["frameworks"] * 2 + 2 + 1 + batches_large + c["max_organizations"]
    for per_call in (2, 4, 8):
        print(f"       {per_call}s/call  ->  {upper_large * per_call / 60:.1f} min  "
              f"({upper_large} calls)")
    print("     (arithmetic on a modelled call count. Real latency: NOT_MEASURED)")
    print()


if __name__ == "__main__":
    raise SystemExit(main())
