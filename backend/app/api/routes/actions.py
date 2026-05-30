from fastapi import APIRouter, Depends

from app.actions.schedule_call_action import ScheduleCallAction, get_schedule_call_action
from app.schemas.scheduled_call import ScheduleCallActionRequest, ScheduledCallResponse

router = APIRouter(prefix="/actions")


@router.post("/schedule-call", response_model=ScheduledCallResponse)
async def schedule_call(
    payload: ScheduleCallActionRequest,
    action: ScheduleCallAction = Depends(get_schedule_call_action),
) -> ScheduledCallResponse:
    return await action.execute(payload)
