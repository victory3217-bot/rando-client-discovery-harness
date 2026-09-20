# -*- coding: utf-8 -*-
"""Settings for the deployment proof. Reads the environment; never prints what it reads.

The harness is imported the way a real application would import it — from outside, with the
repository root put on the path. In production that is a submodule or a vendored copy; here it
is three directories up. Either way the direction is the same: the application reaches into
the harness, and the harness never reaches back.
"""
from __future__ import annotations

import os
import secrets
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

#: The harness repository root, added to ``sys.path`` exactly once.
HARNESS_ROOT = Path(__file__).resolve().parents[4]
if str(HARNESS_ROOT) not in sys.path:
    sys.path.insert(0, str(HARNESS_ROOT))


def _default_db_path() -> Path:
    """``PROOF_DB_PATH`` when set, otherwise outside the repository.

    A proof that writes its database into a git working tree teaches the wrong habit, and the
    first person to run it would commit a file full of run rows. On a host the path points at
    the mounted disk — see ``deploy/render.yaml``.
    """
    configured = os.environ.get("PROOF_DB_PATH")
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / "phase8_proof" / "proof.sqlite3"


@dataclass(frozen=True)
class ProofSettings:
    """Configuration for one proof process.

    ``csrf_secret`` and ``session_secret`` come from the environment when it supplies them and
    are otherwise generated per process. A generated secret means sessions do not survive a
    restart, which is correct for a proof and is stated rather than hidden. Neither value is
    ever logged, rendered or returned — see ``safe_log.py``.
    """

    db_path: Path = field(default_factory=_default_db_path)
    csrf_secret: str = field(default_factory=lambda: os.environ.get("PROOF_CSRF_SECRET") or secrets.token_urlsafe(32))
    session_secret: str = field(default_factory=lambda: os.environ.get("PROOF_SESSION_SECRET") or secrets.token_urlsafe(32))
    #: ``Secure`` on cookies. False locally over http; the deployment manifests set it true.
    cookie_secure: bool = field(default_factory=lambda: os.environ.get("PROOF_COOKIE_SECURE", "0") == "1")
    #: Upload ceiling this proof accepts. Deliberately smaller than the harness's own
    #: ``IntakePolicy.max_file_bytes`` (25 MiB) so the two limits stay visibly distinct.
    max_upload_bytes: int = 8 * 1024 * 1024

    def __repr__(self) -> str:
        """Redacting. A settings object reaches log lines and tracebacks more often than
        anything else in an application."""
        return (
            f"<ProofSettings db={self.db_path.name} cookie_secure={self.cookie_secure} "
            f"max_upload_bytes={self.max_upload_bytes} secrets=<redacted x2>>"
        )
