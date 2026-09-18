# -*- coding: utf-8 -*-
"""Korean and English must stay in step, and enums must never be translated away.

"Bilingual by Design" fails quietly: a missing key does not crash, it just shows a raw code
like ``EVIDENCE_NEEDED`` to somebody in one of the two languages. These tests catch that.
"""
from __future__ import annotations

import enum
import json
from pathlib import Path

import pytest

from core import models

LANGS = ("ko", "en")


def _load(repo_root: Path, lang: str) -> dict:
    with (repo_root / "locales" / f"{lang}.json").open(encoding="utf-8") as fh:
        return json.load(fh)


def _key_paths(node, prefix: str = "") -> set[str]:
    """Every key path in a nested mapping, ignoring leaf values."""
    paths: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key.startswith("_"):
                continue
            path = f"{prefix}.{key}" if prefix else key
            paths.add(path)
            paths |= _key_paths(value, path)
    return paths


def _enum_classes() -> list[type[enum.Enum]]:
    return [
        obj
        for obj in vars(models).values()
        if isinstance(obj, type) and issubclass(obj, enum.Enum) and obj is not enum.Enum
    ]


def test_locales_have_identical_key_structure(repo_root: Path) -> None:
    ko = _key_paths(_load(repo_root, "ko"))
    en = _key_paths(_load(repo_root, "en"))

    assert ko == en, (
        f"only in ko.json: {sorted(ko - en)}; only in en.json: {sorted(en - ko)}"
    )


@pytest.mark.parametrize("lang", LANGS)
def test_every_enum_member_has_a_label(repo_root: Path, lang: str) -> None:
    labels = _load(repo_root, lang)["enums"]
    missing: list[str] = []

    for cls in _enum_classes():
        section = labels.get(cls.__name__)
        if section is None:
            missing.append(f"{cls.__name__}: whole section missing")
            continue
        for member in cls:
            if member.value not in section:
                missing.append(f"{cls.__name__}.{member.value}")

    assert not missing, f"{lang}.json is missing labels for: {missing}"


@pytest.mark.parametrize("lang", LANGS)
def test_no_stale_enum_labels(repo_root: Path, lang: str) -> None:
    """A label left behind after a member was removed is a sign the two have diverged."""
    labels = _load(repo_root, lang)["enums"]
    known = {cls.__name__: {m.value for m in cls} for cls in _enum_classes()}
    stale: list[str] = []

    for section_name, section in labels.items():
        if section_name not in known:
            stale.append(f"{section_name}: no such enum in core/models.py")
            continue
        for value in section:
            if value not in known[section_name]:
                stale.append(f"{section_name}.{value}")

    assert not stale, f"{lang}.json has labels with no matching enum member: {stale}"


@pytest.mark.parametrize("lang", LANGS)
def test_enum_values_are_not_translated(repo_root: Path, lang: str) -> None:
    """The keys inside each enum section are stable codes, never localised text."""
    labels = _load(repo_root, lang)["enums"]
    for section_name, section in labels.items():
        for value in section:
            assert value == value.upper(), (
                f"{lang}.json {section_name}: key {value!r} is not a stable enum code. "
                "Keys are the code; only the values are localised."
            )


def test_privacy_notices_exist_in_both_languages(repo_root: Path) -> None:
    """Both notices are required. Ephemeral storage and outbound transmission are separate
    facts, and a person is entitled to both of them in their own language."""
    for lang in LANGS:
        messages = _load(repo_root, lang)["messages"]
        assert messages.get("ephemeral_notice")
        assert messages.get("transmission_notice")
