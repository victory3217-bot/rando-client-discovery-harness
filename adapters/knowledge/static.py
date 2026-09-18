# -*- coding: utf-8 -*-
"""Static knowledge — reads framework cards from a directory of JSON files.

The default source is ``knowledge/master-notes/``, which holds public analysis-framework cards
(MN02–MN07). The directory is passed in rather than discovered, because the core must not know
where this repository lives on disk and an embedding system may mount its own directory instead.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.errors import UnknownFrameworkError
from core.interfaces.knowledge import Framework, FrameworkDimension


def _framework_from_dict(data: dict) -> Framework:
    return Framework(
        framework_id=data["framework_id"],
        title_ko=data.get("title_ko", ""),
        title_en=data.get("title_en", ""),
        reference=data.get("reference", {}),
        dimensions=[
            FrameworkDimension(
                key=d["key"],
                label_ko=d.get("label_ko", ""),
                label_en=d.get("label_en", ""),
                question_ko=d.get("question_ko"),
                question_en=d.get("question_en"),
            )
            for d in data.get("dimensions", [])
        ],
    )


class StaticKnowledge:
    """Framework cards held in memory. Implements ``KnowledgeProvider``."""

    name = "static"

    def __init__(self, frameworks: dict[str, Framework]) -> None:
        self._frameworks = dict(frameworks)

    @classmethod
    def from_directory(cls, directory: str | Path) -> "StaticKnowledge":
        """Load every ``*.json`` card in ``directory``.

        Reads eagerly so that a malformed card fails at wiring time rather than halfway through
        an analysis.
        """
        root = Path(directory)
        frameworks: dict[str, Framework] = {}
        for path in sorted(root.glob("*.json")):
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
            framework = _framework_from_dict(data)
            frameworks[framework.framework_id] = framework
        return cls(frameworks)

    def get_framework(self, framework_id: str) -> Framework:
        try:
            return self._frameworks[framework_id]
        except KeyError:
            raise UnknownFrameworkError(
                f"framework {framework_id!r} is not available from the {self.name!r} provider "
                f"(has: {', '.join(sorted(self._frameworks)) or 'none'})"
            ) from None

    def list_frameworks(self) -> list[str]:
        return sorted(self._frameworks)
