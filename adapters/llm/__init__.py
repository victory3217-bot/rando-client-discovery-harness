# -*- coding: utf-8 -*-
"""LLM adapters.

``echo`` is offline and deterministic: no key, no network, no cost, and the whole pipeline
runs on it in CI. ``anthropic`` is the first production provider (Phase 8), and the only
module in this repository that can open a socket — ``tests/test_llm_anthropic.py`` fails if a
second one appears outside this package.

Each adapter absorbs its provider's quirks — system-message handling, JSON modes, retries —
so that ``prompts/`` stays neutral and ``core/`` never learns a vendor's name. Which one is
wired is an application decision, made in ``create_harness()``.
"""
