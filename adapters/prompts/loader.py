# -*- coding: utf-8 -*-
"""Read prompt files and hand the text to the core.

``core/research`` takes prompt text as an argument. Keeping the reading here means prompts stay
out of the code (they are reviewable Markdown) without the core touching a filesystem.

Front matter is stripped: it documents the prompt's contract for a human editor and is not part
of what the model sees.
"""
from __future__ import annotations

from pathlib import Path

from core.analysis.policy import AnalysisPromptSet
from core.client.policy import ClientPromptSet
from core.research.policy import PromptSet

#: Research stage -> path relative to the prompts directory.
PROMPT_FILES = {
    "extract_findings": "research/extract-findings.md",
    "classify_swot": "diagnosis/classify-swot.md",
    "derive_key_issues": "diagnosis/derive-key-issues.md",
}

#: Client discovery stage -> path relative to the prompts directory.
CLIENT_PROMPT_FILES = {
    "build_criteria": "discovery/build-criteria.md",
    "find_organizations": "discovery/find-organizations.md",
    "assess_fit": "discovery/assess-fit.md",
}

#: Deep-analysis stage -> path relative to the prompts directory.
ANALYSIS_PROMPT_FILES = {
    "research_criteria": "analysis/research-criteria.md",
    "synthesize_claims": "analysis/synthesize-claims.md",
}


def _strip_front_matter(text: str) -> str:
    if not text.startswith("---"):
        return text.strip()
    parts = text.split("---", 2)
    return parts[2].strip() if len(parts) >= 3 else text.strip()


def load_prompt_text(path: str | Path) -> str:
    """One prompt file, front matter removed."""
    return _strip_front_matter(Path(path).read_text(encoding="utf-8"))


def load_prompt_set(prompts_dir: str | Path) -> PromptSet:
    """Every prompt the research pipeline needs.

    Reads eagerly so a missing or malformed prompt fails at startup rather than halfway through
    an analysis that has already sent evidence to a provider.
    """
    root = Path(prompts_dir)
    texts = {stage: load_prompt_text(root / rel) for stage, rel in PROMPT_FILES.items()}
    return PromptSet(**texts)


def load_client_prompt_set(prompts_dir: str | Path) -> ClientPromptSet:
    """Every prompt the client-discovery pipeline needs, read the same way."""
    root = Path(prompts_dir)
    texts = {stage: load_prompt_text(root / rel) for stage, rel in CLIENT_PROMPT_FILES.items()}
    return ClientPromptSet(**texts)


def load_analysis_prompt_set(prompts_dir: str | Path) -> AnalysisPromptSet:
    """Every prompt the deep-analysis pipeline needs, read the same way."""
    root = Path(prompts_dir)
    texts = {stage: load_prompt_text(root / rel) for stage, rel in ANALYSIS_PROMPT_FILES.items()}
    return AnalysisPromptSet(**texts)
