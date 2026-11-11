"""PageJobRunner: pre-flight, upload, tracking and cancel of one page job against the fake printer.

The printer is ``FakeIppPrinter`` behind an ASGI transport; no network is touched. Every wait
is bounded by ``asyncio.timeout`` (no pytest-timeout plugin).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from app.models.job import Job as DbJob
from app.models.job import JobState as DbJobState
from app.printer_backends.ipp.client import IppClient
from app.printer_backends.ipp.job_attrs import wire_job_name
from app.services.job_lifecycle import Job, JobState
from app.services.job_store import MemoryJobStore
from app.services.page_job_runner import MAX_CONSECUTIVE_POLL_ERRORS, Deferred, PageJobRunner
from app.services.page_jobs import IppPagePrinter, PageJob, PagePayload
from app.services.producers.ipp_status_producer import IppPrinterState

from tests.helpers.fake_ipp_printer import (
    FAKE_URI,
    FailingTransport,
    FakeIppPrinter,
    FlakyTransport,
)
from tests.helpers.page_jobs import RecordingHandler, payload, registered

TEST_TIMEOUT_S = 10.0


class _Env:
    def __init__(
        self,
        fake: FakeIppPrinter,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        poll_interval_s: float = 0.0,
        max_backoff_s: float = 0.0,
        sleep: Callable[[float], Any] | None = None,
        render_timeout_s: float | None = None,
    ) -> None:
        self.fake = fake
        self.store = MemoryJobStore()
        self.state = IppPrinterState()
        self.client = IppClient(FAKE_URI, transport=transport or httpx.ASGITransport(app=fake))
        self.printer = IppPagePrinter(id=uuid4(), client=self.client, state=self.state)
        self.events: list[tuple[JobState, JobState, str | None]] = []
        kwargs: dict[str, Any] = {}
        if sleep is not None:
            kwargs["sleep"] = sleep
        self.runner = PageJobRunner(
            store=self.store,
            notify=self._notify,
            poll_interval_s=poll_interval_s,
            max_backoff_s=max_backoff_s,
            render_timeout_s=render_timeout_s,
            **kwargs,
        )

    def _notify(self, job: Job, from_state: JobState, to_state: JobState, **_: Any) -> None:
        self.events.append((from_state, to_state, job.at_printer))

    async def job(self, p: PagePayload | None = None, *, api_key_id: UUID | None = None) -> PageJob:
        p = p or payload()
        row = DbJob(printer_id=self.printer.id, payload=p.model_dump(mode="json"))
        await self.store.save_queued(row)
        return PageJob(
            job=Job(id=str(row.id), printer_id=self.printer.id, kind=p.kind),
            payload=p,
            api_key_id=api_key_id,
        )

    async def row(self, page_job: PageJob) -> DbJob:
        row = await self.store.get(UUID(page_job.job.id))
        assert row is not None
        return row

    def ops(self, name: str) -> int:
        return sum(1 for r in self.fake.received if r.operation == name)

    async def run(self, page_job: PageJob) -> None:
        async with asyncio.timeout(TEST_TIMEOUT_S):
            await self.runner.run(self.printer, page_job)


@pytest.fixture
def handler() -> Any:
    with registered(RecordingHandler()) as h:
        yield h


async def _until(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(TEST_TIMEOUT_S):
        while not predicate():
            await asyncio.sleep(0.005)


# ---------------------------------------------------------------------------- happy path


class _RecordingStore(MemoryJobStore):
    """Remembers the order of the writes that matter for a failure."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def set_result(self, job_id: UUID, result: dict[str, Any]) -> None:
        self.calls.append(("set_result", dict(result)))
        await super().set_result(job_id, result)

    async def mark_failed_code(self, job_id: UUID, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("mark_failed_code", kwargs.get("result")))
        await super().mark_failed_code(job_id, *args, **kwargs)


async def test_failure_writes_result_and_state_in_one_call(handler: RecordingHandler) -> None:
    """M12: no separate ``phase=ended`` write before the state change (two commits on SQLite)."""
    env = _Env(FakeIppPrinter(print_status=0x040A))
    env.store = _RecordingStore()
    env.runner = PageJobRunner(
        store=env.store, notify=env._notify, poll_interval_s=0.0, max_backoff_s=0.0
    )
    pj = await env.job()
    await env.run(pj)

    calls = env.store.calls
    assert not any(name == "set_result" and r and r.get("phase") == "ended" for name, r in calls)
    assert calls[-1][0] == "mark_failed_code"
    ended = calls[-1][1]
    assert ended is not None and ended["phase"] == "ended" and ended["started"] is False
    row = await env.row(pj)
    assert row.state == DbJobState.FAILED.value and row.result["phase"] == "ended"


