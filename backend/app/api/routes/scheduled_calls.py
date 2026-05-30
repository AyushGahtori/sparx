from fastapi import APIRouter, Depends

from app.schemas.scheduled_call import (
    ScheduledCallResponse,
    ScheduledCallStatus,
    ScheduledCallStatusUpdateRequest,
    ScheduledCallType,
)
from app.services.scheduled_call_service import ScheduledCallService, get_scheduled_call_service

router = APIRouter(prefix="/scheduled-calls")


@router.get("", response_model=list[ScheduledCallResponse])
async def list_scheduled_calls(
    type: ScheduledCallType | None = None,
    status: ScheduledCallStatus | None = None,
    scheduled_call_service: ScheduledCallService = Depends(get_scheduled_call_service),
) -> list[ScheduledCallResponse]:
    return await scheduled_call_service.list_scheduled_calls(type=type, status=status)


@router.get("/{scheduled_call_id}", response_model=ScheduledCallResponse)
async def get_scheduled_call(
    scheduled_call_id: str,
    scheduled_call_service: ScheduledCallService = Depends(get_scheduled_call_service),
) -> ScheduledCallResponse:
    return await scheduled_call_service.get_scheduled_call(scheduled_call_id)


@router.put("/{scheduled_call_id}/status", response_model=ScheduledCallResponse)
async def update_scheduled_call_status(
    scheduled_call_id: str,
    payload: ScheduledCallStatusUpdateRequest,
    scheduled_call_service: ScheduledCallService = Depends(get_scheduled_call_service),
) -> ScheduledCallResponse:
    return await scheduled_call_service.update_scheduled_call_status(scheduled_call_id, payload)
