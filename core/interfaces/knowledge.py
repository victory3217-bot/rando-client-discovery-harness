# -*- coding: utf-8 -*-
"""Knowledge contract — how the harness reaches an analysis framework.

A framework is a set of questions to ask of the evidence. It is **not** a source of facts about
a market or a client, and nothing in this harness may treat it as one (HARNESS.md section 5).

Keeping this behind an interface is what makes the harness reusable: the public build ships
Master Note cards, an organisation can mount its own sales methodology instead, and the core
does not change either way.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable


@dataclass
class FrameworkDimension:
    """One thing the framework says to check, with the question that elicits it."""

    key: str
    label_ko: str
    label_en: str
    question_ko: Optional[str] = None
    question_en: Optional[str] = None

    def label(self, lang: str) -> str:
        """Label in ``lang``, falling back to English when a translation is absent."""
        return self.label_ko if lang == "ko" and self.label_ko else self.label_en

    def question(self, lang: str) -> Optional[str]:
        """Question in ``lang``, falling back to the other language when absent."""
        if lang == "ko":
            return self.question_ko or self.question_en
        return self.question_en or self.question_ko


@dataclass
class Framework:
    """An analysis framework, identified by a stable id such as ``"MN02"``."""

    framework_id: str
    title_ko: str
    title_en: str
    dimensions: list[FrameworkDimension] = field(default_factory=list)
    #: Free-form pointer to where the full methodology lives (chapter, URL, document id).
    #: Never the methodology text itself — this repository is public.
    reference: dict = field(default_factory=dict)

    def title(self, lang: str) -> str:
        return self.title_ko if lang == "ko" and self.title_ko else self.title_en

    def dimension_keys(self) -> list[str]:
        return [d.key for d in self.dimensions]


@runtime_checkable
class KnowledgeProvider(Protocol):
    """Access to analysis frameworks by id.

    Raises :class:`core.errors.UnknownFrameworkError` from :meth:`get_framework` when the id is
    not available, rather than returning a placeholder — an analysis silently run against an
    empty framework is worse than one that stops.
    """

    #: Short adapter identifier, safe to log (e.g. ``"static"``, ``"handbook"``).
    name: str

    def get_framework(self, framework_id: str) -> Framework: ...

    def list_frameworks(self) -> list[str]: ...