class _FailingStore(MemoryJobStore):
    """A store whose terminal write raises (the database is gone)."""

    def __init__(self, fail: str) -> None:
        super().__init__()
        self.fail = fail

    async def mark_done(self, job_id: UUID) -> None:
        if self.fail == "done":
            raise RuntimeError("db down")
        await super().mark_done(job_id)

    async def mark_cancelled(self, job_id: UUID, *, allow_printing: bool = False) -> None:
        if self.fail == "cancelled":
            raise RuntimeError("db down")
        await super().mark_cancelled(job_id, allow_printing=allow_printing)

    async def mark_failed_code(self, job_id: UUID, *args: Any, **kwargs: Any) -> None:
        if self.fail == "failed":
            raise RuntimeError("db down")
        await super().mark_failed_code(job_id, *args, **kwargs)


@pytest.mark.parametrize(
    ("fail", "fake_kwargs"),
    [
        ("done", {"job_script": [9]}),
        ("cancelled", {"job_script": [3, 7]}),
        ("failed", {"print_status": 0x040A}),
    ],
)
async def test_terminal_state_is_persisted_before_it_is_published(
    handler: RecordingHandler, fail: str, fake_kwargs: dict[str, Any]
) -> None:
    """If the database write fails, the job must not claim success (or any end) in memory.

    The exception reaches the queue's backstop, which can only repair a job that is still
    ``printing``; no terminal event went out and no waiter was released.
    """
    env = _Env(FakeIppPrinter(**fake_kwargs))
    env.store = _FailingStore(fail)
    env.runner = PageJobRunner(
        store=env.store, notify=env._notify, poll_interval_s=0.0, max_backoff_s=0.0
    )
    pj = await env.job()
    with pytest.raises(RuntimeError, match="db down"):
        await env.run(pj)
    assert pj.job.state == JobState.PRINTING
    assert not pj.job._done_event.is_set()
    assert all(to_state == JobState.PRINTING for _from, to_state, _where in env.events[1:])
    assert handler.names(UUID(pj.job.id)) in ([], ["started"])  # no completion


@pytest.mark.parametrize("bad_state", [0, 2, 10, 99, -1])
async def test_out_of_range_job_state_is_waiting_not_a_failure(
    handler: RecordingHandler, bad_state: int
) -> None:
    """A job-state outside 3..9 is shown as waiting; the printer, not the hub, owns the job.

    It never ends the job by itself (265-08): the poll goes on until the printer says
    something usable, however many unusable states came before.
    """
    script = [bad_state] * (MAX_CONSECUTIVE_POLL_ERRORS + 2) + [9]
    env = _Env(FakeIppPrinter(job_script=script))
    pj = await env.job()
    await env.run(pj)
    assert pj.job.state == JobState.COMPLETED
    assert env.ops("Get-Job-Attributes") == len(script)
    assert (JobState.PRINTING, JobState.PRINTING, "waiting") in env.events


async def test_unknown_job_state_logged_once(
    handler: RecordingHandler, caplog: pytest.LogCaptureFixture
) -> None:
    """Two polls with the same unknown state give one WARNING per job, without payload."""
    env = _Env(FakeIppPrinter(job_script=[99, 99, 9]))
    pj = await env.job()
    with caplog.at_level(logging.WARNING, logger="app.services.page_job_runner"):
        await env.run(pj)
    unknown = [r for r in caplog.records if "unknown job-state" in r.getMessage()]
    assert len(unknown) == 1
    assert unknown[0].levelno == logging.WARNING
    assert f"job {pj.job.id}: unknown job-state 99" in unknown[0].getMessage()


async def test_completed_flow(handler: RecordingHandler) -> None:
    env = _Env(FakeIppPrinter(job_script=[3, 5, 9]))
    pj = await env.job()
    await env.run(pj)

    row = await env.row(pj)
    assert row.state == DbJobState.DONE.value
    assert pj.job.state == JobState.COMPLETED
    assert row.result is not None
    assert row.result["ipp_job_id"] == 1
    assert row.result["started"] is True
    assert "job_uri" not in row.result  # the printer address stays admin-only
    assert handler.names() == ["started", "completed"]
    assert (JobState.QUEUED, JobState.PRINTING, None) in env.events
    assert (JobState.PRINTING, JobState.PRINTING, "waiting") in env.events
    assert (JobState.PRINTING, JobState.PRINTING, "printing") in env.events
    assert env.events[-1][1] == JobState.COMPLETED
    assert env.ops("Print-Job") == 1
    # the hub's own job is not counted as a job ahead while tracked, and forgotten when final
    assert env.state.own_job_ids == set()


async def test_own_job_id_is_registered_while_tracking(handler: RecordingHandler) -> None:
    env = _Env(FakeIppPrinter(job_script=[3]), poll_interval_s=0.01)
    pj = await env.job()
    task = asyncio.create_task(env.run(pj))
    await _until(lambda: env.runner.is_tracking(UUID(pj.job.id)))
    assert env.state.own_job_ids == {1}
    env.fake.job_script = [9]
    await task
    assert env.state.own_job_ids == set()
    assert not env.runner.is_tracking(UUID(pj.job.id))


