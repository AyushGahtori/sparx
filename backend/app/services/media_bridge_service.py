import asyncio
import base64
import contextlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from functools import lru_cache

from fastapi import WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect as websocket_connect

from app.core.errors import AppError
from app.core.logging import get_logger
from app.integrations.deepgram import DeepgramService, get_deepgram_service
from app.schemas.call import CallResponse
from app.services.call_service import CallService, get_call_service
from app.utils.lead_email import resolve_lead_email

logger = get_logger(__name__)


@dataclass
class MediaSessionState:
    call_id: str | None = None
    stream_sid: str | None = None
    deepgram_request_id: str | None = None
    started: asyncio.Event = field(default_factory=asyncio.Event)
    settings_applied: asyncio.Event = field(default_factory=asyncio.Event)
    stop_requested: bool = False
    auto_hangup_scheduled: bool = False


class MediaBridgeService:
    audio_buffer_size_bytes = 10 * 160
    keepalive_interval_seconds = 5
    auto_hangup_delay_seconds = 3.0
    closing_agent_patterns = (
        re.compile(r"\b(thank you|thanks) for (your time|speaking with me|talking with me)\s*[.!?]*$"),
        re.compile(r"\b(thank you|thanks).{0,80}\b(bye|goodbye|take care|have a (great|nice|good) day)\b"),
        re.compile(r"\b(bye|goodbye|take care)\s*[.!?]*$"),
        re.compile(r"\b(have a (great|nice|good) day|talk to you soon|speak with you soon)\s*[.!?]*$"),
        re.compile(r"\b(i'?ll|i will|we'?ll|we will) (end|close|disconnect) (the|this) call\b"),
        re.compile(r"\b(the meeting is (booked|scheduled|confirmed)).{0,80}\b(thank you|thanks|bye|goodbye)\b"),
    )

    def __init__(self, deepgram_service: DeepgramService, call_service: CallService) -> None:
        self.deepgram_service = deepgram_service
        self.call_service = call_service
        self._auto_hangup_tasks: set[asyncio.Task] = set()

    async def bridge_call(self, twilio_websocket: WebSocket) -> None:
        await twilio_websocket.accept()
        state = MediaSessionState()
        audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()

        twilio_receiver_task = asyncio.create_task(
            self._receive_from_twilio(twilio_websocket, state, audio_queue),
            name="twilio_receiver",
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
                    ),
                    name="deepgram_receiver",
                )
                deepgram_sender_task = asyncio.create_task(
                    self._send_audio_to_deepgram(
                        deepgram_websocket=deepgram_websocket,
                        audio_queue=audio_queue,
                        state=state,
                    ),
                    name="deepgram_sender",
                )
                keepalive_task = asyncio.create_task(
                    self._send_keepalive(deepgram_websocket, state),
                    name="deepgram_keepalive",
                )
                background_tasks.extend([deepgram_receiver_task, deepgram_sender_task, keepalive_task])

                done, _ = await asyncio.wait(
                    [twilio_receiver_task, deepgram_receiver_task, deepgram_sender_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for task in done:
                    task_name = task.get_name()
                    exception = task.exception()
                    await self.call_service.append_event(
                        state.call_id,
                        event_type="media_bridge_task_completed",
                        message=f"The {task_name} task ended the media bridge session.",
                        payload={"task": task_name, "had_exception": exception is not None},
                    )
                    logger.info("Media bridge task completed for call %s: %s", state.call_id, task_name)
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
                twilio_websocket=twilio_websocket,
                state=state,
                call_id=call_id,
                fail_on_error=True,
            )

    async def _handle_deepgram_text_event(
        self,
        *,
        payload: dict[str, object],
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
            if self._is_closing_agent_message(payload) and not state.auto_hangup_scheduled:
                state.auto_hangup_scheduled = True
                task = asyncio.create_task(
                    self._complete_call_after_agent_close(
                        call_id=call_id,
                        reason=str(payload.get("content") or "").strip(),
                    )
                )
                self._auto_hangup_tasks.add(task)
                task.add_done_callback(self._auto_hangup_tasks.discard)
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

    @staticmethod
    def _extract_deepgram_error_message(payload: dict[str, object]) -> str:
        return (
            str(payload.get("description") or "").strip()
            or str(payload.get("message") or "").strip()
            or "Deepgram returned an error while starting the voice agent session."
        )

    async def _complete_call_after_agent_close(self, *, call_id: str, reason: str) -> None:
        await asyncio.sleep(self.auto_hangup_delay_seconds)
        try:
            await self.call_service.complete_active_call(call_id, reason=reason)
        except Exception as exc:
            logger.warning("Unable to auto-complete call %s after closing phrase: %s", call_id, exc)

    @classmethod
    def _is_closing_agent_message(cls, payload: dict[str, object]) -> bool:
        role = str(payload.get("role") or "").strip().lower()
        if role != "assistant":
            return False

        content = " ".join(str(payload.get("content") or "").strip().lower().split())
        if not content:
            return False

        explicit_closing_phrases = (
            "i will end the call now",
            "i'll end the call now",
            "i am ending the call now",
            "you can disconnect now",
        )
        short_closing_phrases = {"thank you", "thanks", "thank you so much", "thanks so much"}
        return content.strip(".!?") in short_closing_phrases or any(
            phrase in content for phrase in explicit_closing_phrases
        ) or any(
            pattern.search(content) for pattern in cls.closing_agent_patterns
        )

    @staticmethod
    def _build_agent_payload(call_record: CallResponse) -> dict[str, object] | str:
        metadata = deepcopy(call_record.metadata)
        campaign_context = metadata.get("campaign_context") or {}
        product_brief = campaign_context.get("product_brief") or {}
        lead_profile = {
            **(metadata.get("lead_profile") or {}),
            **(campaign_context.get("lead_profile") or {}),
        }
        saved_email = resolve_lead_email(direct_email=call_record.email, metadata=metadata)
        callback_context = metadata.get("callback_context") or {}
        conversation_state = callback_context.get("conversation_state") or metadata.get("conversation_state") or {}
        stage = conversation_state.get("stage") or call_record.conversation_stage
        product_intro_completed = bool(
            conversation_state.get("product_intro_completed", call_record.product_intro_completed)
        )
        product_label = (
            campaign_context.get("product_name")
            or product_brief.get("product_name")
            or "SPARX AI Calling Solution"
        )
        previous_summary = (
            conversation_state.get("previous_call_summary")
            or call_record.previous_call_summary
            or call_record.summary
            or "Not available"
        )
        callback_opening = MediaBridgeService._build_callback_opening_guidance(
            call_record=call_record,
            callback_context=callback_context,
            previous_summary=str(previous_summary),
        )

        call_brief_lines = [
            "Call context for the outbound conversation.",
            f"Lead Name: {call_record.lead_name}",
            f"Company: {call_record.company or 'Not provided'}",
            f"City: {call_record.city or 'Not provided'}",
            f"Role: {call_record.role or 'Not provided'}",
            f"Interest: {call_record.interest or 'Not provided'}",
            f"Call Objective: {call_record.call_objective}",
            f"Language Preference: {call_record.language}",
            f"Priority: {call_record.priority}",
            f"Product Name: {product_label}",
            f"Product Description: {product_brief.get('product_description') or 'Not provided'}",
            f"Value Proposition: {product_brief.get('value_proposition') or 'Not provided'}",
            f"Target Audience: {product_brief.get('target_audience') or 'Not provided'}",
            f"Qualification Criteria: {product_brief.get('qualification_criteria') or 'Not provided'}",
            f"Objection Handling Guidance: {product_brief.get('objection_handling') or 'Not provided'}",
            f"Meeting Goal: {product_brief.get('meeting_goal') or call_record.call_objective}",
            f"Additional Context: {call_record.additional_context or 'None'}",
            f"Previous Conversation Stage: {stage}",
            f"Product Intro Completed: {'yes' if product_intro_completed else 'no'}",
            f"Previous Call Summary: {previous_summary}",
            f"Callback Requested: {'yes' if call_record.callback_requested else 'no'}",
            f"Callback Requested Time: {call_record.callback_time.isoformat() if call_record.callback_time else 'Not provided'}",
            f"Lead Email: {saved_email or 'Not provided'}",
            f"Lead Website: {lead_profile.get('website') or 'Not provided'}",
            f"Lead Geography: {', '.join(part for part in [call_record.city, lead_profile.get('state'), lead_profile.get('country')] if part) or 'Not provided'}",
            f"Lead Notes: {lead_profile.get('notes') or 'None'}",
        ]
        if callback_opening:
            call_brief_lines.extend(
                [
                    f"Required Opening: {callback_opening['opening']}",
                    f"Required Callback Handling: {callback_opening['instruction']}",
                ]
            )

        if campaign_context:
            call_brief_lines.extend(
                [
                    f"Campaign Name: {campaign_context.get('campaign_name') or 'Not provided'}",
                    f"Campaign Type: {campaign_context.get('campaign_type') or 'Not provided'}",
                    f"Campaign Notes: {campaign_context.get('notes') or 'None'}",
                ]
            )

        call_brief_lines.append(
            "Use this context to guide the conversation and do not read the full brief verbatim unless it is useful."
        )
        call_brief = "\n".join(call_brief_lines)
        stage_guidance = MediaBridgeService._build_stage_guidance(
            lead_name=call_record.lead_name,
            stage=str(stage),
            product_intro_completed=product_intro_completed,
            meeting_booked=call_record.meeting_booked,
            product_label=product_label,
        )

        agent_configuration = metadata.get("agent_configuration")
        if not agent_configuration:
            return call_record.deepgram_agent_id or call_record.agent_id

        agent_payload = deepcopy(agent_configuration)
        # Enforce personalized greeting so the lead hears their name at the start.
        agent_payload["greeting"] = (
            callback_opening["opening"]
            if callback_opening
            else (
                f"Hello {call_record.lead_name}, this is the SPARX AI assistant. "
                f"I am calling regarding {product_label}."
            )
        )
        context = agent_payload.setdefault("context", {})
        messages = context.setdefault("messages", [])
        messages.append(
            {
                "type": "History",
                "role": "user",
                "content": (
                    "Conversation control rules:\n"
                    "1) Always greet the lead by name.\n"
                    f"2) If stage is NEW or PRODUCT_INTRO, or product intro is incomplete, explain {product_label} before asking for a meeting.\n"
                    "3) If stage is QUALIFICATION, continue discovery questions.\n"
                    "4) If stage is INTERESTED, handle objections/questions and move toward scheduling.\n"
                    "5) If stage is MEETING_PENDING, focus on booking the meeting.\n"
                    "6) If stage is MEETING_BOOKED, confirm details and close politely.\n"
                    "7) Never assume the user knows the product unless context explicitly says intro completed.\n"
                    "8) If Lead Email is provided, confirm it once before sending meeting details. If the lead corrects or replaces it, repeat the new address clearly and use that new email.\n"
                    "9) Ask for the lead's email only when Lead Email is Not provided or the lead says the saved email is wrong."
                ),
            }
        )
        if callback_opening:
            messages.append(
                {
                    "type": "History",
                    "role": "user",
                    "content": (
                        "Callback opening rules:\n"
                        f"1) Start with exactly this meaning: {callback_opening['opening']}\n"
                        f"2) {callback_opening['instruction']}\n"
                        "3) Use the previous context before asking any new question.\n"
                        "4) Do not restart the product pitch unless the context says product intro is incomplete."
                    ),
                }
            )
        messages.append({"type": "History", "role": "user", "content": stage_guidance})
        messages.append({"type": "History", "role": "user", "content": call_brief})
        return agent_payload

    @staticmethod
    def _build_callback_opening_guidance(
        *,
        call_record: CallResponse,
        callback_context: dict[str, object],
        previous_summary: str,
    ) -> dict[str, str] | None:
        if not call_record.callback_id and not callback_context:
            return None

        cancellation_context = callback_context.get("meeting_cancellation_followup")
        if isinstance(cancellation_context, dict):
            reason = str(cancellation_context.get("cancel_reason") or "").strip()
            reason_suffix = f" Reason: {reason}." if reason else ""
            return {
                "opening": (
                    f"Hello {call_record.lead_name}, this is the SPARX AI assistant. "
                    "You were not available at the meeting time, so I am calling about your cancelled meeting. "
                    "Would you like to reschedule your meeting or not?"
                ),
                "instruction": (
                    "Explain briefly that the meeting was cancelled."
                    f"{reason_suffix} Ask only whether they want to reschedule. "
                    "If yes, collect the new meeting date and time and confirm the email address. "
                    "If no, thank them politely and end without scheduling another callback."
                ),
            }

        origin_status = str(callback_context.get("origin_status") or "").strip()
        callback_reason = str(callback_context.get("callback_reason") or "").strip()
        requested_time = str(callback_context.get("requested_time_raw") or "").strip()
        if origin_status == "callback_requested" or "callback" in callback_reason.lower() or call_record.callback_requested:
            requested_suffix = f" You asked us to call at {requested_time}." if requested_time else ""
            summary_suffix = "" if previous_summary == "Not available" else f" Context from that discussion: {previous_summary}"
            return {
                "opening": (
                    f"Hello {call_record.lead_name}, this is the SPARX AI assistant. "
                    f"As per our previous discussion, I am calling you back.{requested_suffix}"
                ),
                "instruction": (
                    "Resume from the previous discussion before asking new questions."
                    f"{summary_suffix} Continue the conversation naturally and use the saved context."
                ),
            }

        return None

    @staticmethod
    def _build_stage_guidance(
        *,
        lead_name: str,
        stage: str,
        product_intro_completed: bool,
        meeting_booked: bool,
        product_label: str,
    ) -> str:
        if meeting_booked or stage == "MEETING_BOOKED":
            return (
                f"Greet {lead_name} by name, confirm booked meeting details, and end politely."
            )
        if stage == "MEETING_PENDING":
            return (
                f"Greet {lead_name} by name, confirm interest, and focus on scheduling the meeting now."
            )
        if stage == "INTERESTED":
            return (
                f"Greet {lead_name} by name, resume from prior interest, answer objections, and ask for meeting time."
            )
        if stage == "QUALIFICATION":
            return (
                f"Greet {lead_name} by name, then continue qualification and discovery questions."
            )
        if stage in {"NEW", "PRODUCT_INTRO"} or not product_intro_completed:
            return (
                f"Greet {lead_name} by name. Prospect may not know the product yet. "
                f"Introduce {product_label} first, then continue discovery."
            )
        return f"Greet {lead_name} by name and continue naturally from previous context."


@lru_cache
def get_media_bridge_service() -> MediaBridgeService:
    return MediaBridgeService(
        deepgram_service=get_deepgram_service(),
        call_service=get_call_service(),
    )
