# -*- coding: utf-8 -*-
"""Prompt loading.

The core cannot read files, so something has to. This is that something, and it is three lines
of work rather than a PromptProvider interface — the prompts are few and they are read once
at startup.
"""
from adapters.prompts.loader import (
    load_analysis_prompt_set,
    load_client_prompt_set,
    load_prompt_set,
    load_proposal_prompt_set,
    load_prompt_text,
)

__all__ = [
    "load_analysis_prompt_set",
    "load_client_prompt_set",
    "load_prompt_set",
    "load_prompt_text",
    "load_proposal_prompt_set",
]