async def test_print_job_attributes_and_document_sent(handler: RecordingHandler) -> None:
    env = _Env(FakeIppPrinter(job_script=[9]))
    pj = await env.job()
    await env.run(pj)
    sent = next(r for r in env.fake.received if r.operation == "Print-Job")
    assert sent.document.startswith(b"%PDF")
    (name,) = sent.attributes["job-name"]
    assert name == wire_job_name("Calibration page · test v1", pj.job.id)
    assert name.startswith("Calibration page · test v1 [") and name.endswith("]")
    assert "media-col" in sent.job_attributes


async def test_substituted_attributes_are_recorded(handler: RecordingHandler) -> None:
    env = _Env(FakeIppPrinter(job_script=[9], print_status=0x0001))
    pj = await env.job()
    await env.run(pj)
    row = await env.row(pj)
    assert row.state == DbJobState.DONE.value
    assert row.result is not None and row.result["attributes_substituted"] is True


async def test_first_poll_already_completed_counts_as_started(handler: RecordingHandler) -> None:
    env = _Env(FakeIppPrinter(job_script=[9]))
    pj = await env.job()
    await env.run(pj)
    assert handler.names() == ["started", "completed"]


# ---------------------------------------------------------------------------- cancel


async def test_cancel_before_start_at_printer(handler: RecordingHandler) -> None:
    env = _Env(FakeIppPrinter(job_script=[3]), poll_interval_s=0.01)
    pj = await env.job()
    jid = UUID(pj.job.id)
    task = asyncio.create_task(env.run(pj))
    await _until(lambda: env.runner.is_tracking(jid) and env.ops("Get-Job-Attributes") > 0)
    assert await env.runner.request_cancel(jid) is True
    await task

    assert env.ops("Cancel-Job") == 1
    row = await env.row(pj)
    assert row.state == DbJobState.CANCELLED.value
    assert pj.job.state == JobState.CANCELLED
    assert handler.ended(jid) == {"state": "cancelled", "started": False, "error_code": "cancelled"}
    assert "started" not in handler.names(jid)


async def test_asynchronous_cancel_keeps_polling_until_final(handler: RecordingHandler) -> None:
    """Spike S2: after Cancel-Job the job reports processing-to-stop-point before canceled.

    That interim ``processing`` is not evidence that the page started printing.
    """
    env = _Env(FakeIppPrinter(job_script=[3], cancel_steps=3), poll_interval_s=0.01)
    pj = await env.job()
    jid = UUID(pj.job.id)
    task = asyncio.create_task(env.run(pj))
    await _until(lambda: env.runner.is_tracking(jid) and env.ops("Get-Job-Attributes") > 0)
    await env.runner.request_cancel(jid)
    await task
    row = await env.row(pj)
    assert row.state == DbJobState.CANCELLED.value
    assert handler.ended(jid)["started"] is False
    assert env.ops("Get-Job-Attributes") >= 4


async def test_cancel_after_start(handler: RecordingHandler) -> None:
    env = _Env(FakeIppPrinter(job_script=[5]), poll_interval_s=0.01)
    pj = await env.job()
    jid = UUID(pj.job.id)
    task = asyncio.create_task(env.run(pj))
    await _until(lambda: "started" in handler.names(jid))
    assert await env.runner.request_cancel(jid) is True
    await task

    row = await env.row(pj)
    assert row.state == DbJobState.FAILED.value
    assert row.error is not None and row.error.startswith("interrupted: ")
    assert row.result is not None and row.result["started"] is True
    assert handler.ended(jid) == {"state": "failed", "started": True, "error_code": "interrupted"}


async def test_cancel_not_possible_means_already_finished(handler: RecordingHandler) -> None:
    """``client-error-not-possible`` on Cancel-Job: the job already ended; read its state."""
    env = _Env(FakeIppPrinter(job_script=[3]), poll_interval_s=0.01)
    pj = await env.job()
    jid = UUID(pj.job.id)
    task = asyncio.create_task(env.run(pj))
    await _until(lambda: env.runner.is_tracking(jid))
    env.fake.job_script = [9]
    env.fake.advance()  # the printer finishes the job before the cancel arrives
    assert await env.runner.request_cancel(jid) is True
    await task
    row = await env.row(pj)
    assert row.state == DbJobState.DONE.value
    assert handler.names(jid) == ["started", "completed"]


async def test_cancel_unknown_job_is_refused(handler: RecordingHandler) -> None:
    env = _Env(FakeIppPrinter())
    assert await env.runner.request_cancel(uuid4()) is False


