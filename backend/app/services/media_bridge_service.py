import asyncio
import base64
import contextlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from zoneinfo import ZoneInfo

from fastapi import WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect as websocket_connect

from app.actions.schedule_call_action import (
    SCHEDULE_CALL_FUNCTION_DEFINITION,
    ScheduleCallAction,
    get_schedule_call_action,
)
from app.core.errors import AppError
from app.core.logging import get_logger
from app.integrations.deepgram import DeepgramService, get_deepgram_service
from app.schemas.call import CallResponse
from app.schemas.scheduled_call import ScheduleCallActionRequest
from app.services.call_service import CallService, get_call_service
from app.utils.time import utc_now_iso

logger = get_logger(__name__)


@dataclass
class MediaSessionState:
    call_id: str | None = None
    stream_sid: str | None = None
    deepgram_request_id: str | None = None
    started: asyncio.Event = field(default_factory=asyncio.Event)
    settings_applied: asyncio.Event = field(default_factory=asyncio.Event)
    stop_requested: bool = False


class MediaBridgeService:
    audio_buffer_size_bytes = 10 * 160
    keepalive_interval_seconds = 5

    def __init__(
        self,
        deepgram_service: DeepgramService,
        call_service: CallService,
        schedule_call_action: ScheduleCallAction,
    ) -> None:
        self.deepgram_service = deepgram_service
        self.call_service = call_service
        self.schedule_call_action = schedule_call_action

    async def bridge_call(self, twilio_websocket: WebSocket) -> None:
        await twilio_websocket.accept()
        state = MediaSessionState()
        audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()

        twilio_receiver_task = asyncio.create_task(
            self._receive_from_twilio(twilio_websocket, state, audio_queue)
        )
        background_tasks: list[asyncio.Task] = [twilio_receiver_task]

        try:
            await asyncio.wait_for(state.started.wait(), timeout=15)
            if not state.call_id:
                raise AppError(
                    status_code=400,
                    code="call_id_missing",
                    message="Twilio media stream did not supply a call_id custom parameter.",
                )

            call_record = await self.call_service.get_call(state.call_id)
            agent_payload = self._build_agent_payload(call_record)
            if not self.deepgram_service.is_configured:
                raise AppError(
                    status_code=503,
                    code="deepgram_not_configured",
                    message="Deepgram is not configured for voice agent streaming.",
                )

            async with websocket_connect(
                self.deepgram_service.voice_agent_websocket_url,
                additional_headers={"Authorization": f"Token {self.deepgram_service.settings.deepgram_api_key_text}"},
                max_size=None,
            ) as deepgram_websocket:
                state.deepgram_request_id = await self._await_deepgram_welcome(deepgram_websocket)
                await deepgram_websocket.send(
                    json.dumps(self._build_settings_message(call_id=state.call_id, agent_payload=agent_payload))
                )
                await self._await_settings_applied(
                    deepgram_websocket=deepgram_websocket,
                    twilio_websocket=twilio_websocket,
                    state=state,
                    call_id=state.call_id,
                )
                await self.call_service.mark_call_in_progress(
                    state.call_id,
                    deepgram_request_id=state.deepgram_request_id,
                )

                deepgram_receiver_task = asyncio.create_task(
                    self._receive_from_deepgram(
                        deepgram_websocket=deepgram_websocket,
                        twilio_websocket=twilio_websocket,
                        state=state,
                        call_id=state.call_id,
                    )
                )
                deepgram_sender_task = asyncio.create_task(
                    self._send_audio_to_deepgram(
                        deepgram_websocket=deepgram_websocket,
                        audio_queue=audio_queue,
                        state=state,
                    )
                )
                keepalive_task = asyncio.create_task(
                    self._send_keepalive(deepgram_websocket, state)
                )
                background_tasks.extend([deepgram_receiver_task, deepgram_sender_task, keepalive_task])

                done, _ = await asyncio.wait(
                    [twilio_receiver_task, deepgram_receiver_task, deepgram_sender_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for task in done:
                    exception = task.exception()
                    if exception is not None:
                        raise exception

                state.stop_requested = True
                await audio_queue.put(None)

        except WebSocketDisconnect:
            logger.info("Twilio media WebSocket disconnected for call %s", state.call_id)
        except Exception as exc:
            logger.exception("Media bridge failure: %s", exc)
            if state.call_id:
                await self.call_service.mark_media_bridge_failure(state.call_id, str(exc))
        finally:
            state.stop_requested = True
            await audio_queue.put(None)
            for task in background_tasks:
                task.cancel()
            for task in background_tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            try:
                await twilio_websocket.close()
            except Exception:
                pass

    async def _receive_from_twilio(
        self,
        twilio_websocket: WebSocket,
        state: MediaSessionState,
        audio_queue: asyncio.Queue[bytes | None],
    ) -> None:
        inbound_audio_buffer = bytearray()

        try:
            while True:
                payload = json.loads(await twilio_websocket.receive_text())
                event_type = payload.get("event")

                if event_type == "connected":
                    continue

                if event_type == "start":
                    start_payload = payload.get("start", {})
                    state.stream_sid = start_payload.get("streamSid")
                    custom_parameters = start_payload.get("customParameters", {})
                    state.call_id = custom_parameters.get("call_id")
                    state.started.set()
                    if state.call_id:
                        await self.call_service.append_event(
                            state.call_id,
                            event_type="twilio_media_started",
                            message="Twilio opened the bidirectional media stream.",
                            payload={"stream_sid": state.stream_sid},
                        )
                    continue

                if event_type == "media":
                    media = payload.get("media", {})
                    if media.get("track") not in {None, "inbound"}:
                        continue
                    media_payload = media.get("payload")
                    if media_payload:
                        inbound_audio_buffer.extend(base64.b64decode(media_payload))
                        while len(inbound_audio_buffer) >= self.audio_buffer_size_bytes:
                            chunk = bytes(inbound_audio_buffer[: self.audio_buffer_size_bytes])
                            del inbound_audio_buffer[: self.audio_buffer_size_bytes]
                            await audio_queue.put(chunk)
                    continue

                if event_type == "dtmf" and state.call_id:
                    await self.call_service.append_event(
                        state.call_id,
                        event_type="twilio_dtmf",
                        message="DTMF received from the callee.",
                        payload=payload.get("dtmf", {}),
                    )
                    continue

                if event_type == "stop":
                    state.stop_requested = True
                    if inbound_audio_buffer:
                        await audio_queue.put(bytes(inbound_audio_buffer))
                        inbound_audio_buffer.clear()
                    if state.call_id:
                        await self.call_service.append_event(
                            state.call_id,
                            event_type="twilio_media_stopped",
                            message="Twilio closed the media stream.",
                            payload={"stream_sid": state.stream_sid},
                        )
                    break
        except WebSocketDisconnect:
            state.stop_requested = True
        finally:
            if inbound_audio_buffer:
                await audio_queue.put(bytes(inbound_audio_buffer))
            state.started.set()
            await audio_queue.put(None)

    async def _receive_from_deepgram(
        self,
        *,
        deepgram_websocket,
        twilio_websocket: WebSocket,
        state: MediaSessionState,
        call_id: str,
    ) -> None:
        async for message in deepgram_websocket:
            if isinstance(message, bytes):
                if state.stream_sid:
                    await twilio_websocket.send_json(
                        {
                            "event": "media",
                            "streamSid": state.stream_sid,
                            "media": {"payload": base64.b64encode(message).decode("ascii")},
                        }
                    )
                continue

            payload = json.loads(message)
            await self._handle_deepgram_text_event(
                payload=payload,
                deepgram_websocket=deepgram_websocket,
                twilio_websocket=twilio_websocket,
                state=state,
                call_id=call_id,
            )

    async def _send_audio_to_deepgram(
        self,
        *,
        deepgram_websocket,
        audio_queue: asyncio.Queue[bytes | None],
        state: MediaSessionState,
    ) -> None:
        while not state.stop_requested:
            audio_chunk = await audio_queue.get()
            if audio_chunk is None:
                break
            await deepgram_websocket.send(audio_chunk)

    async def _send_keepalive(self, deepgram_websocket, state: MediaSessionState) -> None:
        while not state.stop_requested:
            await asyncio.sleep(self.keepalive_interval_seconds)
            try:
                await deepgram_websocket.send(json.dumps({"type": "KeepAlive"}))
            except Exception:
                break

    @staticmethod
    def _build_settings_message(*, call_id: str, agent_payload: dict[str, object] | str) -> dict[str, object]:
        return {
            "type": "Settings",
            "tags": ["sparx", "twilio", call_id],
            "audio": {
                "input": {"encoding": "mulaw", "sample_rate": 8000},
                "output": {"encoding": "mulaw", "sample_rate": 8000, "container": "none"},
            },
            "agent": agent_payload,
        }

    async def _await_deepgram_welcome(self, deepgram_websocket) -> str | None:
        message = await deepgram_websocket.recv()
        if isinstance(message, bytes):
            raise AppError(
                status_code=502,
                code="deepgram_welcome_missing",
                message="Deepgram returned binary audio before the welcome handshake completed.",
            )

        payload = json.loads(message)
        if payload.get("type") != "Welcome":
            raise AppError(
                status_code=502,
                code="deepgram_welcome_missing",
                message="Deepgram did not return the expected welcome handshake message.",
                details={"response": payload},
            )
        return payload.get("request_id")

    async def _await_settings_applied(
        self,
        *,
        deepgram_websocket,
        twilio_websocket: WebSocket,
        state: MediaSessionState,
        call_id: str,
    ) -> None:
        while True:
            message = await deepgram_websocket.recv()
            if isinstance(message, bytes):
                continue

            payload = json.loads(message)
            if payload.get("type") == "SettingsApplied":
                state.settings_applied.set()
                return

            await self._handle_deepgram_text_event(
                payload=payload,
                deepgram_websocket=deepgram_websocket,
                twilio_websocket=twilio_websocket,
                state=state,
                call_id=call_id,
                fail_on_error=True,
            )

    async def _handle_deepgram_text_event(
        self,
        *,
        payload: dict[str, object],
        deepgram_websocket,
        twilio_websocket: WebSocket,
        state: MediaSessionState,
        call_id: str,
        fail_on_error: bool = False,
    ) -> None:
        message_type = str(payload.get("type") or "")

        if message_type == "ConversationText":
            await self.call_service.append_transcript_entry(call_id, payload)
            await self.call_service.append_event(
                call_id,
                event_type="conversation_text",
                message="Deepgram emitted conversation text.",
                payload=payload,
            )
            return

        if message_type == "FunctionCallRequest":
            await self._handle_function_call_request(
                payload=payload,
                deepgram_websocket=deepgram_websocket,
                call_id=call_id,
            )
            return

        if message_type == "UserStartedSpeaking" and state.stream_sid:
            await twilio_websocket.send_json({"event": "clear", "streamSid": state.stream_sid})
            return

        if message_type in {"Error", "Warning"}:
            await self.call_service.append_event(
                call_id,
                event_type=message_type.lower(),
                message=f"Deepgram returned a {message_type.lower()} event.",
                payload=payload,
            )
            if fail_on_error and message_type == "Error":
                raise AppError(
                    status_code=502,
                    code="deepgram_session_setup_failed",
                    message=self._extract_deepgram_error_message(payload),
                    details={"response": payload},
                )

    async def _handle_function_call_request(
        self,
        *,
        payload: dict[str, object],
        deepgram_websocket,
        call_id: str,
    ) -> None:
        functions = payload.get("functions")
        if not isinstance(functions, list):
            await self.call_service.append_event(
                call_id,
                event_type="function_call_error",
                message="Deepgram function call request did not include a functions array.",
                payload=payload,
            )
            return

        for function_call in functions:
            if not isinstance(function_call, dict):
                continue
            response = await self._execute_function_call(function_call=function_call, call_id=call_id)
            await deepgram_websocket.send(json.dumps(response, default=str))

    async def _execute_function_call(
        self,
        *,
        function_call: dict[str, object],
        call_id: str,
    ) -> dict[str, object]:
        function_name = str(function_call.get("name") or "")
        function_id = str(function_call.get("id") or "")

        if function_name != ScheduleCallAction.name:
            content = {
                "error": "unsupported_function",
                "message": f"Function '{function_name}' is not available in SPARX.",
            }
            await self.call_service.append_event(
                call_id,
                event_type="function_call_unsupported",
                message=f"Deepgram requested unsupported function '{function_name}'.",
                payload={"function_id": function_id, "function_name": function_name},
            )
            return self._build_function_response(function_id=function_id, function_name=function_name, content=content)

        try:
            arguments = self._parse_function_arguments(function_call.get("arguments"))
            call_record = await self.call_service.get_call(call_id)
            enriched_arguments = dict(arguments)
            enriched_arguments["name"] = call_record.lead_name
            enriched_arguments["phone"] = call_record.phone
            enriched_arguments["call_id"] = call_record.call_id
            enriched_arguments["call_type"] = call_record.call_type
            enriched_arguments["campaign_id"] = call_record.campaign_id
            enriched_arguments["contact_id"] = call_record.contact_id
            if not enriched_arguments.get("timezone"):
                enriched_arguments["timezone"] = self.schedule_call_action.settings.callback_default_timezone
            enriched_arguments["scheduling_policy"] = deepcopy(call_record.metadata.get("scheduling_policy", {}))
            action_payload = ScheduleCallActionRequest.model_validate(enriched_arguments)
            self._validate_scheduling_policy(call_record, action_payload)
            result = await self.schedule_call_action.execute(action_payload)
            content = self._build_schedule_call_action_content(result)
            await self.call_service.append_event(
                call_id,
                event_type="schedule_call_action_completed",
                message="The voice agent created a scheduled call through schedule_call_action.",
                payload={
                    "function_id": function_id,
                    "scheduled_call_id": result.scheduled_call_id,
                    "type": result.type,
                    "scheduled_time": result.scheduled_time.isoformat(),
                    "communication_mode": result.communication_mode,
                    "attendee_email": result.attendee_email,
                    "google_meet_link": result.google_meet_link,
                    "invite_email_status": result.invite_email_status,
                },
            )
            return self._build_function_response(
                function_id=function_id,
                function_name=function_name,
                content=content,
            )
        except Exception as exc:
            content = {
                "error": "schedule_call_action_failed",
                "message": str(exc),
            }
            await self.call_service.append_event(
                call_id,
                event_type="schedule_call_action_failed",
                message="The voice agent could not create a scheduled call through schedule_call_action.",
                payload={
                    "function_id": function_id,
                    "error": str(exc),
                },
            )
            return self._build_function_response(
                function_id=function_id,
                function_name=function_name,
                content=content,
            )

    @staticmethod
    def _parse_function_arguments(arguments: object) -> dict[str, object]:
        if arguments is None:
            return {}
        if isinstance(arguments, dict):
            return arguments
        if isinstance(arguments, str):
            parsed = json.loads(arguments or "{}")
            if isinstance(parsed, dict):
                return parsed
        raise ValueError("Function arguments must be a JSON object.")

    @staticmethod
    def _build_function_response(
        *,
        function_id: str,
        function_name: str,
        content: dict[str, object],
    ) -> dict[str, object]:
        return {
            "type": "FunctionCallResponse",
            "id": function_id,
            "name": function_name,
            "content": json.dumps(content, default=str),
        }

    @staticmethod
    def _build_schedule_call_action_content(result: object) -> dict[str, object]:
        communication_mode = getattr(result, "communication_mode", "phone_call")
        invite_status = getattr(result, "invite_email_status", "not_required")
        scheduled_time = getattr(result, "scheduled_time", None)
        content = {
            "scheduled_call_id": getattr(result, "scheduled_call_id", None),
            "type": getattr(result, "type", None),
            "status": getattr(result, "status", None),
            "scheduled_time": scheduled_time.isoformat() if scheduled_time else None,
            "timezone": getattr(result, "timezone", None),
            "communication_mode": communication_mode,
            "attendee_email": getattr(result, "attendee_email", None),
            "invite_email_status": invite_status,
        }
        if communication_mode == "google_meet":
            content["message_for_customer"] = (
                "The Google Meet calendar invite has been sent. Ask whether they received it. "
                "Do not read the Meet URL or any backend fields aloud."
                if invite_status == "sent"
                else (
                    "The Google Meet invite could not be sent right now. Tell the customer to check later, "
                    "and explain that a normal executive phone call is also scheduled as fallback."
                )
            )
        return content

    @staticmethod
    def _extract_deepgram_error_message(payload: dict[str, object]) -> str:
        return (
            str(payload.get("description") or "").strip()
            or str(payload.get("message") or "").strip()
            or "Deepgram returned an error while starting the voice agent session."
        )

    def _validate_scheduling_policy(
        self,
        call_record: CallResponse,
        payload: ScheduleCallActionRequest,
    ) -> None:
        policy = call_record.metadata.get("scheduling_policy")
        if not isinstance(policy, dict):
            return

        flow_policy = policy.get(payload.type)
        if not isinstance(flow_policy, dict):
            return

        scheduled_local_date = self._scheduled_local_date(payload)
        max_date_value = flow_policy.get("max_scheduled_date")
        if max_date_value:
            max_date = date.fromisoformat(str(max_date_value))
            if scheduled_local_date > max_date:
                raise AppError(
                    status_code=400,
                    code="schedule_outside_allowed_window",
                    message=(
                        f"The requested {payload.type.replace('_', ' ')} date is outside the allowed scheduling "
                        f"window. Offer a date on or before {max_date.isoformat()}."
                    ),
                )

        allowed_weekdays = flow_policy.get("allowed_weekdays")
        if payload.type == "executive_callback" and isinstance(allowed_weekdays, list) and allowed_weekdays:
            normalized_weekdays = {int(weekday) for weekday in allowed_weekdays}
            if scheduled_local_date.weekday() not in normalized_weekdays:
                raise AppError(
                    status_code=400,
                    code="schedule_outside_working_days",
                    message=(
                        "The requested executive callback date is outside the allowed working days. "
                        f"Offer one of these working days instead: {self._format_weekdays(sorted(normalized_weekdays))}."
                    ),
                )

    def _scheduled_local_date(self, payload: ScheduleCallActionRequest) -> date:
        timezone_name = payload.timezone or self.schedule_call_action.settings.callback_default_timezone
        target_timezone = ZoneInfo(timezone_name)
        scheduled_time = payload.scheduled_time
        if scheduled_time.tzinfo is None:
            scheduled_time = scheduled_time.replace(tzinfo=target_timezone)
        else:
            scheduled_time = scheduled_time.astimezone(target_timezone)
        return scheduled_time.date()

    @staticmethod
    def _format_weekdays(weekdays: list[int]) -> str:
        weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        return ", ".join(weekday_names[weekday] for weekday in weekdays if 0 <= weekday <= 6)

    @staticmethod
    def _build_agent_payload(call_record: CallResponse) -> dict[str, object] | str:
        metadata = deepcopy(call_record.metadata)
        campaign_context = metadata.get("campaign_context") or {}
        scheduling_policy = metadata.get("scheduling_policy") or {}
        scheduling_policy_text = MediaBridgeService._format_scheduling_policy_for_prompt(scheduling_policy)
        call_brief_lines = [
            "Call context for the outbound conversation.",
            f"Lead Name: {call_record.lead_name}",
            f"Lead Phone Number: {call_record.phone}",
            f"Company: {call_record.company or 'Not provided'}",
            f"City: {call_record.city or 'Not provided'}",
            f"Role: {call_record.role or 'Not provided'}",
            f"Interest: {call_record.interest or 'Not provided'}",
            f"Call Objective: {call_record.call_objective}",
            f"Language Preference: {call_record.language}",
            f"Priority: {call_record.priority}",
            f"Additional Context: {call_record.additional_context or 'None'}",
            f"Scheduling Limits: {scheduling_policy_text}",
            f"Current System Time: {utc_now_iso()}",
        ]

        if campaign_context:
            campaign_instructions = campaign_context.get("notes") or call_record.additional_context
            call_brief_lines.extend(
                [
                    f"Campaign Name: {campaign_context.get('campaign_name') or 'Not provided'}",
                    f"Campaign Type: {campaign_context.get('campaign_type') or 'Not provided'}",
                    f"Campaign Instructions: {campaign_instructions or 'None'}",
                ]
            )

        call_brief_lines.append(
            "Use this context to guide the conversation and do not read the full brief verbatim unless it is useful."
        )
        call_brief = "\n".join(call_brief_lines)

        agent_configuration = metadata.get("agent_configuration")
        if not agent_configuration:
            return call_record.deepgram_agent_id or call_record.agent_id

        agent_payload = deepcopy(agent_configuration)
        think = agent_payload.setdefault("think", {})
        functions = think.setdefault("functions", [])
        if not any(function.get("name") == ScheduleCallAction.name for function in functions if isinstance(function, dict)):
            functions.append(deepcopy(SCHEDULE_CALL_FUNCTION_DEFINITION))

        prompt = str(think.get("prompt") or "")
        if ScheduleCallAction.name not in prompt:
            think["prompt"] = (
                f"{prompt}\n\n"
                "When a customer asks for a callback, says this is not a good time, or requests to speak "
                "with a real person, collect a clear date and time if needed. After the customer confirms "
                f"the time, call {ScheduleCallAction.name}. Use ai_callback for automated AI callbacks "
                "and executive_callback for human executive or sales-team requests. For executive_callback, "
                "you must first ask exactly which communication mode they prefer: a normal phone call on "
                "this number, or a Google Meet link sent by email. Do not ask 'is this number okay' until "
                "after they choose phone_call. If they choose a normal call, use communication_mode "
                "phone_call. If they choose Google Meet, ask them to spell their Gmail address slowly. "
                "Normalize spoken words like 'at' and 'dot'. Then repeat the complete normalized email "
                "in a confirmation-friendly way: read each word/segment and also spell every character, "
                "for example 'g a h t o r i a y u s h two five at gmail dot com'. Ask 'Is that correct?' "
                "Wait for a clear yes before calling the action. Only after that confirmation, call "
                f"{ScheduleCallAction.name} with communication_mode google_meet, attendee_email, and "
                "attendee_email_confirmed true. If the customer has not confirmed the spelled email, do "
                "not call the action. After a Google Meet action succeeds, ask if they received the invite. "
                "Do not read any raw URL, JSON, HTTPS link, event id, backend field, or function result aloud. "
                "If they say no, tell them it can take a few minutes, ask them to check spam/all mail, and "
                "explain that a normal executive call is also scheduled as fallback. Do not rely "
                "on a spoken promise alone for scheduling. You already know the current call's phone number "
                "from the call context, so do not ask the customer for their number. Instead, confirm the "
                "existing number naturally, for example: 'Is this number okay for our executive to call at "
                "3:30 PM?' If the requested time is outside the scheduling limits in the call context, do "
                "not call the action. Politely explain that the time is outside the allowed window and ask "
                "for another date or time that fits the listed limits."
            ).strip()
        else:
            think["prompt"] = prompt

        if campaign_context:
            campaign_instructions = str(campaign_context.get("notes") or call_record.additional_context or "").strip()
            if campaign_instructions:
                think["prompt"] = (
                    f"{think['prompt']}\n\n"
                    "Campaign-specific instructions from the operator dashboard:\n"
                    f"{campaign_instructions}\n\n"
                    "For this campaign call, follow the campaign-specific instructions above when they differ "
                    "from the default agent prompt, while still staying truthful, concise, and compliant."
                ).strip()

        context = agent_payload.setdefault("context", {})
        messages = context.setdefault("messages", [])
        messages.append({"type": "History", "role": "user", "content": call_brief})
        return agent_payload

    @staticmethod
    def _format_scheduling_policy_for_prompt(policy: object) -> str:
        if not isinstance(policy, dict) or not policy:
            return "No custom scheduling limits were configured."

        ai_policy = policy.get("ai_callback") if isinstance(policy.get("ai_callback"), dict) else {}
        executive_policy = (
            policy.get("executive_callback")
            if isinstance(policy.get("executive_callback"), dict)
            else {}
        )
        ai_max_date = ai_policy.get("max_scheduled_date") or "No maximum date"
        executive_max_date = executive_policy.get("max_scheduled_date") or "No maximum date"
        executive_weekdays = executive_policy.get("allowed_weekdays")
        weekday_text = "Any day"
        if isinstance(executive_weekdays, list) and executive_weekdays:
            weekday_text = MediaBridgeService._format_weekdays([int(day) for day in executive_weekdays])
        return (
            f"AI callbacks may be scheduled on any day until {ai_max_date}. "
            f"Executive callbacks may be scheduled until {executive_max_date}; allowed working days: {weekday_text}."
        )


@lru_cache
def get_media_bridge_service() -> MediaBridgeService:
    return MediaBridgeService(
        deepgram_service=get_deepgram_service(),
        call_service=get_call_service(),
        schedule_call_action=get_schedule_call_action(),
    )
