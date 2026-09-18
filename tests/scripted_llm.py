# -*- coding: utf-8 -*-
"""A provider that returns exactly what a test tells it to.

``EchoLLM`` answers every schema with "not established", which is the right behaviour offline
but means it never exercises the paths that matter most: a well-formed FACT, an inference that
cites real findings, a SWOT item that groups them — and the malformed versions of each that the
pipeline has to reject.

This double returns prepared payloads in order, keyed by stage. It implements the same
``LLMProvider`` protocol, so nothing in the pipeline can tell the difference.
"""
from __future__ import annotations

from typing import Any, Optional


class ScriptedLLM:
    """Returns queued responses per stage, and records what it was asked."""

    name = "scripted"

    def __init__(self, responses: Optional[dict[str, list[dict]]] = None) -> None:
        #: stage name -> queue of responses. A stage with an exhausted queue returns empty.
        self.responses: dict[str, list[dict]] = {k: list(v) for k, v in (responses or {}).items()}
        #: Every prompt and evidence payload seen, so tests can assert on what was sent.
        self.calls: list[dict] = []

    # -- LLMProvider ------------------------------------------------------
    def generate(self, prompt: str, *, system: Optional[str] = None, output_lang: str = "ko") -> str:
        self.calls.append({"kind": "generate", "prompt": prompt, "lang": output_lang})
        return ""

    def generate_structured(
        self,
        prompt: str,
        *,
        schema: dict,
        system: Optional[str] = None,
        output_lang: str = "ko",
    ) -> dict:
        self.calls.append(
            {"kind": "generate_structured", "prompt": prompt, "schema": schema, "lang": output_lang}
        )
        return self._next(schema)

    def analyze(
        self,
        prompt: str,
        *,
        evidence: list[str],
        schema: dict,
        system: Optional[str] = None,
        output_lang: str = "ko",
    ) -> dict:
        self.calls.append(
            {
                "kind": "analyze",
                "prompt": prompt,
                "evidence": list(evidence),
                "schema": schema,
                "lang": output_lang,
            }
        )
        return self._next(schema)

    def summarize(self, text: str, *, output_lang: str = "ko", max_sentences: int = 3) -> str:
        self.calls.append({"kind": "summarize", "chars": len(text)})
        return ""

    # -- scripting --------------------------------------------------------
    def _next(self, schema: dict) -> dict:
        stage = self._stage_for(schema)
        queue = self.responses.get(stage)
        if queue:
            return queue.pop(0)
        return self._empty_for(stage)

    @staticmethod
    def _stage_for(schema: dict) -> str:
        """Identify the caller from the schema it asked for."""
        title = (schema or {}).get("title", "")
        return {
            "Finding extraction result": "extract",
            "Inference result": "infer",
            "SWOT classification result": "swot",
            "Key issue result": "key_issue",
        }.get(title, "unknown")

    @staticmethod
    def _empty_for(stage: str) -> dict:
        return {
            "extract": {"findings": []},
            "infer": {"inferences": []},
            "swot": {"items": []},
            "key_issue": {"issues": []},
        }.get(stage, {})

    # -- helpers for building payloads ------------------------------------
    @staticmethod
    def fact(ref: str, text: str, confidence: str = "MEDIUM", summary: str = "확인됨") -> dict:
        return {
            "evidence_ref": ref,
            "finding": text,
            "evidence_type": "FACT",
            "confidence": confidence,
            "evidence_summary": summary,
        }

    @staticmethod
    def gap(text: str, summary: str = "추가 자료 필요") -> dict:
        return {
            "evidence_ref": None,
            "finding": text,
            "evidence_type": "MISSING_EVIDENCE",
            "confidence": "UNKNOWN",
            "evidence_summary": summary,
        }

    @staticmethod
    def inference(refs: list[str], text: str, confidence: str = "MEDIUM") -> dict:
        return {"finding": text, "finding_refs": refs, "confidence": confidence}

    @staticmethod
    def swot_item(category: str, statement: str, refs: list[str]) -> dict:
        return {"category": category, "statement": statement, "finding_refs": refs}

    @staticmethod
    def key_issue(
        statement: str,
        swot_refs: list[str],
        *,
        decision_area: str = "market_priority",
        implication: Optional[str] = "현재 근거로는 A가 유리해 보이나 B가 미확인이다.",
        missing: Optional[list[str]] = None,
        confidence: str = "MEDIUM",
    ) -> dict:
        return {
            "statement": statement,
            "decision_area": decision_area,
            "swot_refs": swot_refs,
            "finding_refs": [],
            "strategic_implication": implication,
            "missing_evidence": missing or [],
            "confidence": confidence,
        }