async def test_cancel_requested_during_render_skips_upload(handler: RecordingHandler) -> None:
    gate = asyncio.Event()
    entered = asyncio.Event()
    loop = asyncio.get_running_loop()

    def slow_render(_p: PagePayload) -> bytes:
        loop.call_soon_threadsafe(entered.set)
        asyncio.run_coroutine_threadsafe(gate.wait(), loop).result(5)
        return b"%PDF-1.4\n%%EOF\n"

    with registered(handler, render=slow_render):
        env = _Env(FakeIppPrinter(job_script=[9]))
        pj = await env.job()
        jid = UUID(pj.job.id)
        task = asyncio.create_task(env.run(pj))
        async with asyncio.timeout(TEST_TIMEOUT_S):
            await entered.wait()
        assert await env.runner.request_cancel(jid) is True
        gate.set()
        await task
    assert env.ops("Print-Job") == 0
    assert (await env.row(pj)).state == DbJobState.CANCELLED.value
    assert handler.ended(jid) == {"state": "cancelled", "started": False, "error_code": "cancelled"}


# ---------------------------------------------------------------------------- final states


async def test_aborted_before_start(handler: RecordingHandler) -> None:
    env = _Env(FakeIppPrinter(job_script=[3, 8]))
    pj = await env.job()
    await env.run(pj)
    row = await env.row(pj)
    assert row.state == DbJobState.FAILED.value
    assert row.error is not None and row.error.startswith("ipp_aborted: ")
    assert handler.ended(UUID(pj.job.id)) == {
        "state": "failed",
        "started": False,
        "error_code": "ipp_aborted",
    }


async def test_aborted_after_start_is_interrupted(handler: RecordingHandler) -> None:
    env = _Env(FakeIppPrinter(job_script=[5, 8]))
    pj = await env.job()
    await env.run(pj)
    assert handler.ended(UUID(pj.job.id))["error_code"] == "interrupted"
    assert handler.ended(UUID(pj.job.id))["started"] is True


async def test_final_state_with_impressions_counts_as_started(handler: RecordingHandler) -> None:
    env = _Env(FakeIppPrinter(job_script=[3, 8], impressions_script=[0, 1]))
    pj = await env.job()
    await env.run(pj)
    row = await env.row(pj)
    assert row.state == DbJobState.FAILED.value
    assert row.error is not None and row.error.startswith("interrupted: ")
    assert row.result is not None and row.result["started"] is True
    assert handler.ended(UUID(pj.job.id)) == {
        "state": "failed",
        "started": True,
        "error_code": "interrupted",
    }


@pytest.mark.parametrize("path", ["final_state", "upload_interrupted"])
async def test_started_is_persisted_before_on_ended(handler: RecordingHandler, path: str) -> None:
    fake = FakeIppPrinter(job_script=[3, 8], impressions_script=[0, 1])
    transport = None
    if path == "upload_interrupted":
        transport = FailingTransport(httpx.ASGITransport(app=fake), "Print-Job", httpx.ReadTimeout)
    env = _Env(fake, transport=transport)
    pj = await env.job()
    seen: list[Any] = []

    async def on_ended(job_id: UUID, **kw: Any) -> None:
        row = await env.store.get(job_id)
        assert row is not None
        seen.append((row.state, (row.result or {}).get("started"), kw["started"]))

    handler.on_ended = on_ended  # type: ignore[method-assign]
    await env.run(pj)
    assert seen == [(DbJobState.FAILED.value, True, True)]


async def test_printer_forgot_job_ends_interrupted(handler: RecordingHandler) -> None:
    env = _Env(FakeIppPrinter(job_script=[5]), poll_interval_s=0.01)
    pj = await env.job()
    jid = UUID(pj.job.id)
    task = asyncio.create_task(env.run(pj))
    await _until(lambda: "started" in handler.names(jid))
    env.fake.forget_jobs()
    await task
    assert handler.ended(jid) == {"state": "failed", "started": True, "error_code": "interrupted"}
    assert env.state.own_job_ids == set()


async def test_printer_stopped_while_tracking_reports_stopped(handler: RecordingHandler) -> None:
    env = _Env(FakeIppPrinter(job_script=[6, 6, 9]))
    pj = await env.job()
    await env.run(pj)
    assert (JobState.PRINTING, JobState.PRINTING, "stopped") in env.events
    assert pj.job.at_printer_reasons == ["job-completed-successfully"]


# ---------------------------------------------------------------------------- upload outcomes


async def test_rejected_document(handler: RecordingHandler) -> None:
    env = _Env(FakeIppPrinter(print_status=0x040A))
    pj = await env.job()
    await env.run(pj)
    row = await env.row(pj)
    assert row.state == DbJobState.FAILED.value
    assert row.error == "ipp_rejected: The printer refused the document."
    assert pj.job.error_code == "ipp_rejected"
    assert pj.job.error_detail == {"ipp_status": "client-error-document-format-not-supported"}
    assert handler.ended(UUID(pj.job.id)) == {
        "state": "failed",
        "started": False,
        "error_code": "ipp_rejected",
    }


