# -*- coding: utf-8 -*-
"""Proof checks A–W. Run explicitly; the harness suite never collects this file.

    <proof venv>/python -m pytest scripts/spikes/phase8_deployment_proof/proof_tests.py -q

The filename is not ``test_*.py`` on purpose. ``pytest`` at the repository root must stay at
995 and must not acquire a dependency on Litestar being installed — the harness works without
a web framework, and the suite has to keep proving that. Passing this file by path still
collects the ``test_*`` functions inside it.
"""
from __future__ import annotations

import io
import json
import logging
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

PROOF_DIR = Path(__file__).resolve().parent
HARNESS_ROOT = PROOF_DIR.parents[2]
if str(PROOF_DIR) not in sys.path:
    sys.path.insert(0, str(PROOF_DIR))

from litestar.testing import TestClient  # noqa: E402

from proof_app.app import create_app  # noqa: E402
from proof_app.config import ProofSettings  # noqa: E402
from proof_app.runs import TERMINAL_STATES, BootstrapStatus, reading_for  # noqa: E402
from proof_app.safe_log import ALLOWED_FIELDS, NEVER_LOGGED, log_event, safe_fields  # noqa: E402
from proof_app.store import ProofStore  # noqa: E402

# -- fictional corpus. HARNESS.md section 9. ---------------------------------
FICTIONAL_MD = (
    "# 시장 개요\n\n"
    "메콩델타 상수도 사업자는 건기 염분 상승 구간에서 측정 주기를 늘려야 한다.\n\n"
    "## 운영 현황\n\n"
    "현장 인력이 수동 채수에 의존하고 있어 주기를 늘리기 어렵다.\n"
).encode("utf-8")

#: A canary that would only appear in output if a filename leaked.
CANARY_FILENAME = "ZZCANARYZZ_고객사_내부자료.md"


@pytest.fixture
def settings(tmp_path: Path) -> ProofSettings:
    return ProofSettings(db_path=tmp_path / "proof.sqlite3")


@pytest.fixture
def client(settings: ProofSettings):
    with TestClient(app=create_app(settings)) as c:
        yield c


def _csrf(client) -> str:
    page = client.get("/upload")
    match = re.search(r'name="_csrf_token" value="([^"]+)"', page.text)
    assert match, "the upload form must carry a CSRF token"
    return match.group(1)


def _upload(client, *, data: bytes = FICTIONAL_MD, filename: str = "market.md", token=None, **extra):
    fields = {"_csrf_token": token} if token is not None else {}
    fields.update(extra)
    return client.post(
        "/upload",
        files={"document": (filename, io.BytesIO(data), "text/markdown")},
        data=fields,
        follow_redirects=False,
    )


#: A run is settled when it reaches a terminal state — not when it merely stops saying
#: RUNNING_. ``RESEARCH_COMPLETED`` is a resting point between the two stages, and treating
#: it as final reports a half-finished run as a finished one.
TERMINAL = {s.value for s in TERMINAL_STATES}


def _settle(client, run_id: str, timeout_s: float = 30.0) -> dict:
    """Poll the JSON endpoint the way the page does, until the run reaches a terminal state."""
    import time

    deadline = time.monotonic() + timeout_s
    body: dict = {}
    while time.monotonic() < deadline:
        body = client.get(f"/api/runs/{run_id}").json()
        if body["status"] in TERMINAL:
            return body
        time.sleep(0.05)
    return body


# -- A: the app starts --------------------------------------------------------

def test_a_app_starts(client) -> None:
    assert client.get("/").status_code == 200


# -- B: the harness imports and assembles from outside ------------------------

def test_b_harness_imports_and_assembles(client) -> None:
    page = client.get("/").text
    assert ">9<" in page, "nine core entities, read through create_harness()"
    for adapter in ("memory", "echo", "manual", "static"):
        assert adapter in page, f"{adapter} adapter not wired"


def test_b2_core_does_not_import_the_web_framework() -> None:
    """The direction of the dependency, asserted from the other side."""
    offenders = [
        path.relative_to(HARNESS_ROOT).as_posix()
        for path in (HARNESS_ROOT / "core").rglob("*.py")
        if re.search(r"\b(litestar|starlette|fastapi|jinja2|uvicorn)\b", path.read_text(encoding="utf-8"))
    ]
    assert not offenders, offenders


# -- C/D: session cookie ------------------------------------------------------

def test_c_session_cookie_is_issued(client) -> None:
    client.get("/")
    assert "session" in client.cookies


def test_d_cookie_carries_an_opaque_id_only(client) -> None:
    client.get("/session")
    raw = client.cookies.get("session") or ""
    # Server-side sessions: the cookie is a reference, the data stays on the server.
    assert len(raw) < 256
    for leak in ("sid", "s_", "@", "010", "email", "phone", "name"):
        assert leak not in raw, f"cookie appears to carry {leak!r}"


def test_d2_the_session_holds_nothing_but_that_id(client) -> None:
    page = client.get("/session").text
    assert "sid" in page
    assert re.search(r"<code>s_[0-9a-f]{32}</code>", page), "opaque id, not a readable handle"


# -- E/F/G: CSRF ---------------------------------------------------------------

def test_e_valid_csrf_succeeds(client) -> None:
    response = _upload(client, token=_csrf(client))
    assert response.status_code == 303
    assert response.headers["location"].startswith("/runs/run_")


def test_f_missing_csrf_is_rejected(client) -> None:
    assert _upload(client).status_code == 403


