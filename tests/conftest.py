# -*- coding: utf-8 -*-
"""Shared test fixtures.

The repository is not pip-installable by design (see docs/development-guide.md), so the
repository root goes on ``sys.path`` here rather than in every test module.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def schemas() -> dict:
    """Every JSON Schema in ``schemas/``, keyed by filename stem without ``.schema``."""
    loaded = {}
    for path in sorted((REPO_ROOT / "schemas").glob("*.schema.json")):
        with path.open(encoding="utf-8") as fh:
            loaded[path.name.removesuffix(".schema.json")] = json.load(fh)
    return loaded


@pytest.fixture
def harness():
    """A fully offline harness: memory storage, static knowledge, echo llm, manual search."""
    from adapters.knowledge.static import StaticKnowledge
    from adapters.llm.echo import EchoLLM
    from adapters.search.manual import ManualSearch
    from adapters.storage.memory import MemoryStorage
    from core.harness import create_harness

    return create_harness(
        storage=MemoryStorage(),
        knowledge=StaticKnowledge.from_directory(REPO_ROOT / "knowledge" / "master-notes"),
        llm=EchoLLM(),
        search=ManualSearch(),
    )
