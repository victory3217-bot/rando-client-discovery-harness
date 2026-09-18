# -*- coding: utf-8 -*-
"""The per-agent entry points must stay thin.

``CLAUDE.md``, ``AGENTS.md`` and ``GEMINI.md`` exist so that each coding agent finds its way
into the same shared rules. The failure mode of that pattern is well known: the three files
slowly absorb copies of the rules, then drift, and eventually three agents follow three
different versions of the same project. This test is the guard against that.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

AGENT_FILES = ("CLAUDE.md", "AGENTS.md", "GEMINI.md")
MAX_LINES = 40


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize("name", AGENT_FILES)
def test_entry_point_exists_and_is_short(repo_root: Path, name: str) -> None:
    path = repo_root / name
    assert path.is_file(), f"{name} is missing; every supported agent needs an entry point"

    length = len(_lines(path))
    assert length <= MAX_LINES, (
        f"{name} is {length} lines. An entry point points; it does not explain. "
        "Move the content into HARNESS.md."
    )


@pytest.mark.parametrize("name", AGENT_FILES)
def test_entry_point_directs_to_the_shared_rules(repo_root: Path, name: str) -> None:
    text = (repo_root / name).read_text(encoding="utf-8")
    assert "HARNESS.md" in text, f"{name} must send the reader to HARNESS.md"
    assert "ARCHITECTURE.md" in text, f"{name} must send the reader to ARCHITECTURE.md"


@pytest.mark.parametrize("name", AGENT_FILES)
def test_entry_point_does_not_copy_the_rules(repo_root: Path, name: str) -> None:
    """No substantial sentence from HARNESS.md may be reproduced in an entry point."""
    harness_text = (repo_root / "HARNESS.md").read_text(encoding="utf-8")
    entry_text = (repo_root / name).read_text(encoding="utf-8")

    # Compare on normalised whitespace so that re-wrapping does not hide a copy.
    def normalise(text: str) -> str:
        return re.sub(r"\s+", " ", text)

    harness_norm = normalise(harness_text)
    copied: list[str] = []

    for line in _lines(repo_root / name):
        candidate = normalise(line).strip("> -*#").strip()
        if len(candidate) < 60:
            continue
        if candidate in harness_norm:
            copied.append(candidate[:70])

    assert not copied, (
        f"{name} reproduces text from HARNESS.md: {copied}. "
        "Link to the rule instead of restating it."
    )


def test_shared_rules_document_is_the_one_that_holds_the_detail(repo_root: Path) -> None:
    """Sanity check on the direction of the relationship, not a style preference.

    If an entry point ever grows larger than the document it points at, the single source of
    truth has moved without anyone deciding to move it.
    """
    harness_lines = len(_lines(repo_root / "HARNESS.md"))
    for name in AGENT_FILES:
        assert harness_lines > len(_lines(repo_root / name)) * 3


def test_required_reading_list_points_at_files_that_exist(repo_root: Path) -> None:
    """A required-reading list with a dead entry sends every agent to a missing file."""
    harness_text = (repo_root / "HARNESS.md").read_text(encoding="utf-8")
    section = harness_text.split("## 0. Required Reading", 1)[1].split("\n---", 1)[0]

    referenced = set(re.findall(r"`([A-Za-z0-9_./-]+\.md)`", section))
    assert referenced, "the Required Reading section lists no files"

    missing = [name for name in sorted(referenced) if not (repo_root / name).is_file()]
    assert not missing, f"Required Reading points at files that do not exist: {missing}"
