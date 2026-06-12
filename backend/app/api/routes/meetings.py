from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.api.dependencies.auth import get_current_user
from app.schemas.meeting import (
    MeetingCancelRequest,
    MeetingCancelResponse,
    MeetingCreateRequest,
    MeetingDeleteResponse,
    MeetingResponse,
    MeetingRescheduleRequest,
    MeetingStatus,
    MeetingSyncResponse,
)
from app.services.firebase_auth_service import AuthenticatedUser
from app.services.meeting_service import MeetingService, get_meeting_service

router = APIRouter(prefix="/meetings")


@router.get("", response_model=list[MeetingResponse])
async def list_meetings(
    status: MeetingStatus | None = None,
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    sync_google: bool = Query(default=True),
    current_user: AuthenticatedUser = Depends(get_current_user),
    meeting_service: MeetingService = Depends(get_meeting_service),
) -> list[MeetingResponse]:
    return await meeting_service.list_meetings(
        status=status,
        date_from=date_from,
        date_to=date_to,
        sync_google=sync_google,
        operator_uid=current_user.uid,
    )


@router.post("", response_model=MeetingResponse)
async def create_meeting(
    payload: MeetingCreateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    meeting_service: MeetingService = Depends(get_meeting_service),
) -> MeetingResponse:
    return await meeting_service.create_meeting(payload, operator_uid=current_user.uid)


@router.post("/sync", response_model=MeetingSyncResponse)
async def sync_meetings(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    current_user: AuthenticatedUser = Depends(get_current_user),
    meeting_service: MeetingService = Depends(get_meeting_service),
) -> MeetingSyncResponse:
    return await meeting_service.sync_google_meetings(
        date_from=date_from,
        date_to=date_to,
        operator_uid=current_user.uid,
    )


@router.post("/{meeting_id}/reschedule", response_model=MeetingResponse)
async def reschedule_meeting(
    meeting_id: str,
    payload: MeetingRescheduleRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    meeting_service: MeetingService = Depends(get_meeting_service),
) -> MeetingResponse:
    return await meeting_service.reschedule_meeting(
        meeting_id,
        payload,
        operator_uid=current_user.uid,
    )


@router.post("/{meeting_id}/done", response_model=MeetingResponse)
async def mark_meeting_done(
    meeting_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    meeting_service: MeetingService = Depends(get_meeting_service),
) -> MeetingResponse:
    return await meeting_service.mark_meeting_done(meeting_id, operator_uid=current_user.uid)


@router.post("/{meeting_id}/cancel", response_model=MeetingCancelResponse)
async def cancel_meeting(
    meeting_id: str,
    payload: MeetingCancelRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    meeting_service: MeetingService = Depends(get_meeting_service),
) -> MeetingCancelResponse:
    return await meeting_service.cancel_meeting(
        meeting_id,
        payload,
        operator_uid=current_user.uid,
    )


@router.delete("/{meeting_id}", response_model=MeetingDeleteResponse)
async def delete_meeting(
    meeting_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    meeting_service: MeetingService = Depends(get_meeting_service),
) -> MeetingDeleteResponse:
    return await meeting_service.delete_meeting(meeting_id, operator_uid=current_user.uid)
