# -*- coding: utf-8 -*-
"""The JSON file contract with ``pricing-harness-public``.

Everything the core is not allowed to do happens here: opening files, writing them, reading a
schema off disk, running ``jsonschema``. The core assembles documents and stops
(``HARNESS.md`` section 12, ``ARCHITECTURE.md`` section 2).

**Nothing from that repository is imported.** Both repositories use a top-level package named
``core``, and importing ``core.engine...`` in this process would resolve into *this* harness
or shadow it, depending on ``sys.path`` order. What is read is its **schema file** — data, not
code — which is why the contract can be checked against the real thing without the name clash
ever arising. Reversing that decision means renaming a package first.

Two things this adapter refuses to do.

It will not write out a payload whose status is ``HANDOFF_BLOCKED``. Writing the file *is* the
hand-off, so the gate has to bite here or it is only advice.

It will not report an unchecked payload as a valid one. Without a path to the real
``client_input.schema.json`` the strict local shape check still runs, but the answer that
comes back says ``EXTERNAL_CONTRACT_NOT_CHECKED`` — "we did not look" and "we looked and it
was fine" are different facts and a deployment is entitled to tell them apart.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from core.errors import PricingHandoffBlocked
from core.models import PricingResult, PricingStatus
from core.pricing_bridge.codes import PricingFlagCode
from core.pricing_bridge.payload import validate_payload_shape

#: Where the two documents live inside the pricing harness repository.
CLIENT_INPUT_SCHEMA = Path("core/schemas/client_input.schema.json")
ANALYSIS_RESULT_SCHEMA = Path("core/schemas/analysis_result.schema.json")

#: Statuses whose payload may leave this machine. ``HANDOFF_BLOCKED`` is deliberately absent.
SENDABLE = (PricingStatus.PAYLOAD_READY, PricingStatus.COMPLETED)


@dataclass(frozen=True)
class ExternalValidation:
    """What was actually checked, and what it said.

    ``checked`` is the field that matters. A caller that only looks at ``errors`` would read
    an unchecked document as a valid one, which is the single misreading this type exists to
    prevent.
    """

    checked: bool
    errors: list[str] = field(default_factory=list)
    #: ``""`` when the real schema was applied and passed.
    code: str = ""

    @property
    def ok(self) -> bool:
        """Checked against the external contract and accepted by it."""
        return self.checked and not self.errors

    def __repr__(self) -> str:
        return f"<ExternalValidation checked={self.checked} errors={len(self.errors)} code={self.code!r}>"


class FilePricingBridge:
    """Exchanges ``client_input`` and ``analysis_result`` documents with the pricing harness.

    Not a provider. ``create_harness()`` still takes four, because a provider is something the
    core calls and the core never calls this — it is wired by whatever application layer owns
    the directory the files go in.
    """

    name = "pricing_file"

    def __init__(self, *, schema_root: Optional[str | Path] = None) -> None:
        self._schema_root = Path(schema_root) if schema_root is not None else None

    @classmethod
    def from_repository(cls, repository_path: str | Path) -> "FilePricingBridge":
        """Point the adapter at a checkout of ``pricing-harness-public``.

        The repository is optional at runtime and is not a dependency: without it the local
        contract check still runs and every answer says so.
        """
        return cls(schema_root=repository_path)

    # -- external schema ----------------------------------------------------

    @property
    def external_schema_available(self) -> bool:
        return self._schema_path(CLIENT_INPUT_SCHEMA) is not None

    def _schema_path(self, relative: Path) -> Optional[Path]:
        if self._schema_root is None:
            return None
        candidate = self._schema_root / relative
        return candidate if candidate.is_file() else None

    def _validate_against(self, relative: Path, document: dict) -> ExternalValidation:
        path = self._schema_path(relative)
        if path is None:
            return ExternalValidation(
                checked=False, code=PricingFlagCode.EXTERNAL_CONTRACT_NOT_CHECKED
            )

        from jsonschema import Draft7Validator

        with path.open(encoding="utf-8") as fh:
            schema = json.load(fh)

        validator = Draft7Validator(schema)
        errors = [
            f"{'/'.join(str(part) for part in error.path)}: {error.message}"
            for error in sorted(validator.iter_errors(document), key=lambda e: list(e.path))
        ]
        return ExternalValidation(
            checked=True, errors=errors, code="EXTERNAL_CONTRACT_INVALID" if errors else ""
        )

    def validate_external_payload(self, payload: dict) -> ExternalValidation:
        """Validate a payload against the pricing harness's own ``client_input`` schema."""
        return self._validate_against(CLIENT_INPUT_SCHEMA, payload)

    def validate_external_engine_result(self, engine_result: dict) -> ExternalValidation:
        """Validate a returned document against that harness's ``analysis_result`` schema."""
        return self._validate_against(ANALYSIS_RESULT_SCHEMA, engine_result)

    # -- files --------------------------------------------------------------

    def write_payload(self, result: PricingResult, directory: str | Path) -> Path:
        """Write one payload to ``<directory>/<pricing_case_id>.client_input.json``.

        ``directory`` is required and never defaulted. Where a document with a client's cost
        structure in it lands is an application-layer decision, and a default working
        directory is how such a file ends up somewhere nobody chose (``docs/privacy.md``).

        The file name is the opaque case id, not a client name and not a product name.
        """
        if result.status not in SENDABLE:
            raise PricingHandoffBlocked(
                f"{result.status.value}: this case may not be handed over"
            )

        local = validate_payload_shape(result.pricing_payload)
        if local:
            raise ValueError(
                f"payload fails this harness's own contract check ({len(local)} violations): "
                f"{local[0]}"
            )

        target = Path(directory) / f"{result.pricing_case_id}.client_input.json"
        with target.open("w", encoding="utf-8") as fh:
            json.dump(result.pricing_payload, fh, ensure_ascii=False, indent=2, sort_keys=False)
            fh.write("\n")
        return target

    def read_engine_result(self, path: str | Path) -> dict:
        """Read an ``analysis_result`` document produced by the pricing harness.

        Returned as-is. Interpreting it is not this adapter's job and reshaping it here would
        put a second, silent version of that contract in this repository — see
        :func:`core.pricing_bridge.attach_engine_result`, which checks that the document is
        answering the case it is being filed under.
        """
        with Path(path).open(encoding="utf-8") as fh:
            document = json.load(fh)
        if not isinstance(document, dict):
            raise ValueError("analysis_result must be a JSON object")
        return document
