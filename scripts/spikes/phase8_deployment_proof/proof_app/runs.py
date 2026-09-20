# -*- coding: utf-8 -*-
"""Bootstrap run state and the in-process background execution that drives it.

**Every state here is application-local.** None of it is a core enum and none of it is
persisted by the harness's ``StorageProvider`` — ``docs/product-spec.md`` fixes that boundary
and this module is the proof that the boundary is workable.

The lifecycle is the one ``HARNESS.md`` section 10 permits: the work runs in *this* process,
on a worker thread, with no broker, no worker fleet, no durable queue, no automatic retry and
no exactly-once guarantee. The consequence is the state at the bottom of the enum — a run
found still ``RUNNING_*`` after a restart did not survive, and saying so is the whole point of
recording it.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from proof_app.safe_log import log_event


class BootstrapStatus(str, Enum):
    """The seven states a Bootstrap Analysis Run passes through, plus one recovery reading.

    Research succeeding and discovery failing is a **partial success**: findings, SWOT and key
    issues are already stored and their review resumes. What cannot resume is discovery,
    because the evidence candidates it reads were never persisted and cannot be. The state
    name says ``REUPLOAD_REQUIRED`` at that length on purpose — a screen that says only
    "failed" sends somebody looking for a retry button that cannot exist.
    """

    NOT_STARTED = "NOT_STARTED"
    RUNNING_RESEARCH = "RUNNING_RESEARCH"
    RESEARCH_COMPLETED = "RESEARCH_COMPLETED"
    RUNNING_DISCOVERY = "RUNNING_DISCOVERY"
    COMPLETED = "COMPLETED"
    RESEARCH_FAILED = "RESEARCH_FAILED"
    DISCOVERY_FAILED_REUPLOAD_REQUIRED = "DISCOVERY_FAILED_REUPLOAD_REQUIRED"
    #: Not a stored transition. A **view-level reading** of a row left ``RUNNING_*`` by a
    #: process that died — derived at read time, never written by the runner.
    INTERRUPTED_REUPLOAD_REQUIRED = "INTERRUPTED_REUPLOAD_REQUIRED"


#: States a run can be left in when the process disappears mid-flight.
RUNNING_STATES: frozenset[BootstrapStatus] = frozenset(
    {BootstrapStatus.RUNNING_RESEARCH, BootstrapStatus.RUNNING_DISCOVERY}
)

#: States from which nothing more will happen without a fresh upload.
TERMINAL_STATES: frozenset[BootstrapStatus] = frozenset(
    {
        BootstrapStatus.COMPLETED,
        BootstrapStatus.RESEARCH_FAILED,
        BootstrapStatus.DISCOVERY_FAILED_REUPLOAD_REQUIRED,
        BootstrapStatus.INTERRUPTED_REUPLOAD_REQUIRED,
    }
)

#: Whether the user has to upload documents again to get further.
NEEDS_REUPLOAD: frozenset[BootstrapStatus] = frozenset(
    {
        BootstrapStatus.RESEARCH_FAILED,
        BootstrapStatus.DISCOVERY_FAILED_REUPLOAD_REQUIRED,
        BootstrapStatus.INTERRUPTED_REUPLOAD_REQUIRED,
    }
)


@dataclass(frozen=True)
class RunOutcome:
    """What one background run produced, in counts. No text, ever."""

    status: BootstrapStatus
    error_code: Optional[str] = None
    candidate_count: int = 0
    finding_count: int = 0
    llm_calls: int = 0


class BootstrapRunner:
    """Starts a run on a worker thread of this process and returns immediately.

    ``asyncio.create_task`` plus a thread, and nothing else. There is deliberately no queue to
    put work on, no retry wrapper and no scheduler: each of those is the first half of the
    infrastructure the exclusion list exists to keep out, and each would make the process-loss
    behaviour below stop being true.

    Two properties of the registry are load-bearing and easy to get wrong.

    **A running task is strongly referenced.** ``asyncio`` keeps only a weak reference to a
    task, so a task nobody holds can be garbage-collected mid-flight and simply stop. The set
    below is what stops that happening — it is a lifetime anchor, not a queue.

    **A finished task is dropped.** ``add_done_callback(discard)`` removes it the moment it
    settles, whichever way it settled. Without that the set is a slow leak: every run ever
    started stays reachable for as long as the process lives.
    """

    def __init__(self, store, *, sleep_between_stages: float = 0.0) -> None:
        self._store = store
        self._sleep = sleep_between_stages
        #: Strong references to in-flight tasks, and nothing else. Entries leave on
        #: completion, failure and cancellation alike.
        self._tasks: set[asyncio.Task] = set()

    @property
    def active_count(self) -> int:
        """In-flight tasks. Should return to zero after every run, however it ended."""
        return len(self._tasks)

    def start(self, run_id: str, work: Callable[[Callable[[BootstrapStatus], None]], RunOutcome]) -> None:
        """Schedule ``work`` on a thread. ``work`` receives a callback to report each stage."""
        self._store.set_status(run_id, BootstrapStatus.RUNNING_RESEARCH)
        task = asyncio.get_running_loop().create_task(self._drive(run_id, work))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _drive(self, run_id: str, work) -> None:
        """Nothing escapes this coroutine except cancellation.

        An exception that leaves a background task is retrieved by nobody, and Python reports
        that at collection time as ``Task exception was never retrieved`` — on stderr, with a
        full traceback, outside the allowlist that every other line in this application goes
        through. A stack trace from inside intake quotes the document that produced it. So
        every failure is turned into an application state and a stable code here, and the
        message is discarded unread.

        The boundary is ``Exception``, not ``BaseException``, and the width is the point.
        ``CancelledError``, ``KeyboardInterrupt`` and ``SystemExit`` all derive from
        ``BaseException`` and none of them derives from ``Exception``, so all three pass
        straight through. That is what is wanted:

        * **cancellation** is how shutdown stops an in-flight run. The row stays ``RUNNING_*``
          and a later process reads it as ``INTERRUPTED_REUPLOAD_REQUIRED``;
        * **``KeyboardInterrupt`` and ``SystemExit`` are the process asking to stop.** A
          background task is the last place that should out-vote that. asyncio surfaces them
          out of the loop rather than filing them against the task, and it also logs
          "Task exception was never retrieved" for them — noise that belongs to a process
          that is on its way down, and a fair price for not swallowing an interrupt.

        Catching ``BaseException`` here would contain all three, which reads as thorough and
        is the opposite: a run that cannot be interrupted and a process that cannot exit.

        An earlier version paired this with an explicit ``except asyncio.CancelledError:
        raise``. It was removed because it is **functionally redundant**, not because it
        could never run: ``CancelledError`` is not included in ``Exception``, so it already
        propagates without a clause of its own. Re-adding one would restate a guarantee the
        language makes, and the next reader would reasonably wonder what it is guarding
        against.
        """
        import anyio.to_thread

        # The furthest stage the work reported. Written on the worker thread, read after the
        # await completes, so the hand-off is ordered.
        progress = {"stage": BootstrapStatus.RUNNING_RESEARCH}

        def report(status: BootstrapStatus) -> None:
            # Called from the worker thread. sqlite3 connections are opened per call in
            # store.py, so there is no cross-thread connection sharing to get wrong.
            progress["stage"] = status
            self._store.set_status(run_id, status)

        try:
            outcome: RunOutcome = await anyio.to_thread.run_sync(lambda: work(report))
            if self._sleep:
                await asyncio.sleep(self._sleep)
            self._store.set_status(
                run_id,
                outcome.status,
                error_code=outcome.error_code,
                counts={
                    "candidate_count": outcome.candidate_count,
                    "finding_count": outcome.finding_count,
                    "llm_calls": outcome.llm_calls,
                },
            )
        except Exception:  # noqa: BLE001 — a code is recorded, never the message
            self._record_failure(run_id, progress["stage"])

    def _record_failure(self, run_id: str, reached: BootstrapStatus) -> None:
        """Turn a raised exception into the honest terminal state for where it happened.

        Failing after research completed is a **partial success**: the findings are already
        stored and their review resumes, so the state is the one that says a reupload is
        needed for discovery — not the one that says nothing survived.
        """
        after_research = reached in {BootstrapStatus.RESEARCH_COMPLETED, BootstrapStatus.RUNNING_DISCOVERY}
        status = (
            BootstrapStatus.DISCOVERY_FAILED_REUPLOAD_REQUIRED
            if after_research
            else BootstrapStatus.RESEARCH_FAILED
        )
        code = "DISCOVERY_FAILED" if after_research else "RESEARCH_FAILED"
        try:
            self._store.set_status(run_id, status, error_code=code)
        except Exception:  # noqa: BLE001 — the second failure, handled like the first
            self._note_unrecorded_failure(run_id)

    def _note_unrecorded_failure(self, run_id: str) -> None:
        """The store itself failed while recording a failure. Say so, and stop.

        This is the double-failure path: something raised, and the write that was supposed to
        turn that into an application state raised too. Three things must not happen here.

        **No pretending.** The row is not marked failed, because the write that would have
        marked it is the thing that broke. It stays ``RUNNING_*`` and the next reader derives
        ``INTERRUPTED_REUPLOAD_REQUIRED`` from it — which is exactly what happened.

        **No retrying, queueing or rescheduling.** Each is the first half of the
        infrastructure ``HARNESS.md`` section 10 excludes, and reaching for one here is how a
        proof acquires a broker.

        **No escaping.** An ordinary exception leaving this method lands back in the task,
        unretrieved, and Python prints it with a traceback at collection time — outside every
        allowlist this application has. Both exceptions are discarded unread; the original one
        is the dangerous one, because a traceback from inside intake quotes the document.
        ``KeyboardInterrupt`` and ``SystemExit`` are not ordinary and are not caught.

        What is left is one allowlisted line: an opaque run id and a stable code.
        """
        try:
            log_event(
                "proof.background_failure_unrecorded",
                run_id=run_id,
                error_code="BACKGROUND_FAILURE_RECORDING_FAILED",
            )
        except Exception:  # noqa: BLE001
            # The logger was the last thing that could report anything. If it is also gone
            # there is nowhere left to put this, and raising would re-open the leak above.
            # Still only ``Exception``: an interrupt arriving mid-log is the process leaving,
            # and a log line is not worth suppressing that.
            pass


def reading_for(status: BootstrapStatus, *, process_started_at: float, row_updated_at: float) -> BootstrapStatus:
    """How a stored status should be *read*, given when this process started.

    A row that still says ``RUNNING_*`` but was last touched before this process existed
    belongs to a process that is gone. Nothing will move it, so it reads as
    ``INTERRUPTED_REUPLOAD_REQUIRED``.

    The derivation happens here, at read time, and is never written back. Writing it would
    lose the distinction between "the run recorded that it was interrupted" — which nothing
    can do, because a process that dies records nothing — and "a reader worked it out".
    """
    if status in RUNNING_STATES and row_updated_at < process_started_at:
        return BootstrapStatus.INTERRUPTED_REUPLOAD_REQUIRED
    return status
