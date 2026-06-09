from fastapi import APIRouter, Depends, Response

from app.schemas.call import (
    CallDeleteResponse,
    CallResponse,
    CallStatusUpdateRequest,
    IndividualCallRequest,
    MeetingConfirmationIntentRequest,
    MeetingConfirmationIntentResponse,
)
from app.schemas.intelligence import SummaryDetailResponse, TranscriptIngestionRequest
from app.services.call_service import CallService, get_call_service
from app.services.post_call_intelligence_runner_service import (
    PostCallIntelligenceRunnerService,
    get_post_call_intelligence_runner_service,
)
from app.services.post_call_intelligence_service import (
    PostCallIntelligenceService,
    get_post_call_intelligence_service,
)

router = APIRouter(prefix="/calls")


@router.get("", response_model=list[CallResponse])
async def list_calls(
    call_service: CallService = Depends(get_call_service),
) -> list[CallResponse]:
    return await call_service.list_calls()


@router.get("/recordings", response_model=list[CallResponse])
async def list_call_recordings(
    call_service: CallService = Depends(get_call_service),
) -> list[CallResponse]:
    return await call_service.list_recorded_calls()


@router.get("/{call_id}/recording/audio")
async def get_call_recording_audio(
    call_id: str,
    call_service: CallService = Depends(get_call_service),
) -> Response:
    content, media_type, filename = await call_service.fetch_recording_audio(call_id)
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "private, max-age=300",
            "X-Skip-Envelope": "1",
        },
    )


@router.get("/{call_id}", response_model=CallResponse)
async def get_call(
    call_id: str,
    call_service: CallService = Depends(get_call_service),
) -> CallResponse:
    return await call_service.get_call(call_id)


@router.post("/individual", response_model=CallResponse)
async def start_individual_call(
    payload: IndividualCallRequest,
    call_service: CallService = Depends(get_call_service),
) -> CallResponse:
    return await call_service.start_individual_call(payload)


@router.put("/{call_id}/status", response_model=CallResponse)
async def update_call_status(
    call_id: str,
    payload: CallStatusUpdateRequest,
    call_service: CallService = Depends(get_call_service),
) -> CallResponse:
    return await call_service.update_call_status(call_id, payload)


@router.post("/{call_id}/transcript", response_model=CallResponse)
async def ingest_call_transcript(
    call_id: str,
    payload: TranscriptIngestionRequest,
    intelligence_service: PostCallIntelligenceService = Depends(get_post_call_intelligence_service),
    intelligence_runner: PostCallIntelligenceRunnerService = Depends(get_post_call_intelligence_runner_service),
) -> CallResponse:
    updated_call = await intelligence_service.ingest_transcript(call_id, payload)
    if payload.auto_process:
        await intelligence_runner.schedule_call_processing(call_id)
    return updated_call


@router.post("/{call_id}/process-ai", response_model=SummaryDetailResponse)
async def process_call_intelligence(
    call_id: str,
    intelligence_runner: PostCallIntelligenceRunnerService = Depends(get_post_call_intelligence_runner_service),
) -> SummaryDetailResponse:
    return await intelligence_runner.process_now(call_id, force=True)


@router.delete("/{call_id}", response_model=CallDeleteResponse)
async def delete_call(
    call_id: str,
    call_service: CallService = Depends(get_call_service),
) -> CallDeleteResponse:
    return await call_service.delete_call(call_id)


@router.post("/{call_id}/meeting-intent", response_model=MeetingConfirmationIntentResponse)
async def handle_meeting_confirmation_intent(
    call_id: str,
    payload: MeetingConfirmationIntentRequest,
    call_service: CallService = Depends(get_call_service),
) -> MeetingConfirmationIntentResponse:
    return await call_service.handle_meeting_confirmation_intent(call_id, payload)
