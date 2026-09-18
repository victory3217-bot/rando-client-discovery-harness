# -*- coding: utf-8 -*-
"""LLM adapters.

``echo`` is offline and deterministic. Provider-specific adapters (anthropic, openai, google)
arrive in Phase 3; each absorbs its provider's quirks so that ``prompts/`` stays neutral.
"""