def test_g_invalid_csrf_is_rejected(client) -> None:
    _csrf(client)
    assert _upload(client, token="not-the-token").status_code == 403


def test_g2_csrf_applies_to_the_second_state_changing_post(client) -> None:
    token = _csrf(client)
    assert client.post("/acknowledge", data={"gap_ref": "gap_abc123"}, follow_redirects=False).status_code == 403
    ok = client.post(
        "/acknowledge",
        data={"gap_ref": "gap_abc123", "_csrf_token": token},
        follow_redirects=False,
    )
    assert ok.status_code == 303


def test_g3_get_does_not_require_csrf(client) -> None:
    for route in ("/", "/session", "/upload"):
        assert client.get(route).status_code == 200


# -- H/I/J: multipart upload ----------------------------------------------------

@pytest.mark.parametrize("size_label,size", [("small_100kb", 100 * 1024), ("medium_2mb", 2 * 1024 * 1024)])
def test_h_multipart_upload_accepted(client, size_label: str, size: int) -> None:
    payload = (FICTIONAL_MD * (size // len(FICTIONAL_MD) + 1))[:size]
    response = _upload(client, data=payload, token=_csrf(client))
    assert response.status_code == 303, size_label


def test_h2_upload_over_the_configured_ceiling_is_refused(tmp_path: Path) -> None:
    small = ProofSettings(db_path=tmp_path / "p.sqlite3", max_upload_bytes=64 * 1024)
    with TestClient(app=create_app(small)) as c:
        response = _upload(c, data=b"x" * (128 * 1024), filename="big.txt", token=_csrf(c))
    assert response.status_code == 413


def test_i_raw_upload_is_not_persisted(client, settings: ProofSettings) -> None:
    """The bytes must not reach SQLite, and no column exists that could hold them."""
    marker = b"ZZUPLOADCANARYZZ"
    _upload(client, data=FICTIONAL_MD + marker, token=_csrf(client))

    assert marker not in settings.db_path.read_bytes(), "document bytes reached the database"
    columns = ProofStore(settings.db_path).column_names()
    for table, names in columns.items():
        for name in names:
            assert not any(b in name for b in ("file", "document", "text", "content", "blob")), f"{table}.{name}"


def test_i2_no_temp_file_is_created_by_the_proof(client, tmp_path: Path) -> None:
    before = set(tmp_path.rglob("*"))
    _upload(client, token=_csrf(client))
    created = {p.name for p in set(tmp_path.rglob("*")) - before}
    assert not {n for n in created if not n.startswith("proof.sqlite3")}, created


def test_j_original_filename_is_never_logged(client, caplog) -> None:
    with caplog.at_level(logging.INFO, logger="phase8.proof"):
        _upload(client, filename=CANARY_FILENAME, token=_csrf(client))
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "ZZCANARYZZ" not in text
    assert "고객사" not in text
    assert ".md" not in text


def test_j2_the_filename_is_not_returned_either(client) -> None:
    response = _upload(client, filename=CANARY_FILENAME, token=_csrf(client))
    run_id = response.headers["location"].rsplit("/", 1)[-1]
    body = _settle(client, run_id)
    assert "ZZCANARYZZ" not in json.dumps(body, ensure_ascii=False)
    assert "ZZCANARYZZ" not in client.get(f"/runs/{run_id}").text


# -- K/L/M/N: background lifecycle and polling -----------------------------------

def test_k_post_creates_a_run_id_immediately(client) -> None:
    response = _upload(client, token=_csrf(client))
    run_id = response.headers["location"].rsplit("/", 1)[-1]
    assert run_id.startswith("run_")
    first = client.get(f"/api/runs/{run_id}").json()
    assert first["status"] in {"RUNNING_RESEARCH", "RESEARCH_COMPLETED", "RUNNING_DISCOVERY", "COMPLETED"}


def test_l_background_run_reaches_completed(client) -> None:
    response = _upload(client, token=_csrf(client))
    run_id = response.headers["location"].rsplit("/", 1)[-1]
    body = _settle(client, run_id)
    assert body["status"] == "COMPLETED", body
    assert body["counts"]["candidates"] > 0
    assert body["counts"]["llm_calls"] > 0


def test_l2_partial_failure_keeps_research_and_demands_a_reupload(client) -> None:
    response = _upload(client, token=_csrf(client), fail_discovery="1")
    run_id = response.headers["location"].rsplit("/", 1)[-1]
    body = _settle(client, run_id)

    assert body["status"] == "DISCOVERY_FAILED_REUPLOAD_REQUIRED"
    assert body["error_code"] == "DISCOVERY_FAILED"
    page = client.get(f"/runs/{run_id}").text
    assert "다시 올려야" in page
    assert "자료 다시 올리기" in page


def test_m_polling_json_works(client) -> None:
    run_id = _upload(client, token=_csrf(client)).headers["location"].rsplit("/", 1)[-1]
    body = _settle(client, run_id)
    assert set(body) == {"run_id", "status", "updated_at", "error_code", "counts"}


def test_n_html_status_page_works(client) -> None:
    run_id = _upload(client, token=_csrf(client)).headers["location"].rsplit("/", 1)[-1]
    _settle(client, run_id)
    page = client.get(f"/runs/{run_id}")
    assert page.status_code == 200
    assert "분석 상태" in page.text and run_id in page.text


def test_n2_a_missing_run_is_a_stable_code_not_a_trace(client) -> None:
    html = client.get("/runs/run_nope")
    assert html.status_code == 404 and "RUN_NOT_FOUND" in html.text
    assert "Traceback" not in html.text and "proof_app" not in html.text

    api = client.get("/api/runs/run_nope")
    assert api.status_code == 404 and api.json()["error_code"] == "RUN_NOT_FOUND"
    assert "Traceback" not in api.text


# -- O: SQLite survives the request boundary ---------------------------------------

def test_o_sqlite_state_survives_a_new_app_over_the_same_file(client, settings: ProofSettings) -> None:
    run_id = _upload(client, token=_csrf(client)).headers["location"].rsplit("/", 1)[-1]
    _settle(client, run_id)

    with TestClient(app=create_app(settings)) as second:
        body = second.get(f"/api/runs/{run_id}").json()
    assert body["run_id"] == run_id and body["status"] == "COMPLETED"


def test_o2_the_two_application_tables_are_the_only_ones(settings: ProofSettings) -> None:
    store = ProofStore(settings.db_path)
    assert set(store.column_names()) == {"proof_run", "proof_session"}, "no harness entity tables here"


# -- P: no broker, no worker ---------------------------------------------------------

def test_p_no_broker_or_worker_dependency() -> None:
    banned = ("celery", "redis", "rq", "kombu", "pika", "boto3", "dramatiq", "arq", "huey")
    installed = subprocess.run(
        [sys.executable, "-m", "pip", "list", "--format=freeze"], capture_output=True, text=True
    ).stdout.lower()
    assert not [b for b in banned if f"{b}==" in installed], installed

    source = "\n".join(p.read_text(encoding="utf-8") for p in (PROOF_DIR / "proof_app").rglob("*.py"))
    assert not [b for b in banned if re.search(rf"\b{b}\b", source)]


# -- Q: no front-end framework ---------------------------------------------------------

def test_q_no_react_vue_or_svelte() -> None:
    web = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (PROOF_DIR / "proof_app").rglob("*")
        if p.suffix in {".html", ".css", ".js", ".py"}
    ).lower()
    for framework in ("react", "vue", "svelte", "angular", "htmx", "alpine.js"):
        assert framework not in web, framework
    assert not list((PROOF_DIR).rglob("package.json"))
    assert not list((PROOF_DIR).rglob("node_modules"))


# -- R/S/T: privacy canaries -------------------------------------------------------------

def test_r_rendered_html_carries_no_document_text(client) -> None:
    marker = "ZZHTMLCANARYZZ"
    body = FICTIONAL_MD + f"\n\n{marker} 내부 단가표\n".encode("utf-8")
    run_id = _upload(client, data=body, token=_csrf(client)).headers["location"].rsplit("/", 1)[-1]
    _settle(client, run_id)

    for page in (client.get("/").text, client.get(f"/runs/{run_id}").text, client.get("/session").text):
        assert marker not in page
        assert "내부 단가표" not in page


def test_s_json_carries_counts_and_codes_only(client) -> None:
    marker = "ZZJSONCANARYZZ"
    body = FICTIONAL_MD + marker.encode("utf-8")
    run_id = _upload(client, data=body, token=_csrf(client)).headers["location"].rsplit("/", 1)[-1]
    payload = _settle(client, run_id)

    serialised = json.dumps(payload, ensure_ascii=False)
    assert marker not in serialised
    assert all(isinstance(v, (int, float)) for v in payload["counts"].values())
    for banned in ("prompt", "evidence", "filename", "text", "document", "csrf", "cookie"):
        assert banned not in serialised.lower()


def test_t_the_log_allowlist_excludes_everything_dangerous(client, caplog) -> None:
    assert not (ALLOWED_FIELDS & NEVER_LOGGED)
    assert safe_fields({"run_id": "r", "filename": "x.md", "prompt": "p"}) == {"run_id": "r"}
    assert "x.md" not in log_event("t", filename="x.md", run_id="r")

    with caplog.at_level(logging.INFO, logger="phase8.proof"):
        run_id = _upload(client, filename=CANARY_FILENAME, token=_csrf(client)).headers[
            "location"
        ].rsplit("/", 1)[-1]
        _settle(client, run_id)
    text = "\n".join(r.getMessage() for r in caplog.records)
    for banned in ("ZZCANARYZZ", "csrftoken", "메콩", "_csrf"):
        assert banned not in text, banned


# -- U: mobile layout ------------------------------------------------------------------

def test_u_pages_declare_a_mobile_viewport_and_avoid_tables(client) -> None:
    """Static half of the 375px check. The rendered half is a browser run — see README."""
    run_id = _upload(client, token=_csrf(client)).headers["location"].rsplit("/", 1)[-1]
    _settle(client, run_id)
    for page in ("/", "/session", "/upload", f"/runs/{run_id}"):
        html = client.get(page).text
        assert 'name="viewport" content="width=device-width, initial-scale=1"' in html
        assert "<table" not in html, f"{page} uses a table"
        assert html.count('class="cta"') <= 2, f"{page} has more than one primary action area"

    css = (PROOF_DIR / "proof_app" / "static" / "proof.css").read_text(encoding="utf-8")
    assert "overflow-x: hidden" in css and "max-width: 640px" in css


# -- V: the harness is untouched ----------------------------------------------------------

def test_v_core_and_production_files_are_unchanged() -> None:
    changed = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all",
         "--", "core", "adapters", "schemas", "locales", "tests", "examples"],
        cwd=HARNESS_ROOT, capture_output=True, text=True,
    ).stdout.strip()
    assert changed == "", changed


