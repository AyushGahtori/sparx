import asyncio
import base64
import contextlib
import json
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

    def __init__(self, deepgram_service: DeepgramService, call_service: CallService) -> None:
        self.deepgram_service = deepgram_service
        self.call_service = call_service

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

    @staticmethod
    def _build_agent_payload(call_record: CallResponse) -> dict[str, object] | str:
        metadata = deepcopy(call_record.metadata)
        campaign_context = metadata.get("campaign_context") or {}
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
            f"Additional Context: {call_record.additional_context or 'None'}",
        ]

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

        agent_configuration = metadata.get("agent_configuration")
        if not agent_configuration:
            return call_record.deepgram_agent_id or call_record.agent_id

        agent_payload = deepcopy(agent_configuration)
        context = agent_payload.setdefault("context", {})
        messages = context.setdefault("messages", [])
        messages.append({"type": "History", "role": "user", "content": call_brief})
        return agent_payload


@lru_cache
def get_media_bridge_service() -> MediaBridgeService:
    return MediaBridgeService(
        deepgram_service=get_deepgram_service(),
        call_service=get_call_service(),
    )
