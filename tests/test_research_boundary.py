# -*- coding: utf-8 -*-
"""One way out, and a test that keeps it that way.

Phase 3 is where document text first reaches an external provider. Every call goes through
:func:`core.research.transmission.send`, so there is one place to audit, one place that records
what went out, and one place to change if redaction is ever needed.

A convention would decay. This parses the modules and fails when one of them reaches for the
provider directly — the same approach ``test_core_purity.py`` takes to the core's other
boundaries.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

RESEARCH_DIR = Path(__file__).resolve().parent.parent / "core" / "research"

#: Methods that send something to a provider.
PROVIDER_CALLS = {"analyze", "generate_structured", "generate", "summarize"}

#: The only module allowed to make them.
GATEWAY = "transmission.py"


def _modules() -> list[Path]:
    return [p for p in sorted(RESEARCH_DIR.rglob("*.py")) if p.name != GATEWAY]


def test_the_gateway_exists_and_is_the_only_exception() -> None:
    assert (RESEARCH_DIR / GATEWAY).is_file()
    assert _modules(), "there should be other modules for this rule to apply to"


@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.name)
def test_no_module_calls_a_provider_directly(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in PROVIDER_CALLS:
                offenders.append(f"line {node.lineno}: .{node.func.attr}()")

    assert not offenders, (
        f"{path.name} calls a provider directly: {offenders}. "
        "Every external call goes through core.research.transmission.send()."
    )


def test_the_gateway_really_does_call_the_provider() -> None:
    """Otherwise the rule above would pass on a codebase that sends nothing at all."""
    tree = ast.parse((RESEARCH_DIR / GATEWAY).read_text(encoding="utf-8"), filename=GATEWAY)
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert {"analyze", "generate_structured"} <= called


def test_every_stage_records_what_it_sent() -> None:
    """A transmission that leaves no record cannot be audited afterwards."""
    from adapters.llm.echo import EchoLLM
    from core.research.models import EvidenceBlock, EvidenceEntry
    from core.research.output_schemas import FINDING_BATCH
    from core.research.transmission import send

    block = EvidenceBlock(
        entries=[EvidenceEntry(ref="E1", text="본문", candidate=object())]
    )
    _, grounded = send(
        EchoLLM(), stage="extract_findings", prompt="p", schema=FINDING_BATCH,
        evidence=block, framework_id="MN02",
    )
    assert grounded.grounded is True
    assert grounded.item_count == 1 and grounded.char_count == 2
    assert grounded.framework_id == "MN02" and grounded.provider == "echo"

    _, ungrounded = send(
        EchoLLM(), stage="classify_swot", prompt="p", schema=FINDING_BATCH, items=["[F1] x"]
    )
    assert ungrounded.grounded is False and ungrounded.item_count == 1


def test_transmission_records_carry_no_document_text() -> None:
    """The record is for logging, so every field in it has to be safe to write down."""
    from adapters.llm.echo import EchoLLM
    from core.research.models import EvidenceBlock, EvidenceEntry
    from core.research.output_schemas import FINDING_BATCH
    from core.research.transmission import send

    secret = "ZQX-RESEARCH-CANARY-4a91"
    block = EvidenceBlock(entries=[EvidenceEntry(ref="E1", text=secret, candidate=object())])
    _, record = send(
        EchoLLM(), stage="extract_findings", prompt=f"analyse {secret}",
        schema=FINDING_BATCH, evidence=block,
    )

    assert secret not in str(record)
    assert secret not in str(record.as_log_fields())
    assert secret not in repr(record)


def test_research_objects_do_not_print_their_text() -> None:
    from core.research.models import EvidenceBlock, EvidenceEntry, Rejection, ResearchOutcome

    secret = "ZQX-RESEARCH-CANARY-4a91"
    entry = EvidenceEntry(ref="E1", text=secret, candidate=object())
    block = EvidenceBlock(entries=[entry])

    assert secret not in repr(entry)
    assert secret not in repr(block)
    assert secret not in repr(Rejection("extract_findings", "bad ref", "E9"))
    assert secret not in repr(ResearchOutcome())


def test_core_research_stays_pure() -> None:
    """The Phase 1 purity rules apply here too; this states it for the new package."""
    forbidden = {"os", "pathlib", "io", "logging", "requests", "httpx", "tempfile", "adapters"}
    offenders: list[str] = []

    for path in sorted(RESEARCH_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in forbidden:
                        offenders.append(f"{path.name}:{node.lineno} {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in forbidden:
                    offenders.append(f"{path.name}:{node.lineno} {node.module}")

    assert not offenders, offenders


def test_core_research_does_not_read_prompt_files() -> None:
    """Prompt text is injected. The core cannot open ``prompts/*.md`` and must not try."""
    offenders: list[str] = []
    for path in sorted(RESEARCH_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in {"open", "print"}:
                    offenders.append(f"{path.name}:{node.lineno} {node.func.id}()")
            # .read_text() / .read_bytes() / .open() on a path object
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"read_text", "read_bytes", "open", "write_text"}:
                    offenders.append(f"{path.name}:{node.lineno} .{node.func.attr}()")
    assert not offenders, offenders


def test_prompts_reach_the_pipeline_by_injection() -> None:
    """The positive half: there is a parameter for prompt text, and it is required.

    Without this, the rule above would also pass on a pipeline that had no prompts at all.
    """
    import inspect

    from core.research.pipeline import run_research
    from core.research.policy import PromptSet

    parameter = inspect.signature(run_research).parameters.get("prompts")
    assert parameter is not None, "run_research must take prompt text as an argument"
    assert parameter.default is inspect.Parameter.empty, "prompts must be supplied, not defaulted"

    fields = {f.name for f in __import__("dataclasses").fields(PromptSet)}
    assert {"extract_findings", "classify_swot", "derive_key_issues"} <= fields
