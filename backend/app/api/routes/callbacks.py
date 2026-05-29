from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.schemas.callback import (
    CallbackCreateRequest,
    CallbackDeleteResponse,
    CallbackPriority,
    CallbackRescheduleRequest,
    CallbackResponse,
    CallbackSource,
    CallbackStatus,
    CallbackUpdateRequest,
)
from app.services.callback_service import CallbackService, get_callback_service

router = APIRouter(prefix="/callbacks")


@router.get("", response_model=list[CallbackResponse])
async def list_callbacks(
    status: CallbackStatus | None = None,
    priority: CallbackPriority | None = None,
    source: CallbackSource | None = None,
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    callback_service: CallbackService = Depends(get_callback_service),
) -> list[CallbackResponse]:
    return await callback_service.list_callbacks(
        status=status,
        priority=priority,
        source=source,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/{callback_id}", response_model=CallbackResponse)
async def get_callback(
    callback_id: str,
    callback_service: CallbackService = Depends(get_callback_service),
) -> CallbackResponse:
    return await callback_service.get_callback(callback_id)


@router.post("", response_model=CallbackResponse)
async def create_callback(
    payload: CallbackCreateRequest,
    callback_service: CallbackService = Depends(get_callback_service),
) -> CallbackResponse:
    return await callback_service.create_callback(payload)


@router.put("/{callback_id}", response_model=CallbackResponse)
async def update_callback(
    callback_id: str,
    payload: CallbackUpdateRequest,
    callback_service: CallbackService = Depends(get_callback_service),
) -> CallbackResponse:
    return await callback_service.update_callback(callback_id, payload)


@router.post("/{callback_id}/reschedule", response_model=CallbackResponse)
async def reschedule_callback(
    callback_id: str,
    payload: CallbackRescheduleRequest,
    callback_service: CallbackService = Depends(get_callback_service),
) -> CallbackResponse:
    return await callback_service.reschedule_callback(callback_id, payload)


@router.post("/{callback_id}/execute", response_model=CallbackResponse)
async def execute_callback_now(
    callback_id: str,
    callback_service: CallbackService = Depends(get_callback_service),
) -> CallbackResponse:
    return await callback_service.execute_callback_now(callback_id)


@router.delete("/{callback_id}", response_model=CallbackDeleteResponse)
async def delete_callback(
    callback_id: str,
    callback_service: CallbackService = Depends(get_callback_service),
) -> CallbackDeleteResponse:
    return await callback_service.delete_callback(callback_id)