async def test_server_error_on_print_job_fails_clean(handler: RecordingHandler) -> None:
    env = _Env(FakeIppPrinter(print_status=0x0500))
    pj = await env.job()
    await env.run(pj)
    assert handler.ended(UUID(pj.job.id))["started"] is False
    assert pj.job.error_code == "ipp_rejected"


async def test_busy_at_upload_fails_clean(handler: RecordingHandler) -> None:
    fake = FakeIppPrinter()
    env = _Env(fake)
    pj = await env.job()

    original = fake._print_job

    def busy_print_job(ops: dict[str, Any]) -> Any:
        fake.busy = True
        try:
            return original(ops)
        finally:
            fake.busy = False

    fake._print_job = busy_print_job  # type: ignore[method-assign]
    await env.run(pj)
    row = await env.row(pj)
    assert row.state == DbJobState.FAILED.value
    assert row.error is not None and row.error.startswith("ipp_busy: ")
    assert handler.ended(UUID(pj.job.id)) == {
        "state": "failed",
        "started": False,
        "error_code": "ipp_busy",
    }


async def test_connect_error_at_upload_fails_clean(handler: RecordingHandler) -> None:
    fake = FakeIppPrinter()
    transport = FlakyTransport(httpx.ASGITransport(app=fake), {"Print-Job": [httpx.ConnectError]})
    env = _Env(fake, transport=transport)
    pj = await env.job()
    await env.run(pj)
    row = await env.row(pj)
    assert row.state == DbJobState.FAILED.value
    assert row.error is not None and row.error.startswith("ipp_unreachable: ")
    assert (row.result or {}).get("started") is False
    assert env.ops("Print-Job") == 0
    assert handler.ended(UUID(pj.job.id)) == {
        "state": "failed",
        "started": False,
        "error_code": "ipp_unreachable",
    }


@pytest.mark.parametrize("exc", [httpx.ReadTimeout, httpx.RemoteProtocolError])
async def test_upload_read_timeout_is_interrupted(
    handler: RecordingHandler, exc: type[httpx.RequestError]
) -> None:
    fake = FakeIppPrinter()
    transport = FailingTransport(httpx.ASGITransport(app=fake), "Print-Job", exc)
    env = _Env(fake, transport=transport)
    pj = await env.job()
    await env.run(pj)
    row = await env.row(pj)
    assert row.state == DbJobState.FAILED.value
    assert row.error is not None and row.error.startswith("interrupted: ")
    assert row.result is not None and row.result["started"] is True
    assert transport.failed_documents  # the printer did receive the document
    assert handler.ended(UUID(pj.job.id)) == {
        "state": "failed",
        "started": True,
        "error_code": "interrupted",
    }


async def test_unusable_answer_to_print_job_is_interrupted(handler: RecordingHandler) -> None:
    """IppBadResponseError after the document was sent: whether it was accepted is unknown."""

    class _NoJobId(httpx.AsyncBaseTransport):
        """Print-Job reaches the printer; the answer it returns lacks the job id."""

        def __init__(self) -> None:
            self.inner = httpx.ASGITransport(app=fake)

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            await request.aread()
            response = await self.inner.handle_async_request(request)
            if fake.received[-1].operation != "Print-Job":
                return response
            await response.aread()
            ok = fake._response(0, fake.received[-1].request_id)
            return httpx.Response(200, headers={"content-type": "application/ipp"}, content=ok)

    fake = FakeIppPrinter()
    env = _Env(fake, transport=_NoJobId())
    pj = await env.job()
    await env.run(pj)
    assert handler.ended(UUID(pj.job.id)) == {
        "state": "failed",
        "started": True,
        "error_code": "interrupted",
    }


async def test_render_error_fails_cleanly(handler: RecordingHandler) -> None:
    def broken(_p: PagePayload) -> bytes:
        raise ValueError("renderer bug")

    with registered(handler, render=broken):
        env = _Env(FakeIppPrinter())
        pj = await env.job()
        await env.run(pj)
    row = await env.row(pj)
    assert row.state == DbJobState.FAILED.value
    assert row.error is not None and row.error.startswith("render_failed: ")
    assert "renderer bug" not in row.error
    assert env.ops("Print-Job") == 0
    assert handler.ended(UUID(pj.job.id)) == {
        "state": "failed",
        "started": False,
        "error_code": "render_failed",
    }


