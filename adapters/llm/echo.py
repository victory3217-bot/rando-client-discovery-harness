# -*- coding: utf-8 -*-
"""Echo LLM — a deterministic, offline provider.

This adapter exists in Phase 1, before any real provider, for three reasons:

1. The whole pipeline can run in CI with no API key, no cost and no network.
2. It proves the claim that swapping the LLM leaves the core workflow intact, from the first
   commit rather than as a later aspiration.
3. ``generate_structured`` synthesises a value from the requested JSON Schema, so every schema
   in ``schemas/`` is continuously checked for being satisfiable at all.

Two deliberate behaviours:

* **It never echoes the prompt back.** Prompts carry extracted document text, and a provider
  that returned it would be an easy way to leak that text into a test log or an error message.
  Output carries a short digest instead, which is stable but reveals nothing.
* **It prefers the "do not know" member of an enum** — ``UNKNOWN``, ``EVIDENCE_NEEDED``,
  ``MISSING_EVIDENCE``. Placeholder output should never be mistakable for a judgement.
"""
from __future__ import annotations

import hashlib
from typing import Any, Optional

#: Enum members that mean "unanswered", in order of preference.
_PREFERRED_ENUM_VALUES = (
    "UNKNOWN",
    "EVIDENCE_NEEDED",
    "MISSING_EVIDENCE",
    "NOT_REQUESTED",
    "NOT_STARTED",
    "PENDING",
    "CANDIDATE",
)

_PLACEHOLDER = "[echo]"


def _digest(*parts: str) -> str:
    joined = "|".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]


def _resolve(schema: dict, root: dict) -> dict:
    """Follow local ``$ref`` pointers (``#/$defs/...``) until a concrete schema is reached."""
    seen: set[str] = set()
    while isinstance(schema, dict) and "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/") or ref in seen:
            break
        seen.add(ref)
        node: Any = root
        for part in ref[2:].split("/"):
            if not isinstance(node, dict) or part not in node:
                return schema
            node = node[part]
        schema = node
    return schema


def _pick_type(schema: dict, *, required: bool) -> str:
    """Resolve a possibly-union ``type`` into one concrete type name."""
    declared = schema.get("type")
    if isinstance(declared, list):
        concrete = [t for t in declared if t != "null"]
        if not concrete:
            return "null"
        # An optional nullable field is left null; a required one gets a real value.
        return concrete[0] if required else "null"
    if declared is None:
        return "object" if "properties" in schema else "string"
    return declared


def _synthesize(
    schema: dict,
    *,
    key: str = "value",
    required: bool = True,
    root: Optional[dict] = None,
) -> Any:
    """Build the simplest value that satisfies ``schema``.

    ``root`` is the top-level schema, kept so that local ``$ref`` pointers resolve.
    """
    if root is None:
        root = schema
    schema = _resolve(schema, root)

    if "enum" in schema:
        values = [v for v in schema["enum"] if v is not None]
        for preferred in _PREFERRED_ENUM_VALUES:
            if preferred in values:
                return preferred
        if not values:
            return None
        return values[0]

    kind = _pick_type(schema, required=required)

    if kind == "null":
        return None

    if kind == "object":
        properties: dict = schema.get("properties", {})
        required_keys = set(schema.get("required", []))
        if not properties:
            return {}
        return {
            name: _synthesize(
                subschema, key=name, required=name in required_keys, root=root
            )
            for name, subschema in properties.items()
        }

    if kind == "array":
        item_schema = schema.get("items", {"type": "string"})
        count = max(int(schema.get("minItems", 0)), 0)
        return [
            _synthesize(item_schema, key=f"{key}[{i}]", required=True, root=root)
            for i in range(count)
        ]

    if kind in ("integer", "number"):
        minimum = schema.get("minimum", 0)
        return int(minimum) if kind == "integer" else float(minimum)

    if kind == "boolean":
        return False

    # string
    text = f"{_PLACEHOLDER} {key}"
    min_length = int(schema.get("minLength", 0))
    if len(text) < min_length:
        text = text + "." * (min_length - len(text))
    max_length = schema.get("maxLength")
    if isinstance(max_length, int):
        text = text[:max_length]
    return text


class EchoLLM:
    """Offline, deterministic provider. Implements ``LLMProvider``."""

    name = "echo"

    def generate(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        output_lang: str = "ko",
    ) -> str:
        return f"{_PLACEHOLDER} lang={output_lang} digest={_digest(system or '', prompt)}"

    def generate_structured(
        self,
        prompt: str,
        *,
        schema: dict,
        system: Optional[str] = None,
        output_lang: str = "ko",
    ) -> dict:
        result = _synthesize(schema, key="root", required=True)
        if not isinstance(result, dict):
            return {"value": result}
        return result

    def analyze(
        self,
        prompt: str,
        *,
        evidence: list[str],
        schema: dict,
        system: Optional[str] = None,
        output_lang: str = "ko",
    ) -> dict:
        # Evidence is not read: this provider has no knowledge and invents nothing. A real
        # adapter grounds its answer in these passages and leaves fields unanswered rather
        # than filling them from general knowledge.
        return self.generate_structured(
            prompt, schema=schema, system=system, output_lang=output_lang
        )

    def summarize(
        self,
        text: str,
        *,
        output_lang: str = "ko",
        max_sentences: int = 3,
    ) -> str:
        return (
            f"{_PLACEHOLDER} summary unavailable (offline provider) "
            f"lang={output_lang} digest={_digest(text)}"
        )
