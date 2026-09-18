# -*- coding: utf-8 -*-
"""Handbook knowledge — resolves each framework card's pointer into real file paths.

The detailed methodology behind MN01–MN08 lives in the ``business-planning-handbook``
repository (chapters CH01–CH08, in ``ko/`` and ``en/``). This adapter takes that repository's
path and turns each card's ``reference`` into paths that actually exist on this machine.

It does **not** copy the methodology text into this repository. Two copies drift, and only one
of them gets corrected.

This adapter also demonstrates that providers compose: it wraps another ``KnowledgeProvider``
rather than reimplementing card loading.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from core.interfaces.knowledge import Framework, KnowledgeProvider


class HandbookKnowledge:
    """Decorates a base provider with resolved handbook paths. Implements ``KnowledgeProvider``."""

    name = "handbook"

    def __init__(self, base: KnowledgeProvider, handbook_root: str | Path) -> None:
        self._base = base
        self._root = Path(handbook_root)

    def get_framework(self, framework_id: str) -> Framework:
        framework = self._base.get_framework(framework_id)
        reference = dict(framework.reference)

        declared = reference.get("handbook_paths") or []
        resolved = [str(self._root / rel) for rel in declared if (self._root / rel).is_file()]

        reference["handbook_root"] = str(self._root)
        reference["resolved_paths"] = resolved
        reference["handbook_available"] = bool(resolved)
        return replace(framework, reference=reference)

    def list_frameworks(self) -> list[str]:
        return self._base.list_frameworks()

    def is_available(self) -> bool:
        """Whether the handbook repository is actually present at the configured path.

        A missing handbook is not an error: the framework cards are self-contained and the
        analysis proceeds without the deeper methodology reference.
        """
        return self._root.is_dir()