async def test_a_render_past_its_limit_fails_render_timeout(
    handler: RecordingHandler, caplog: pytest.LogCaptureFixture
) -> None:
    """#293: the job ends ``failed/render_timeout`` and nothing is sent; the log names the job
    by id and kind only. The thread keeps its render slot until it ends, then frees it."""
    import threading

    from app.services import render_slots

    release = threading.Event()

    def hung(_p: PagePayload) -> bytes:
        release.wait(TEST_TIMEOUT_S)
        return b"%PDF-"

    caplog.set_level(logging.WARNING)
    try:
        with registered(handler, render=hung):
            env = _Env(FakeIppPrinter(), render_timeout_s=0.05)
            pj = await env.job()
            await env.run(pj)
        row = await env.row(pj)
        assert row.state == DbJobState.FAILED.value
        assert row.error is not None and row.error.startswith("render_timeout: ")
        assert env.ops("Print-Job") == 0
        assert handler.ended(UUID(pj.job.id)) == {
            "state": "failed",
            "started": False,
            "error_code": "render_timeout",
        }
        assert render_slots.stuck_renders() == 1
        warned = [r.getMessage() for r in caplog.records if "exceeded" in r.getMessage()]
        assert warned == [
            f"Render page job {pj.job.id} ({pj.payload.kind}) exceeded 0.05s; its thread keeps "
            f"a render slot until it ends (1 of {render_slots.MAX_CONCURRENT_RENDERS} slots stuck)"
        ]
    finally:
        release.set()
    await _until(lambda: render_slots.stuck_renders() == 0)


