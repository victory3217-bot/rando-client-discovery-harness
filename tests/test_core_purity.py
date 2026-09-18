# -*- coding: utf-8 -*-
"""The core must stay pure.

"Modular Core", "Database Agnostic" and "Embeddable" are only real if something checks them.
This module parses every file under ``core/`` and fails when the core reaches for the outside
world: the file system, the environment, the network, a logger, or an adapter.

If a change here fails, the answer is to move the impure part into an adapter or into the
application layer — not to widen the allowlist.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

#: Modules the core may not import. Either they perform I/O, or importing them means the core
#: has started to care about a specific implementation.
FORBIDDEN_MODULES = {
    "adapters",
    "anthropic",
    "asyncio",
    "google",
    "http",
    "httpx",
    "io",
    "logging",
    "openai",
    "os",
    "pathlib",
    "reference_app",
    "requests",
    "shutil",
    "socket",
    "sqlalchemy",
    "sqlite3",
    "subprocess",
    "tempfile",
    "urllib",
}

#: Builtins whose use in the core would mean side effects or an output channel.
FORBIDDEN_CALLS = {"open", "print", "input", "eval", "exec", "compile", "breakpoint"}


def _core_files() -> list[Path]:
    core = Path(__file__).resolve().parent.parent / "core"
    return sorted(core.rglob("*.py"))


def _top_level(module: str) -> str:
    return module.split(".", 1)[0]


@pytest.mark.parametrize("path", _core_files(), ids=lambda p: p.name)
def test_core_file_has_no_forbidden_imports(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _top_level(alias.name) in FORBIDDEN_MODULES:
                    offenders.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module and _top_level(node.module) in FORBIDDEN_MODULES:
                offenders.append(f"line {node.lineno}: from {node.module} import ...")

    assert not offenders, (
        f"{path.name} imports something the core may not depend on: {offenders}. "
        "Move it to an adapter (adapters/) or to the application layer."
    )


@pytest.mark.parametrize("path", _core_files(), ids=lambda p: p.name)
def test_core_file_has_no_side_effect_calls(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_CALLS:
                offenders.append(f"line {node.lineno}: {node.func.id}()")

    assert not offenders, (
        f"{path.name} performs a side effect the core may not perform: {offenders}. "
        "The core returns values and raises exceptions; it does not read, write or print."
    )


def test_core_never_imports_adapters() -> None:
    """Stated separately because it is the one rule that keeps the core embeddable."""
    violations: list[str] = []
    for path in _core_files():
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("adapters"):
                violations.append(f"{path.name}:{node.lineno}")
            if isinstance(node, ast.Import):
                if any(a.name.startswith("adapters") for a in node.names):
                    violations.append(f"{path.name}:{node.lineno}")

    assert not violations, (
        f"core imports adapters at {violations}. The dependency runs one way only: "
        "adapters -> core."
    )
