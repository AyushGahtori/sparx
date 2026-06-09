import asyncio
from functools import lru_cache

from starlette.concurrency import run_in_threadpool

from app.config.settings import Settings, get_settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.models.firestore_documents import CallbackDocument
from app.repositories.callback_repository import CallbackRepository, get_callback_repository
from app.schemas.callback import CallbackResponse
from app.services.call_service import CallService, get_call_service
from app.services.callback_sync_service import CallbackSyncService, get_callback_sync_service
from app.utils.time import coerce_utc, format_uptime, utc_now, utc_now_iso

logger = get_logger(__name__)


class CallbackRunnerService:
    active_statuses = {"queued", "in_progress"}
    runnable_statuses = {"scheduled", "rescheduled"}

    def __init__(
        self,
        *,
        settings: Settings,
        callback_repository: CallbackRepository,
        call_service: CallService,
        sync_service: CallbackSyncService,
    ) -> None:
        self.settings = settings
        self.callback_repository = callback_repository
        self.call_service = call_service
        self.sync_service = sync_service
        self._loop_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._started_at = utc_now()
        self._last_cycle_started_at: str | None = None
        self._last_cycle_completed_at: str | None = None
        self._last_error: str | None = None
        self._recovered_callbacks = 0

    async def start(self) -> None:
        if self._loop_task and not self._loop_task.done():
            return
        self._stop_event.clear()
        try:
            await self._recover_stale_callbacks()
        except AppError as exc:
            if exc.code != "firestore_not_configured":
                raise
        self._loop_task = asyncio.create_task(self._scheduler_loop(), name="callback-runner")
        logger.info(
            "Callback runner started | max_parallel_calls=%s | dispatch_interval_seconds=%s",
            self.settings.callback_max_parallel_calls,
            self.settings.callback_dispatch_interval_seconds,
        )

    async def stop(self) -> None:
        if self._loop_task is None:
            return
        self._stop_event.set()
        self._wake_event.set()
        self._loop_task.cancel()
        try:
            await self._loop_task
        except asyncio.CancelledError:
            pass
        self._loop_task = None
        logger.info("Callback runner stopped")

    def kick(self) -> None:
        self._wake_event.set()

    async def execute_callback_now(self, callback_id: str) -> CallbackResponse:
        callback_document = await run_in_threadpool(self.callback_repository.get_callback, callback_id)
        if callback_document.status in {"completed", "cancelled", "missed"}:
            raise AppError(
                status_code=409,
                code="callback_not_executable",
                message=f"Callback '{callback_document.callback_id}' cannot be executed from status '{callback_document.status}'.",
            )

        await run_in_threadpool(
            self.callback_repository.update_callback,
            callback_document.callback_id,
            {
                "status": "queued",
                "normalized_callback_time": utc_now(),
                "next_retry_time": utc_now(),
            },
        )
        await self.sync_service.append_event(
            callback_document.callback_id,
            event_type="callback_execution_requested",
            message="Callback was queued for immediate execution.",
            payload={"source": "api"},
        )
        await self._launch_callback(callback_id)
        refreshed_callback = await run_in_threadpool(self.callback_repository.get_callback, callback_id)
        return self._to_response(refreshed_callback)

    async def _scheduler_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._last_cycle_started_at = utc_now_iso()
                await self._process_due_callbacks()
                self._last_cycle_completed_at = utc_now_iso()
                self._last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = str(exc)
                logger.exception("Callback scheduler loop failed: %s", exc)

            self._wake_event.clear()
            try:
                await asyncio.wait_for(
                    self._wake_event.wait(),
                    timeout=self.settings.callback_dispatch_interval_seconds,
                )
            except asyncio.TimeoutError:
                continue

    async def _process_due_callbacks(self) -> None:
        try:
            callbacks = await run_in_threadpool(self.callback_repository.list_callbacks)
        except AppError as exc:
            if exc.code == "firestore_not_configured":
                return
            raise

        active_count = len([callback for callback in callbacks if callback.status in self.active_statuses])
        remaining_capacity = max(self.settings.callback_max_parallel_calls - active_count, 0)
        if remaining_capacity == 0:
            return

        now = utc_now()
        due_callbacks = [
            callback
            for callback in callbacks
            if callback.status in self.runnable_statuses
            and coerce_utc(callback.normalized_callback_time) <= now
        ]
        due_callbacks.sort(key=self._callback_sort_key)

        for callback_document in due_callbacks[:remaining_capacity]:
            await self._launch_callback(callback_document.callback_id)

    async def _launch_callback(self, callback_id: str) -> None:
        callback_document = await run_in_threadpool(self.callback_repository.get_callback, callback_id)
        if callback_document.status in {"completed", "cancelled", "missed"}:
            return

        await run_in_threadpool(
            self.callback_repository.update_callback,
            callback_document.callback_id,
            {
                "status": "queued",
                "last_attempted_at": utc_now(),
            },
        )
        await self.sync_service.append_event(
            callback_document.callback_id,
            event_type="callback_queued",
            message="Callback entered the execution queue.",
            payload={"priority": callback_document.priority},
        )

        try:
            await self.call_service.start_callback_call(callback_document)
        except Exception as exc:
            logger.exception("Callback execution failed for %s: %s", callback_document.callback_id, exc)
            await run_in_threadpool(
                self.callback_repository.update_callback,
                callback_document.callback_id,
                {"status": "failed"},
            )
            await self.sync_service.append_event(
                callback_document.callback_id,
                event_type="callback_execution_failed",
                message="Callback execution failed before a call could be started.",
                payload={"error": str(exc)},
            )

    async def _recover_stale_callbacks(self) -> None:
        callbacks = await run_in_threadpool(self.callback_repository.list_callbacks)
        now = utc_now()
        recovered = 0

        for callback_document in callbacks:
            if callback_document.status not in self.active_statuses:
                continue

            last_attempted_at = callback_document.last_attempted_at or callback_document.updated_at or callback_document.created_at
            if last_attempted_at is None:
                continue

            age_seconds = (now - coerce_utc(last_attempted_at)).total_seconds()
            if age_seconds < self.settings.queue_recovery_stale_seconds:
                continue

            recovered += 1
            await run_in_threadpool(
                self.callback_repository.update_callback,
                callback_document.callback_id,
                {
                    "status": "rescheduled",
                    "normalized_callback_time": now,
                    "next_retry_time": now,
                },
            )
            await self.sync_service.append_event(
                callback_document.callback_id,
                event_type="callback_recovered_after_restart",
                message="Recovered a stale callback queue item after application restart.",
                payload={"previous_status": callback_document.status},
            )

        self._recovered_callbacks += recovered

    def get_diagnostics(self) -> dict[str, object]:
        if not self.settings.resolved_run_callback_dispatch_runner:
            return {
                "status": "disabled",
                "loop_running": False,
                "active_items": 0,
                "last_cycle_started_at": self._last_cycle_started_at,
                "last_cycle_completed_at": self._last_cycle_completed_at,
                "recovered_items": self._recovered_callbacks,
                "last_error": None,
                "uptime": format_uptime(self._started_at),
            }
        active_items = 0
        if self._loop_task and not self._loop_task.done():
            active_items = 1
        status = "healthy" if self._loop_task and not self._loop_task.done() and self._last_error is None else "degraded"
        return {
            "status": status,
            "loop_running": bool(self._loop_task and not self._loop_task.done()),
            "active_items": active_items,
            "last_cycle_started_at": self._last_cycle_started_at,
            "last_cycle_completed_at": self._last_cycle_completed_at,
            "recovered_items": self._recovered_callbacks,
            "last_error": self._last_error,
            "uptime": format_uptime(self._started_at),
        }

    @staticmethod
    def _callback_sort_key(callback_document: CallbackDocument) -> tuple[int, object, object]:
        priority_order = {"high": 0, "medium": 1, "low": 2}
        return (
            priority_order[callback_document.priority],
            coerce_utc(callback_document.normalized_callback_time),
            coerce_utc(callback_document.created_at or utc_now()),
        )

    @staticmethod
    def _to_response(callback_document: CallbackDocument) -> CallbackResponse:
        payload = callback_document.model_dump()
        payload.pop("id", None)
        return CallbackResponse.model_validate(payload)


@lru_cache
def get_callback_runner_service() -> CallbackRunnerService:
    return CallbackRunnerService(
        settings=get_settings(),
        callback_repository=get_callback_repository(),
        call_service=get_call_service(),
        sync_service=get_callback_sync_service(),
    )