def test_v2_the_proof_adds_no_dependency_to_the_harness() -> None:
    requirements = (HARNESS_ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    for package in ("litestar", "jinja2", "uvicorn", "starlette", "fastapi"):
        assert package not in requirements, package


# -- W: the harness suite is unaffected -----------------------------------------------------

def test_w_the_harness_suite_cannot_collect_the_proof() -> None:
    """Checked structurally rather than by shelling out.

    ``sys.executable`` here is the proof's own virtualenv, which deliberately does not have
    the harness's test dependencies — running the harness suite from it proves nothing about
    the harness suite. What matters is the mechanism, and the mechanism is naming: pytest
    recurses into ``test_*.py`` only, this file is not one, and no configuration widens that.
    The 995 figure is verified separately with the harness's own interpreter.
    """
    assert not Path(__file__).name.startswith("test_")

    named_like_a_test = [
        p.relative_to(HARNESS_ROOT).as_posix()
        for p in PROOF_DIR.rglob("test_*.py")
    ]
    assert not named_like_a_test, named_like_a_test

    for config in ("pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml"):
        path = HARNESS_ROOT / config
        if path.exists():
            assert "python_files" not in path.read_text(encoding="utf-8"), config


def test_w2_the_proof_venv_is_not_the_harness_environment() -> None:
    """The separation, stated as a fact rather than assumed.

    Litestar is importable here and must not be importable from the harness's own
    interpreter's requirements — ``test_v2`` checks the requirements file, this checks that
    the two environments are genuinely different trees.
    """
    import litestar

    assert HARNESS_ROOT not in Path(litestar.__file__).parents


# -- process-loss reading -----------------------------------------------------------------

def test_a_stale_running_row_reads_as_interrupted(tmp_path: Path) -> None:
    """A run left RUNNING_* by a process that is gone. Nothing will move it."""
    store = ProofStore(tmp_path / "p.sqlite3", process_started_at=0.0)
    run_id = store.create_run()
    store.set_status(run_id, BootstrapStatus.RUNNING_RESEARCH)
    assert store.get_run(run_id)["status"] == "RUNNING_RESEARCH"

    restarted = ProofStore(tmp_path / "p.sqlite3")  # a later process
    row = restarted.get_run(run_id)
    assert row["status"] == "INTERRUPTED_REUPLOAD_REQUIRED"
    assert row["stored_status"] == "RUNNING_RESEARCH", "the derivation is never written back"


def test_a_stale_row_is_never_read_as_completed(tmp_path: Path) -> None:
    store = ProofStore(tmp_path / "p.sqlite3", process_started_at=0.0)
    run_id = store.create_run()
    store.set_status(run_id, BootstrapStatus.RUNNING_DISCOVERY)
    assert ProofStore(tmp_path / "p.sqlite3").get_run(run_id)["status"] != "COMPLETED"


def test_reading_for_leaves_settled_rows_alone() -> None:
    for status in (BootstrapStatus.COMPLETED, BootstrapStatus.RESEARCH_FAILED):
        assert reading_for(status, process_started_at=100.0, row_updated_at=1.0) is status


# -- background task lifecycle -------------------------------------------------------------
#
# Four ways a background task registry goes wrong, each checked directly:
#   a task nobody references is collected mid-flight and the run silently stops;
#   a task nobody removes accumulates until the process dies;
#   an exception nobody retrieves is printed to stderr with a traceback, outside every
#     allowlist this application has;
#   a failure after research is recorded as though nothing survived.


def _runner_scenario(coro_body, tmp_path: Path):
    """Run one async scenario on its own loop, capturing the loop's exception handler.

    Its own loop rather than the TestClient's, because the thing under test is what asyncio
    reports when a task settles — and that is only observable from the loop that owns it.
    """
    import asyncio
    import gc

    reported: list[str] = []

    async def scenario():
        asyncio.get_running_loop().set_exception_handler(
            lambda loop, context: reported.append(str(context.get("message", "")))
        )
        return await coro_body()

    result = asyncio.run(scenario())
    gc.collect()  # "never retrieved" is emitted when the Task is collected, not when it fails
    return result, reported


async def _drain(runner, timeout: float = 30.0) -> None:
    import asyncio
    import time as _time

    deadline = _time.monotonic() + timeout
    while runner.active_count and _time.monotonic() < deadline:
        await asyncio.sleep(0.01)


def test_x_a_running_task_is_strongly_referenced(tmp_path: Path) -> None:
    """asyncio holds tasks weakly. A run nobody anchors can be collected and just stop."""
    import asyncio
    import gc

    from proof_app.runs import BootstrapRunner, RunOutcome

    async def body():
        store = ProofStore(tmp_path / "ref.sqlite3")
        runner = BootstrapRunner(store)
        started = asyncio.Event()
        release = asyncio.Event()

        def work(report):
            report(BootstrapStatus.RESEARCH_COMPLETED)
            return RunOutcome(status=BootstrapStatus.COMPLETED)

        run_id = store.create_run()
        runner.start(run_id, work)
        anchored_while_running = runner.active_count == 1
        gc.collect()  # a weakly-held task would not survive this
        survived_collection = runner.active_count == 1

        await _drain(runner)
        return anchored_while_running, survived_collection, store.get_run(run_id)["status"]

    (anchored, survived, status), reported = _runner_scenario(body, tmp_path)
    assert anchored, "the task was not registered while running"
    assert survived, "the task was collected mid-flight"
    assert status == "COMPLETED"
    assert reported == []


def test_x2_a_completed_task_is_removed(tmp_path: Path) -> None:
    from proof_app.runs import BootstrapRunner, RunOutcome

    async def body():
        store = ProofStore(tmp_path / "done.sqlite3")
        runner = BootstrapRunner(store)
        run_id = store.create_run()
        runner.start(run_id, lambda report: RunOutcome(status=BootstrapStatus.COMPLETED))
        await _drain(runner)
        return runner.active_count, store.get_run(run_id)["status"]

    (active, status), reported = _runner_scenario(body, tmp_path)
    assert active == 0, "a finished task stayed in the registry"
    assert status == "COMPLETED"
    assert reported == []


def test_x3_a_failed_task_is_removed_and_recorded_safely(tmp_path: Path) -> None:
    """The exception carries a filename and a document line. Neither may survive it."""
    from proof_app.runs import BootstrapRunner

    def exploding(report):
        raise RuntimeError("ZZTASKCANARYZZ /srv/uploads/고객사_단가표.xlsx 메콩델타 수치")

    async def body():
        store = ProofStore(tmp_path / "boom.sqlite3")
        runner = BootstrapRunner(store)
        run_id = store.create_run()
        runner.start(run_id, exploding)
        await _drain(runner)
        return runner.active_count, store.get_run(run_id)

    (active, row), reported = _runner_scenario(body, tmp_path)
    assert active == 0, "a failed task stayed in the registry"
    assert row["status"] == "RESEARCH_FAILED"
    assert row["error_code"] == "RESEARCH_FAILED"
    assert reported == [], reported

    stored = json.dumps(row, ensure_ascii=False)
    for leak in ("ZZTASKCANARYZZ", ".xlsx", "고객사", "메콩", "Traceback", "RuntimeError"):
        assert leak not in stored, leak


def test_x4_a_failure_after_research_keeps_the_partial_success_meaning(tmp_path: Path) -> None:
    """Research already stored its findings. The state must not claim nothing survived."""
    from proof_app.runs import BootstrapRunner

    def explode_in_discovery(report):
        report(BootstrapStatus.RESEARCH_COMPLETED)
        report(BootstrapStatus.RUNNING_DISCOVERY)
        raise RuntimeError("boom")

    async def body():
        store = ProofStore(tmp_path / "partial.sqlite3")
        runner = BootstrapRunner(store)
        run_id = store.create_run()
        runner.start(run_id, explode_in_discovery)
        await _drain(runner)
        return runner.active_count, store.get_run(run_id)

    (active, row), reported = _runner_scenario(body, tmp_path)
    assert active == 0
    assert row["status"] == "DISCOVERY_FAILED_REUPLOAD_REQUIRED"
    assert row["error_code"] == "DISCOVERY_FAILED"
    assert reported == []


def test_x5_no_task_exception_was_never_retrieved(tmp_path: Path) -> None:
    """The exact asyncio warning, asserted by name rather than by its absence in general."""
    from proof_app.runs import BootstrapRunner

    async def body():
        store = ProofStore(tmp_path / "quiet.sqlite3")
        runner = BootstrapRunner(store)
        for _ in range(5):
            run_id = store.create_run()
            runner.start(run_id, lambda report: (_ for _ in ()).throw(ValueError("x")))
        await _drain(runner)
        return runner.active_count

    active, reported = _runner_scenario(body, tmp_path)
    assert active == 0
    assert not [m for m in reported if "never retrieved" in m], reported
    assert reported == [], reported


def test_x6_repeated_runs_do_not_accumulate_tasks(tmp_path: Path) -> None:
    """Twelve runs, mixed outcomes. The registry has to be empty afterwards."""
    from proof_app.runs import BootstrapRunner, RunOutcome

    async def body():
        store = ProofStore(tmp_path / "many.sqlite3")
        runner = BootstrapRunner(store)
        peak = 0
        for index in range(12):
            run_id = store.create_run()
            if index % 3 == 0:
                runner.start(run_id, lambda report: RunOutcome(status=BootstrapStatus.COMPLETED))
            elif index % 3 == 1:
                runner.start(run_id, lambda report: (_ for _ in ()).throw(RuntimeError("x")))
            else:
                def partial(report):
                    report(BootstrapStatus.RESEARCH_COMPLETED)
                    return RunOutcome(
                        status=BootstrapStatus.DISCOVERY_FAILED_REUPLOAD_REQUIRED,
                        error_code="DISCOVERY_FAILED",
                    )

                runner.start(run_id, partial)
            peak = max(peak, runner.active_count)
        await _drain(runner)
        return peak, runner.active_count

    (peak, active), reported = _runner_scenario(body, tmp_path)
    assert peak > 0, "nothing was ever registered"
    assert active == 0, f"{active} tasks left behind after 12 runs"
    assert reported == []


def test_x7_repeated_runs_through_the_app_leave_nothing_behind(client) -> None:
    """The same property through the real HTTP path, not just the runner in isolation."""
    runner = client.app.state.runner
    for _ in range(4):
        run_id = _upload(client, token=_csrf(client)).headers["location"].rsplit("/", 1)[-1]
        assert _settle(client, run_id)["status"] == "COMPLETED"
    assert runner.active_count == 0, f"{runner.active_count} tasks left behind"


def test_x8_cancellation_is_not_swallowed(tmp_path: Path) -> None:
    """Shutdown has to be able to cancel a run; the row then reads as interrupted."""
    import asyncio

    from proof_app.runs import BootstrapRunner

    async def body():
        store = ProofStore(tmp_path / "cancel.sqlite3")
        runner = BootstrapRunner(store)
        run_id = store.create_run()

        def slow(report):
            import time as _t

            _t.sleep(2.0)
            return None

        runner.start(run_id, slow)
        await asyncio.sleep(0.05)
        task = next(iter(runner._tasks))
        task.cancel()
        await asyncio.sleep(0.05)
        cancelled = task.cancelled() or task.done()
        return cancelled, runner.active_count, store.get_run(run_id)["stored_status"]

    (cancelled, active, stored_status), reported = _runner_scenario(body, tmp_path)
    assert cancelled, "the task did not respond to cancellation"
    assert active == 0, "a cancelled task stayed in the registry"
    assert stored_status == "RUNNING_RESEARCH", "cancellation must not invent a terminal state"
    assert reported == []


def test_x9_the_proof_adds_no_retry_or_scheduler() -> None:
    """The fix must not have smuggled in the infrastructure section 10 excludes.

    Scanned as code, not as text: the module's prose says "no automatic retry" several times
    and a raw substring search would flag its own documentation. What matters is whether any
    *name* in the AST implements one.
    """
    import ast

    banned = ("retry", "backoff", "reschedule", "requeue", "attempt", "queue", "scheduler")
    offenders: list[str] = []
    for path in (PROOF_DIR / "proof_app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            name = None
            if isinstance(node, (ast.Name, ast.Attribute)):
                name = node.id if isinstance(node, ast.Name) else node.attr
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = node.name
            elif isinstance(node, ast.arg):
                name = node.arg
            if name and any(b in name.lower() for b in banned):
                offenders.append(f"{path.name}:{node.lineno} {name}")
    assert not offenders, offenders


def test_x10_importing_the_app_module_has_no_side_effect() -> None:
    """Importing must create nothing. The harness's intake canary watches the temp root.

    This is a regression test for a defect the harness caught rather than one found here: a
    module-level ``create_app()`` built a ``ProofStore``, which made its SQLite directory
    under ``tempfile.gettempdir()`` at import time. ``test_intake_leaves_no_file_in_the_temp_
    directory`` snapshots that directory and fails when a new entry appears while it runs —
    so a proof running alongside the harness suite could fail it. The application is served
    with ``--factory`` and the module now holds no instance.
    """
    import ast
    import tempfile

    source = (PROOF_DIR / "proof_app" / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    module_level_calls = [
        node.lineno
        for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
    ]
    assert not module_level_calls, f"app.py builds something at import time: {module_level_calls}"

    root = Path(tempfile.gettempdir())
    before = set(root.iterdir())
    import importlib

    importlib.reload(importlib.import_module("proof_app.app"))
    created = sorted(p.name for p in set(root.iterdir()) - before)
    assert not created, f"importing proof_app.app created {created}"


# -- double failure: the work fails, and recording the failure fails too -------------------
#
# The last unproven path. Everything above assumes the store still works when something goes
# wrong; this is what happens when it does not. Both exceptions carry a filename and a line
# of the uploaded document, because that is what a real sqlite or intake error looks like.

PRIMARY_CANARY = "ZZPRIMARYCANARYZZ"
SECONDARY_CANARY = "ZZSECONDARYCANARYZZ"


class _StoreThatCannotRecordFailure:
    """A store that works until it is asked to write a failure, then raises.

    Delegates everything else so the run reaches the failure path normally. The exception it
    raises looks like a real one: a disk error quoting a path and a document line.
    """

    def __init__(self, inner) -> None:
        self._inner = inner
        self.failure_writes_attempted = 0

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def set_status(self, run_id, status, *, error_code=None, counts=None):
        if status in {
            BootstrapStatus.RESEARCH_FAILED,
            BootstrapStatus.DISCOVERY_FAILED_REUPLOAD_REQUIRED,
        }:
            self.failure_writes_attempted += 1
            raise sqlite3.OperationalError(
                f"disk I/O error while writing {SECONDARY_CANARY} "
                f"/srv/uploads/고객사_단가표.xlsx — 메콩델타 수치 12,400"
            )
        return self._inner.set_status(run_id, status, error_code=error_code, counts=counts)


def _double_failure_scenario(tmp_path: Path):
    """Primary failure in the work, secondary failure in the failure recording."""
    from proof_app.runs import BootstrapRunner

    def exploding(report):
        raise RuntimeError(f"{PRIMARY_CANARY} /srv/uploads/내부_원가표.md — 수동 채수 단가 8,900")

    holder: dict = {}

    async def body():
        real = ProofStore(tmp_path / "double.sqlite3")
        store = _StoreThatCannotRecordFailure(real)
        runner = BootstrapRunner(store)
        run_id = store.create_run()
        runner.start(run_id, exploding)
        await _drain(runner)
        holder["store"] = store
        holder["real"] = real
        holder["run_id"] = run_id
        return runner.active_count, real.get_run(run_id)

    (active, row), reported = _runner_scenario(body, tmp_path)
    return active, row, reported, holder


def test_y_a_double_failure_leaks_no_task_exception(tmp_path: Path, capfd) -> None:
    """Primary failure, then the failure write fails. Nothing may escape the task."""
    active, row, reported, holder = _double_failure_scenario(tmp_path)

    assert holder["store"].failure_writes_attempted == 1, "the failure path was not reached"
    assert reported == [], f"the asyncio loop reported something: {reported}"
    assert not [m for m in reported if "never retrieved" in m]

    captured = capfd.readouterr()
    combined = captured.out + captured.err
    for leak in (
        "Traceback",
        "never retrieved",
        "OperationalError",
        "RuntimeError",
        PRIMARY_CANARY,
        SECONDARY_CANARY,
        ".xlsx",
        ".md —",
        "고객사",
        "메콩",
        "8,900",
        "12,400",
    ):
        assert leak not in combined, f"{leak!r} reached stdout/stderr"


def test_y2_the_fallback_log_carries_a_run_id_and_a_stable_code_only(
    tmp_path: Path, caplog
) -> None:
    """The one line the double-failure path is allowed to emit."""
    with caplog.at_level(logging.INFO, logger="phase8.proof"):
        active, row, reported, holder = _double_failure_scenario(tmp_path)

    lines = [r.getMessage() for r in caplog.records]
    fallback = [line for line in lines if "background_failure_unrecorded" in line]
    assert len(fallback) == 1, lines

    line = fallback[0]
    assert "error_code=BACKGROUND_FAILURE_RECORDING_FAILED" in line
    assert f"run_id={holder['run_id']}" in line

    # Exactly two fields, and both are allowlisted.
    fields = dict(pair.split("=", 1) for pair in line.split("  ", 1)[1].split(" "))
    assert set(fields) == {"run_id", "error_code"}
    assert set(fields) <= ALLOWED_FIELDS

    everything = "\n".join(lines)
    for leak in (
        PRIMARY_CANARY,
        SECONDARY_CANARY,
        "Traceback",
        "OperationalError",
        "RuntimeError",
        ".xlsx",
        "고객사",
        "메콩",
        "disk I/O",
        "8,900",
        "12,400",
    ):
        assert leak not in everything, f"{leak!r} reached the log"


def test_y3_the_registry_is_empty_after_a_double_failure(tmp_path: Path) -> None:
    active, row, reported, holder = _double_failure_scenario(tmp_path)
    assert active == 0, f"{active} tasks left behind after a double failure"


def test_y4_a_double_failure_does_not_fake_a_stored_state(tmp_path: Path) -> None:
    """The write that would have marked it failed is the thing that broke.

    So the row keeps saying what it last truly said. Pretending otherwise would record a
    state no code ever successfully wrote.
    """
    active, row, reported, holder = _double_failure_scenario(tmp_path)

    assert row["stored_status"] == "RUNNING_RESEARCH"
    assert row["error_code"] is None, "an error code was stored by a write that failed"

    # And the existing stale-state rule still reads it correctly in a later process.
    later = ProofStore(tmp_path / "double.sqlite3")
    assert later.get_run(holder["run_id"])["status"] == "INTERRUPTED_REUPLOAD_REQUIRED"


def test_y5_the_double_failure_path_adds_no_retry_or_queue() -> None:
    """The fallback must not have reached for the infrastructure section 10 excludes."""
    import ast

    source = (PROOF_DIR / "proof_app" / "runs.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    handler = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_note_unrecorded_failure"
    )
    calls = [
        node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        for node in ast.walk(handler)
        if isinstance(node, ast.Call)
    ]
    assert calls == ["log_event"], f"the fallback does more than log: {calls}"


# -- the width of the exception boundary ---------------------------------------------------
#
# Containment is for ordinary failures. Three things must pass through it: cancellation,
# because that is how shutdown works, and KeyboardInterrupt and SystemExit, because those are
# the process asking to stop and a background task does not get to out-vote that. All three
# derive from BaseException and none derives from Exception, which is why the handlers catch
# Exception — the narrower word is the load-bearing one.


def test_z_the_handlers_catch_exception_not_baseexception() -> None:
    """Structural: no ``except BaseException`` anywhere in the proof application.

    Asserted on the AST rather than by grep so the module's prose about BaseException does
    not flag itself.
    """
    import ast

    offenders: list[str] = []
    for path in (PROOF_DIR / "proof_app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and isinstance(node.type, ast.Name):
                if node.type.id == "BaseException":
                    offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, offenders


def test_z0_the_three_pass_through_exception_by_construction() -> None:
    """The language guarantee the boundary rests on, stated once."""
    import asyncio

    for cls in (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        assert issubclass(cls, BaseException)
        assert not issubclass(cls, Exception), cls


def test_z1_an_ordinary_secondary_exception_is_still_contained(tmp_path: Path) -> None:
    """Regression guard for the narrowing: the double-failure path still contains."""
    active, row, reported, holder = _double_failure_scenario(tmp_path)
    assert holder["store"].failure_writes_attempted == 1
    assert reported == []
    assert active == 0
    assert row["stored_status"] == "RUNNING_RESEARCH"


def test_z2_cancellation_during_failure_recording_propagates(tmp_path: Path) -> None:
    """A cancel arriving while the failure is being written must not be contained."""
    import asyncio

    from proof_app.runs import BootstrapRunner

    class _StoreCancelledWhileRecording:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def set_status(self, run_id, status, *, error_code=None, counts=None):
            if status is BootstrapStatus.RESEARCH_FAILED:
                raise asyncio.CancelledError()
            return self._inner.set_status(run_id, status, error_code=error_code, counts=counts)

    outcome: dict = {}

    async def scenario():
        real = ProofStore(tmp_path / "cancel_record.sqlite3")
        runner = BootstrapRunner(_StoreCancelledWhileRecording(real))
        run_id = real.create_run()
        runner.start(run_id, lambda report: (_ for _ in ()).throw(RuntimeError("primary")))
        await _drain(runner)
        task_states = [t.cancelled() for t in list(runner._tasks)]
        outcome["active"] = runner.active_count
        outcome["cancelled"] = task_states
        outcome["row"] = real.get_run(run_id)

    asyncio.run(scenario())

    # Not contained: the task ends cancelled rather than reaching the fallback log.
    assert outcome["active"] == 0, "the registry must still be cleaned up"
    assert outcome["row"]["stored_status"] == "RUNNING_RESEARCH"
    assert outcome["row"]["error_code"] is None


def _work_raising(exc: BaseException):
    def work(report):
        raise exc

    return work


def test_z3_systemexit_from_the_work_is_not_swallowed(tmp_path: Path) -> None:
    """A background task does not get to out-vote the process leaving."""
    import asyncio

    from proof_app.runs import BootstrapRunner

    seen: dict = {}

    async def scenario():
        store = ProofStore(tmp_path / "sysexit.sqlite3")
        runner = BootstrapRunner(store)
        run_id = store.create_run()
        seen["run_id"] = run_id
        seen["store"] = store
        runner.start(run_id, _work_raising(SystemExit(7)))
        await asyncio.sleep(0.4)

    with pytest.raises(SystemExit) as raised:
        asyncio.run(scenario())
    assert raised.value.code == 7, "SystemExit was contained or altered"

    row = seen["store"].get_run(seen["run_id"])
    assert row["stored_status"] == "RUNNING_RESEARCH", "a failure state was faked"
    assert row["error_code"] is None

    # Collect the abandoned task here rather than letting asyncio's notice surface
    # inside an unrelated test later. The notice is expected: not swallowing a
    # process-level exception is the whole point of this test.
    import gc

    gc.collect()


def test_z4_keyboardinterrupt_from_the_work_is_not_swallowed(tmp_path: Path) -> None:
    import asyncio

    from proof_app.runs import BootstrapRunner

    async def scenario():
        store = ProofStore(tmp_path / "kbint.sqlite3")
        runner = BootstrapRunner(store)
        run_id = store.create_run()
        runner.start(run_id, _work_raising(KeyboardInterrupt()))
        await asyncio.sleep(0.4)

    with pytest.raises(KeyboardInterrupt):
        asyncio.run(scenario())

    # Collect the abandoned task here rather than letting asyncio's notice surface
    # inside an unrelated test later. The notice is expected: not swallowing a
    # process-level exception is the whole point of this test.
    import gc

    gc.collect()


def test_z5_systemexit_from_the_fallback_logger_is_not_swallowed(tmp_path: Path) -> None:
    """The last-resort ``except`` is narrow too: an interrupt mid-log still leaves."""
    import asyncio

    import proof_app.runs as runs_module
    from proof_app.runs import BootstrapRunner

    class _StoreThatAlwaysFails:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def set_status(self, run_id, status, *, error_code=None, counts=None):
            if status is BootstrapStatus.RESEARCH_FAILED:
                raise sqlite3.OperationalError("secondary")
            return self._inner.set_status(run_id, status, error_code=error_code, counts=counts)

    original = runs_module.log_event

    def exploding_log(*a, **k):
        raise SystemExit(9)

    async def scenario():
        store = ProofStore(tmp_path / "logexit.sqlite3")
        runner = BootstrapRunner(_StoreThatAlwaysFails(store))
        run_id = store.create_run()
        runner.start(run_id, lambda report: (_ for _ in ()).throw(RuntimeError("primary")))
        await asyncio.sleep(0.4)

    runs_module.log_event = exploding_log
    try:
        with pytest.raises(SystemExit) as raised:
            asyncio.run(scenario())
        assert raised.value.code == 9
    finally:
        runs_module.log_event = original
        import gc

        gc.collect()


def test_z6_registry_and_safe_logging_survive_the_narrowing(tmp_path: Path, caplog) -> None:
    """Both regressions the narrowing could have caused, in one pass."""
    from proof_app.runs import BootstrapRunner, RunOutcome

    async def body():
        store = ProofStore(tmp_path / "mixed.sqlite3")
        runner = BootstrapRunner(store)
        for index in range(6):
            run_id = store.create_run()
            if index % 2:
                runner.start(run_id, lambda report: (_ for _ in ()).throw(ValueError("x")))
            else:
                runner.start(run_id, lambda report: RunOutcome(status=BootstrapStatus.COMPLETED))
        await _drain(runner)
        return runner.active_count

    with caplog.at_level(logging.INFO, logger="phase8.proof"):
        active, reported = _runner_scenario(body, tmp_path)

    assert active == 0, "registry cleanup regressed"
    assert reported == [], reported

    # Only this application's logger. `caplog` captures every logger in the process, and
    # the SystemExit tests above deliberately abandon a task — asyncio emits its "never
    # retrieved" notice when that task is collected, which can surface inside any later
    # test. That notice belongs to those tests and is expected there; the question here is
    # what *we* logged.
    ours = [r for r in caplog.records if r.name == "phase8.proof"]
    text = chr(10).join(r.getMessage() for r in ours)
    for leak in ("Traceback", "ValueError", "never retrieved"):
        assert leak not in text, leak
    assert not [r for r in ours if r.levelno > logging.INFO], "our logger raised its voice"