async def test_a_page_job_prints_with_a_single_render_slot(
    handler: RecordingHandler, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deadlock guard (#293): the runner takes one render slot per page and none inside it;
    with only one slot the job still prints."""
    from app.services import render_slots

    slots = render_slots._current()
    monkeypatch.setattr(slots, "gate", asyncio.Semaphore(1))
    env = _Env(FakeIppPrinter(job_script=[9]))
    pj = await env.job()
    await env.run(pj)
    assert (await env.row(pj)).state == DbJobState.DONE.value
    assert render_slots.free_slots() == render_slots.MAX_CONCURRENT_RENDERS


async def test_a_key_with_a_stuck_render_cannot_hang_the_second_slot(
    handler: RecordingHandler,
) -> None:
    """F1 (#293): two runs of one key with hanging input. The first job times out and keeps
    its slot; the second fails ``render_timeout`` at once without drawing, so one slot stays
    free and another key's job prints."""
    import threading

    from app.services import render_slots

    release = threading.Event()
    drawn: list[str] = []

    def render(p: PagePayload) -> bytes:
        drawn.append(p.detail["tag"])
        if p.detail["tag"].startswith("hang"):
            release.wait(TEST_TIMEOUT_S)
        return b"%PDF-"

    key, other = uuid4(), uuid4()
    try:
        with registered(handler, render=render):
            env = _Env(FakeIppPrinter(job_script=[9]), render_timeout_s=0.05)
            first = await env.job(payload(tag="hang-1"), api_key_id=key)
            await env.run(first)
            second = await env.job(payload(tag="hang-2"), api_key_id=key)
            await env.run(second)
            assert drawn == ["hang-1"]  # the second never got a thread
            for pj in (first, second):
                assert handler.ended(UUID(pj.job.id))["error_code"] == "render_timeout"
            assert render_slots.free_slots() == render_slots.MAX_CONCURRENT_RENDERS - 1
            third = await env.job(payload(tag="ok"), api_key_id=other)
            await env.run(third)
            assert (await env.row(third)).state == DbJobState.DONE.value
    finally:
        release.set()
    await _until(lambda: render_slots.stuck_renders() == 0)


async def test_jobs_without_a_key_cannot_hang_the_last_slot(handler: RecordingHandler) -> None:
    """Jobs without a key share ``NO_KEY``, which may hang all slots but one: the next job
    without a key fails ``render_unavailable`` at once, a key's job prints on the last slot."""
    import threading

    from app.services import render_slots

    release = threading.Event()
    drawn: list[str] = []

    def render(p: PagePayload) -> bytes:
        drawn.append(p.detail["tag"])
        if p.detail["tag"] == "hang":
            release.wait(TEST_TIMEOUT_S)
        return b"%PDF-"

    try:
        with registered(handler, render=render):
            env = _Env(FakeIppPrinter(job_script=[9]), render_timeout_s=0.05)
            first = await env.job(payload(tag="hang"))
            await env.run(first)
            assert handler.ended(UUID(first.job.id))["error_code"] == "render_timeout"
            second = await env.job(payload(tag="no-key"))
            await env.run(second)
            assert handler.ended(UUID(second.job.id))["error_code"] == "render_unavailable"
            keyed = await env.job(payload(tag="key"), api_key_id=uuid4())
            await env.run(keyed)
            assert (await env.row(keyed)).state == DbJobState.DONE.value
            assert drawn == ["hang", "key"]
    finally:
        release.set()
    await _until(lambda: render_slots.stuck_renders() == 0)


async def test_with_every_slot_stuck_a_page_job_fails_render_unavailable_at_once(
    handler: RecordingHandler,
) -> None:
    """F2 (#293): no job waits in ``printing`` for a slot that may never free."""
    import threading

    from app.services import render_slots

    release = threading.Event()

    def hung() -> None:
        release.wait(TEST_TIMEOUT_S)

    try:
        for _ in range(render_slots.MAX_CONCURRENT_RENDERS):
            with pytest.raises(render_slots.RenderTimeoutError):
                await render_slots.render_bounded(hung, label="t", timeout_s=0.05)
        with registered(handler):
            env = _Env(FakeIppPrinter(), render_timeout_s=TEST_TIMEOUT_S)
            pj = await env.job()
            async with asyncio.timeout(TEST_TIMEOUT_S / 5):  # at once, not after the limit
                await env.run(pj)
        row = await env.row(pj)
        assert row.error is not None and row.error.startswith("render_unavailable: ")
        assert env.ops("Print-Job") == 0
        assert handler.ended(UUID(pj.job.id)) == {
            "state": "failed",
            "started": False,
            "error_code": "render_unavailable",
        }
    finally:
        release.set()
    await _until(lambda: render_slots.stuck_renders() == 0)


async def test_handler_error_does_not_break_the_runner(handler: RecordingHandler) -> None:
    async def boom(job_id: UUID) -> None:
        raise RuntimeError("handler bug")

    handler.on_completed = boom  # type: ignore[method-assign]
    env = _Env(FakeIppPrinter(job_script=[9]))
    pj = await env.job()
    await env.run(pj)
    assert (await env.row(pj)).state == DbJobState.DONE.value


# ---------------------------------------------------------------------------- pre-flight


async def test_preflight_unreachable_raises_deferred(handler: RecordingHandler) -> None:
    fake = FakeIppPrinter()
    transport = FlakyTransport(
        httpx.ASGITransport(app=fake), {"Get-Printer-Attributes": [httpx.ConnectError]}
    )
    env = _Env(fake, transport=transport)
    pj = await env.job()
    with pytest.raises(Deferred) as info:
        await env.run(pj)
    assert info.value.reason_code == "ipp_unreachable"
    assert pj.job.state == JobState.QUEUED
    assert (await env.row(pj)).state == DbJobState.QUEUED.value
    assert env.ops("Print-Job") == 0
    assert handler.calls == []


async def test_not_accepting_defers(handler: RecordingHandler) -> None:
    env = _Env(FakeIppPrinter(accepting_jobs=False))
    pj = await env.job()
    with pytest.raises(Deferred) as info:
        await env.run(pj)
    assert info.value.reason_code == "not_accepting"
    assert (await env.row(pj)).state == DbJobState.QUEUED.value


async def test_blocking_reason_defers(handler: RecordingHandler) -> None:
    env = _Env(FakeIppPrinter(printer_state=5, reasons=["toner-empty-error"]))
    pj = await env.job()
    with pytest.raises(Deferred) as info:
        await env.run(pj)
    assert info.value.reason_code == "toner-empty"
    assert env.ops("Print-Job") == 0
    assert (await env.row(pj)).state == DbJobState.QUEUED.value


async def test_cancelled_during_preflight_is_not_sent(handler: RecordingHandler) -> None:
    """The queue cancels the job (QUEUED -> CANCELLED) while the pre-flight is in flight."""
    from app.services.job_lifecycle import JobStateMachine

    fake = FakeIppPrinter()
    env = _Env(fake)
    pj = await env.job()
    original = fake._get_printer_attributes

    def cancel_then_answer(ops: dict[str, Any]) -> Any:
        JobStateMachine.transition(pj.job, JobState.CANCELLED)
        return original(ops)

    fake._get_printer_attributes = cancel_then_answer  # type: ignore[method-assign]
    await env.run(pj)
    assert env.ops("Print-Job") == 0
    assert (await env.row(pj)).state == DbJobState.QUEUED.value  # the queue persists it


# ---------------------------------------------------------------------------- tracking outages


async def test_unreachable_while_tracking_backs_off(handler: RecordingHandler) -> None:
    delays: list[float] = []

    async def fake_sleep(s: float) -> None:
        delays.append(s)
        await asyncio.sleep(0)

    # The read timeout reaches the printer (one step), the connect errors do not.
    fake = FakeIppPrinter(job_script=[3, 3, 9])
    transport = FlakyTransport(
        httpx.ASGITransport(app=fake),
        {
            "Get-Job-Attributes": [
                httpx.ConnectError,
                httpx.ConnectTimeout,
                httpx.ReadTimeout,
                httpx.ConnectError,
                httpx.ConnectError,
            ]
        },
    )
    env = _Env(fake, transport=transport, poll_interval_s=2.0, max_backoff_s=10.0, sleep=fake_sleep)
    pj = await env.job()
    await env.run(pj)
    assert len(transport.failures) == 5
    assert (await env.row(pj)).state == DbJobState.DONE.value
    assert handler.names() == ["started", "completed"]
    # 2 s poll, then 4, 8, 10, 10, 10 after the failures, back to 2 once it answers again
    assert delays[:7] == [2.0, 4.0, 8.0, 10.0, 10.0, 10.0, 2.0]
    assert not any(t == JobState.FAILED for _, t, _ in env.events)


async def test_unreachable_for_long_never_times_out(handler: RecordingHandler) -> None:
    fake = FakeIppPrinter(job_script=[3])
    transport = FlakyTransport(
        httpx.ASGITransport(app=fake), {"Get-Job-Attributes": [httpx.ConnectError] * 50}
    )
    env = _Env(fake, transport=transport)
    pj = await env.job()
    jid = UUID(pj.job.id)
    task = asyncio.create_task(env.run(pj))
    await _until(lambda: len(transport.failures) == 50)
    assert pj.job.state == JobState.PRINTING
    assert (await env.row(pj)).state == DbJobState.PRINTING.value
    fake.job_script = [9]
    await task
    assert handler.names(jid) == ["started", "completed"]


async def test_blocking_reason_while_idle_defers(handler: RecordingHandler) -> None:
    """Any blocking reason defers, whatever the printer state (consistent with auto-resume)."""
    env = _Env(FakeIppPrinter(printer_state=3, reasons=["media-empty-error"]))
    pj = await env.job()
    with pytest.raises(Deferred) as info:
        await env.run(pj)
    assert info.value.reason_code == "media-empty"
    assert env.ops("Print-Job") == 0


class _BadAnswerTransport(httpx.AsyncBaseTransport):
    """Get-Job-Attributes reaches the printer, the answer is not IPP (bad content type)."""

    def __init__(self, fake: FakeIppPrinter, failures: int) -> None:
        self.inner = httpx.ASGITransport(app=fake)
        self.fake = fake
        self.failures = failures

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await request.aread()
        response = await self.inner.handle_async_request(request)
        if self.fake.received[-1].operation != "Get-Job-Attributes" or self.failures <= 0:
            return response
        await response.aread()
        self.failures -= 1
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html/>")


@pytest.mark.parametrize("kind", ["status_error", "bad_answer"])
async def test_persistent_poll_errors_end_interrupted(handler: RecordingHandler, kind: str) -> None:
    """Not a reachability problem (OC-23 does not apply): five failures in a row end the job."""
    fake = FakeIppPrinter(job_script=[5])
    transport: httpx.AsyncBaseTransport | None = None
    if kind == "bad_answer":
        transport = _BadAnswerTransport(fake, failures=10_000)
    env = _Env(fake, transport=transport)
    pj = await env.job()
    original = fake._get_job
    polls = {"n": 0}

    def first_ok_then_forbidden(ops: dict[str, Any]) -> Any:
        polls["n"] += 1
        if polls["n"] == 1:
            return original(ops)  # observed processing: started
        return 0x0401, []  # client-error-forbidden

    if kind == "status_error":
        fake._get_job = first_ok_then_forbidden  # type: ignore[method-assign]
    else:
        transport.failures = 0  # type: ignore[union-attr]

        async def on_started(job_id: UUID) -> None:
            # the first poll observed processing; from now on every answer is unusable
            transport.failures = 10_000  # type: ignore[union-attr]

        handler.on_started = on_started  # type: ignore[method-assign]
    await env.run(pj)
    row = await env.row(pj)
    assert row.state == DbJobState.FAILED.value
    assert row.error is not None and row.error.startswith("interrupted: ")
    assert row.result is not None and row.result["started"] is True
    assert pj.job.error_code == "interrupted"
    assert env.ops("Get-Job-Attributes") == 1 + MAX_CONSECUTIVE_POLL_ERRORS


async def test_persistent_poll_errors_before_start_keep_started_false(
    handler: RecordingHandler,
) -> None:
    fake = FakeIppPrinter(job_script=[3], fail_get_job_with=0x0400)
    env = _Env(fake)
    pj = await env.job()
    await env.run(pj)
    assert handler.ended(UUID(pj.job.id)) == {
        "state": "failed",
        "started": False,
        "error_code": "interrupted",
    }
    assert env.ops("Get-Job-Attributes") == MAX_CONSECUTIVE_POLL_ERRORS


async def test_successful_poll_resets_the_error_count(handler: RecordingHandler) -> None:
    fake = FakeIppPrinter(job_script=[3])
    env = _Env(fake)
    pj = await env.job()
    original = fake._get_job
    polls = {"n": 0}
    good = {MAX_CONSECUTIVE_POLL_ERRORS, 2 * MAX_CONSECUTIVE_POLL_ERRORS}

    def mostly_bad(ops: dict[str, Any]) -> Any:
        polls["n"] += 1
        if polls["n"] == 2 * MAX_CONSECUTIVE_POLL_ERRORS + 1:
            fake.job_script = [9]
            return original(ops)
        if polls["n"] in good:
            return original(ops)
        return 0x0400, []  # client-error-bad-request

    fake._get_job = mostly_bad  # type: ignore[method-assign]
    await env.run(pj)
    assert (await env.row(pj)).state == DbJobState.DONE.value
