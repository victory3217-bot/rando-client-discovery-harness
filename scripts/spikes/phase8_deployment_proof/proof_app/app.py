# -*- coding: utf-8 -*-
"""The Litestar application. Seven routes, and each one exists to prove one claim.

| route | proves |
|---|---|
| ``GET /`` | the harness imports and assembles from outside itself |
| ``GET /session`` | a session cookie is issued and carries an opaque id and nothing else |
| ``GET /upload`` | a server-rendered form with a CSRF token, no SPA |
| ``POST /upload`` | multipart bytes reach the harness in memory; a run id returns at once |
| ``GET /runs/{id}`` | server-rendered status, readable at 375px |
| ``GET /api/runs/{id}`` | the same state as JSON, with nothing sensitive in it |
| ``POST /acknowledge`` | CSRF is enforced on a second state-changing form |

Not here: the eighteen-step UI, authentication, a production adapter, or a real provider.
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Annotated, Any, Optional

from litestar import Litestar, MediaType, Request, get, post
from litestar.config.csrf import CSRFConfig
from litestar.contrib.jinja import JinjaTemplateEngine
from litestar.datastructures import UploadFile
from litestar.enums import RequestEncodingType
from litestar.exceptions import HTTPException
from litestar.middleware.session.server_side import ServerSideSessionConfig
from litestar.params import Body
from litestar.response import Response, Template
from litestar.static_files import create_static_files_router
from litestar.stores.memory import MemoryStore
from litestar.template.config import TemplateConfig
from litestar.utils.scope.state import ScopeState

from proof_app.config import ProofSettings
from proof_app.harness_probe import UploadedPart, harness_facts, run_bootstrap
from proof_app.runs import (
    NEEDS_REUPLOAD,
    TERMINAL_STATES,
    BootstrapRunner,
    BootstrapStatus,
)
from proof_app.safe_log import log_event
from proof_app.store import ProofStore

HERE = Path(__file__).resolve().parent

#: Extensions the proof accepts, mapped to the harness's own ``FileType`` values. The browser
#: filename is used for **this lookup only** and is never stored, logged or returned.
_SUFFIX_TO_TYPE = {".md": "MD", ".txt": "TXT", ".csv": "CSV", ".html": "HTML", ".htm": "HTML"}

#: Stable codes. A user-facing error is one of these plus a sentence; never a stack trace.
ERROR_MESSAGES = {
    "UNSUPPORTED_FILE_TYPE": "지원하지 않는 형식입니다. MD · TXT · CSV · HTML만 올릴 수 있습니다.",
    "NO_FILE": "파일을 선택해 주세요.",
    "FILE_TOO_LARGE": "파일이 너무 큽니다.",
    "RUN_NOT_FOUND": "요청한 분석을 찾을 수 없습니다.",
    "RUN_FAILED": "분석을 완료하지 못했습니다.",
    "RESEARCH_FAILED": "분석을 완료하지 못했습니다. 자료를 다시 올려주세요.",
    "DISCOVERY_FAILED": "진단 결과는 남아 있습니다. 고객 발굴을 다시 하려면 자료를 다시 올려야 합니다.",
}

#: What each status says to a person. The wording is the contract from product-spec.
STATUS_COPY = {
    BootstrapStatus.NOT_STARTED: ("대기 중", "아직 시작하지 않았습니다."),
    BootstrapStatus.RUNNING_RESEARCH: ("진단 중", "자료를 읽고 있습니다."),
    BootstrapStatus.RESEARCH_COMPLETED: ("진단 완료", "고객 발굴을 시작합니다."),
    BootstrapStatus.RUNNING_DISCOVERY: ("고객 발굴 중", "후보를 찾고 있습니다."),
    BootstrapStatus.COMPLETED: ("완료", "업로드한 문서는 삭제되었습니다. 분석 결과는 남아 있습니다."),
    BootstrapStatus.RESEARCH_FAILED: ("실패", ERROR_MESSAGES["RESEARCH_FAILED"]),
    BootstrapStatus.DISCOVERY_FAILED_REUPLOAD_REQUIRED: (
        "일부 완료 · 재업로드 필요",
        ERROR_MESSAGES["DISCOVERY_FAILED"],
    ),
    BootstrapStatus.INTERRUPTED_REUPLOAD_REQUIRED: (
        "중단됨 · 재업로드 필요",
        "분석이 중단되었습니다. 자동으로 다시 시작되지 않습니다. 자료를 다시 올려주세요.",
    ),
}


def _session_id(request: Request) -> str:
    """The opaque id in the session. Created on first sight, and it is all the session holds."""
    existing = request.session.get("sid")
    if isinstance(existing, str) and existing:
        return existing
    sid = f"s_{uuid.uuid4().hex}"
    request.session["sid"] = sid
    return sid


def _file_type_for(upload: UploadFile) -> str:
    suffix = Path(upload.filename or "").suffix.lower()
    file_type = _SUFFIX_TO_TYPE.get(suffix)
    if file_type is None:
        raise HTTPException(status_code=415, detail="UNSUPPORTED_FILE_TYPE")
    return file_type


# ---------------------------------------------------------------- routes
@get("/")
async def home(request: Request) -> Template:
    sid = _session_id(request)
    request.app.state.store.ensure_session(sid)
    log_event("proof.home", route="/", session_id=sid, status=200)
    return Template("home.html", context={"facts": request.app.state.facts})


@get("/session")
async def session_probe(request: Request) -> Template:
    """Shows what the session holds: one opaque id. Nothing about a person."""
    sid = _session_id(request)
    request.app.state.store.ensure_session(sid)
    log_event("proof.session", route="/session", session_id=sid, status=200)
    return Template(
        "session.html",
        context={"session_keys": sorted(request.session.keys()), "session_id": sid},
    )


def _csrf_token(request: Request) -> str:
    """The token the CSRF middleware put on this connection.

    It lives on ``ScopeState``, not in ``scope`` directly. Reading it from the wrong place
    yields an empty string and a form that silently fails every POST — which is exactly the
    kind of security control that looks present and is not, so the tests assert on the
    rendered token rather than on the middleware being configured.
    """
    return ScopeState.from_scope(request.scope).csrf_token or ""


@get("/upload")
async def upload_form(request: Request) -> Template:
    _session_id(request)
    return Template("upload.html", context={"csrf_token": _csrf_token(request)})


@post("/upload")
async def upload(
    request: Request,
    data: Annotated[dict[str, Any], Body(media_type=RequestEncodingType.MULTI_PART)],
) -> Response:
    """Read the bytes, start a run, return the id. The bytes never reach a disk or the database."""
    started = time.perf_counter()
    sid = _session_id(request)
    store: ProofStore = request.app.state.store

    upload_file = data.get("document")
    if not isinstance(upload_file, UploadFile):
        raise HTTPException(status_code=400, detail="NO_FILE")

    file_type = _file_type_for(upload_file)
    payload = await upload_file.read()
    if len(payload) > request.app.state.settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="FILE_TOO_LARGE")

    # The filename dies here. What continues is bytes and a declared type.
    parts = [UploadedPart(data=payload, file_type=file_type)]
    fail_discovery = str(data.get("fail_discovery", "")).lower() in {"1", "true", "on"}

    run_id = store.create_run()
    request.app.state.runner.start(
        run_id, lambda report: run_bootstrap(parts, report, fail_discovery=fail_discovery)
    )

    log_event(
        "proof.upload",
        route="/upload",
        method="POST",
        session_id=sid,
        run_id=run_id,
        byte_count=len(payload),
        part_count=1,
        status=303,
        latency_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    return Response(content=None, status_code=303, headers={"Location": f"/runs/{run_id}"})


@get("/runs/{run_id:str}")
async def run_page(request: Request, run_id: str) -> Template:
    row = request.app.state.store.get_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    status = BootstrapStatus(row["status"])
    title, message = STATUS_COPY[status]
    return Template(
        "run.html",
        context={
            "run": row,
            "status": status.value,
            "title": title,
            "message": message,
            "needs_reupload": status in NEEDS_REUPLOAD,
            # Terminal, not merely "not running". RESEARCH_COMPLETED is a resting point
            # between two stages, and a poller that stops there reports a half-finished run
            # as a finished one.
            "settled": status in TERMINAL_STATES,
            "terminal_statuses": sorted(s.value for s in TERMINAL_STATES),
        },
    )


@get("/api/runs/{run_id:str}", media_type=MediaType.JSON)
async def run_json(request: Request, run_id: str) -> dict:
    """Counts and codes. No evidence, no prompt, no filename, no document text."""
    row = request.app.state.store.get_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    return {
        "run_id": row["run_id"],
        "status": row["status"],
        "updated_at": row["updated_at"],
        "error_code": row["error_code"],
        "counts": {
            "candidates": row["candidate_count"],
            "findings": row["finding_count"],
            "llm_calls": row["llm_calls"],
        },
    }


@post("/acknowledge")
async def acknowledge(
    request: Request,
    data: Annotated[dict[str, Any], Body(media_type=RequestEncodingType.URL_ENCODED)],
) -> Response:
    """A second state-changing POST, so CSRF is proven on more than the upload path.

    Stands in for the Phase 7 gap acknowledgement, and takes a ``gap_ref`` for the same reason
    the real one does: the display text is never the identifier.
    """
    sid = _session_id(request)
    gap_ref = str(data.get("gap_ref", ""))
    log_event("proof.acknowledge", route="/acknowledge", method="POST", session_id=sid, status=303)
    return Response(content=None, status_code=303, headers={"Location": f"/?ack={gap_ref[:24]}"})


def _exception_handler(request: Request, exc: Exception) -> Response:
    """Stable code plus a safe sentence. No stack trace, no locals, no request body."""
    code = "INTERNAL_ERROR"
    status = 500
    if isinstance(exc, HTTPException):
        status = exc.status_code
        detail = str(exc.detail or "")
        code = detail if detail in ERROR_MESSAGES else ("CSRF_REJECTED" if status == 403 else "REQUEST_REJECTED")
    log_event("proof.error", route=request.scope.get("path", ""), status=status, error_code=code)
    message = ERROR_MESSAGES.get(code, "요청을 처리할 수 없습니다.")
    if request.scope.get("path", "").startswith("/api/"):
        return Response({"error_code": code, "message": message}, status_code=status, media_type=MediaType.JSON)
    return Response(
        f"<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<link rel='stylesheet' href='/static/proof.css'><title>오류</title></head><body>"
        f"<main class='wrap'><h1>오류</h1><p class='muted'>{code}</p><p>{message}</p>"
        f"<a class='cta' href='/'>처음으로</a></main></body></html>",
        status_code=status,
        media_type=MediaType.HTML,
    )


def create_app(settings: Optional[ProofSettings] = None, *, sleep_between_stages: float = 0.0) -> Litestar:
    settings = settings or ProofSettings()
    store = ProofStore(settings.db_path)

    app = Litestar(
        route_handlers=[
            home,
            session_probe,
            upload_form,
            upload,
            run_page,
            run_json,
            acknowledge,
            create_static_files_router(path="/static", directories=[HERE / "static"]),
        ],
        template_config=TemplateConfig(directory=HERE / "templates", engine=JinjaTemplateEngine),
        csrf_config=CSRFConfig(
            secret=settings.csrf_secret,
            cookie_secure=settings.cookie_secure,
            cookie_httponly=False,  # the form reads it; the session cookie stays HttpOnly
            cookie_samesite="lax",
        ),
        middleware=[
            ServerSideSessionConfig(
                # Server-side, so the cookie carries an opaque id and the data stays here.
                secure=settings.cookie_secure,
                httponly=True,
                samesite="lax",
            ).middleware
        ],
        stores={"sessions": MemoryStore()},
        exception_handlers={Exception: _exception_handler},
        debug=False,  # never render a traceback to a user
    )
    app.state.settings = settings
    app.state.store = store
    app.state.runner = BootstrapRunner(store, sleep_between_stages=sleep_between_stages)
    app.state.facts = harness_facts()
    return app


# **No module-level app instance.** Building one at import time created the SQLite
# directory as a side effect of `import proof_app.app` — and the harness's own
# `tests/test_intake_canary.py::test_intake_leaves_no_file_in_the_temp_directory`
# snapshots the system temp root and fails when a new entry appears there while it runs.
# That test caught this, correctly: a proof must not disturb the environment the harness
# is tested in. Serve with uvicorn's `--factory` so importing the module does nothing.
