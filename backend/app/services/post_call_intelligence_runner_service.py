import asyncio
from functools import lru_cache

from starlette.concurrency import run_in_threadpool

from app.config.settings import Settings, get_settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.repositories.call_repository import CallRepository, get_call_repository
from app.schemas.intelligence import SummaryDetailResponse
from app.services.post_call_intelligence_service import (
    PostCallIntelligenceService,
    get_post_call_intelligence_service,
)
from app.utils.time import coerce_utc, utc_now, utc_now_iso

logger = get_logger(__name__)


class PostCallIntelligenceRunnerService:
    active_statuses = {"queued", "processing"}

    def __init__(
        self,
        *,
        settings: Settings,
        call_repository: CallRepository,
        intelligence_service: PostCallIntelligenceService,
    ) -> None:
        self.settings = settings
        self.call_repository = call_repository
        self.intelligence_service = intelligence_service
        self._loop_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._last_cycle_started_at: str | None = None
        self._last_cycle_completed_at: str | None = None
        self._last_error: str | None = None
        self._recovered_jobs = 0

    async def start(self) -> None:
        if self._loop_task and not self._loop_task.done():
            return
        self._stop_event.clear()
        try:
            await self._recover_incomplete_jobs()
        except AppError as exc:
            if exc.code != "firestore_not_configured":
                raise
        except Exception as exc:
            # Firestore transient failures (for example quota exhaustion) should not block API startup.
            self._last_error = str(exc)
            logger.warning("Skipping AI recovery on startup due to datastore error: %s", exc)
        self._loop_task = asyncio.create_task(self._scheduler_loop(), name="post-call-intelligence-runner")
        logger.info(
            "Post-call intelligence runner started | max_parallel_jobs=%s | dispatch_interval_seconds=%s",
            self.settings.ai_max_parallel_jobs,
            self.settings.ai_dispatch_interval_seconds,
        )

    async def stop(self) -> None:
        if self._loop_task is None:
            return
        self._stop_event.set()
        self._wake_event.set()
        self._loop_task.cancel()
        for task in self._active_tasks.values():
            task.cancel()
        try:
            await self._loop_task
        except asyncio.CancelledError:
            pass
        self._loop_task = None
        self._active_tasks.clear()
        logger.info("Post-call intelligence runner stopped")

    def kick(self) -> None:
        self._wake_event.set()

    async def schedule_call_processing(self, call_id: str, *, force: bool = False) -> None:
        if call_id in self._active_tasks:
            return
        call_document = await run_in_threadpool(self.call_repository.get_call, call_id)
        if not force and not self.intelligence_service.should_auto_process(call_document):
            return
        if call_document.ai_processing_status in {"queued", "processing"}:
            return
        if call_document.processed_by_ai and not force:
            return

        await run_in_threadpool(
            self.call_repository.update_call,
            call_id,
            {
                "ai_processing_status": "queued",
                "ai_error": None,
            },
        )
        self.kick()

    async def process_now(self, call_id: str, *, force: bool = False) -> SummaryDetailResponse:
        if call_id in self._active_tasks:
            return await self._active_tasks[call_id]
        await self.schedule_call_processing(call_id, force=force)
        return await self._run_processing(call_id)

    async def _scheduler_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._last_cycle_started_at = utc_now_iso()
                await self._dispatch_queued_calls()
                self._last_cycle_completed_at = utc_now_iso()
                self._last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = str(exc)
                logger.exception("Post-call intelligence scheduler loop failed: %s", exc)

            self._wake_event.clear()
            try:
                await asyncio.wait_for(
                    self._wake_event.wait(),
                    timeout=self.settings.ai_dispatch_interval_seconds,
                )
            except asyncio.TimeoutError:
                continue

    async def _dispatch_queued_calls(self) -> None:
        try:
            calls = await run_in_threadpool(self.call_repository.list_calls)
        except AppError as exc:
            if exc.code == "firestore_not_configured":
                return
            raise
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("Skipping AI queue dispatch cycle due to datastore error: %s", exc)
            return
        queued_calls = [call for call in calls if call.ai_processing_status == "queued"]
        queued_calls.sort(key=lambda call: coerce_utc(call.ended_at or call.created_at or utc_now()))

        available_slots = max(self.settings.ai_max_parallel_jobs - len(self._active_tasks), 0)
        for call_document in queued_calls[:available_slots]:
            self._launch_processing(call_document.call_id)
        await self._dispatch_pending_meeting_invites(calls)

    async def _dispatch_pending_meeting_invites(self, calls) -> None:
        pending_calls = [
            call
            for call in calls
            if self.intelligence_service._needs_meeting_invite(call)
        ]
        pending_calls.sort(key=lambda call: coerce_utc(call.updated_at or call.ended_at or call.created_at or utc_now()))
        for call_document in pending_calls[:5]:
            try:
                await self.intelligence_service.ensure_meeting_invite(call_document.call_id)
            except Exception as exc:
                logger.warning(
                    "Unable to auto-send meeting invite for call %s: %s",
                    call_document.call_id,
                    exc,
                )

    def _launch_processing(self, call_id: str) -> None:
        if call_id in self._active_tasks:
            return

        task = asyncio.create_task(self._run_processing(call_id), name=f"ai-process-{call_id}")
        self._active_tasks[call_id] = task

        def _cleanup(finished_task: asyncio.Task) -> None:
            self._active_tasks.pop(call_id, None)
            try:
                finished_task.result()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.exception("Post-call intelligence task failed for %s: %s", call_id, exc)

        task.add_done_callback(_cleanup)

    async def _run_processing(self, call_id: str) -> SummaryDetailResponse:
        await run_in_threadpool(
            self.call_repository.update_call,
            call_id,
            {
                "ai_processing_status": "processing",
                "ai_error": None,
            },
        )
        try:
            return await self.intelligence_service.process_call(call_id)
        except AppError as exc:
            await run_in_threadpool(
                self.call_repository.update_call,
                call_id,
                {
                    "ai_processing_status": "failed",
                    "ai_error": exc.message,
                },
            )
            raise
        except Exception as exc:
            await run_in_threadpool(
                self.call_repository.update_call,
                call_id,
                {
                    "ai_processing_status": "failed",
                    "ai_error": str(exc),
                },
            )
            raise

    async def _recover_incomplete_jobs(self) -> None:
        try:
            calls = await run_in_threadpool(self.call_repository.list_calls)
        except AppError:
            raise
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("Unable to recover AI jobs during startup due to datastore error: %s", exc)
            return
        for call_document in calls:
            if call_document.ai_processing_status == "processing":
                await run_in_threadpool(
                    self.call_repository.update_call,
                    call_document.call_id,
                    {
                        "ai_processing_status": "queued",
                        "ai_error": "Recovered after application restart.",
                    },
                )
                self._recovered_jobs += 1

    def get_diagnostics(self) -> dict[str, object]:
        if not self.settings.resolved_run_ai_background_runner:
            return {
                "status": "disabled",
                "loop_running": False,
                "active_items": 0,
                "last_cycle_started_at": self._last_cycle_started_at,
                "last_cycle_completed_at": self._last_cycle_completed_at,
                "recovered_items": self._recovered_jobs,
                "last_error": None,
            }
        status = "healthy" if self._loop_task and not self._loop_task.done() and self._last_error is None else "degraded"
        return {
            "status": status,
            "loop_running": bool(self._loop_task and not self._loop_task.done()),
            "active_items": len(self._active_tasks),
            "last_cycle_started_at": self._last_cycle_started_at,
            "last_cycle_completed_at": self._last_cycle_completed_at,
            "recovered_items": self._recovered_jobs,
            "last_error": self._last_error,
        }


@lru_cache
def get_post_call_intelligence_runner_service() -> PostCallIntelligenceRunnerService:
    return PostCallIntelligenceRunnerService(
        settings=get_settings(),
        call_repository=get_call_repository(),
        intelligence_service=get_post_call_intelligence_service(),
    )
