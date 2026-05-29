from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.schemas.intelligence import (
    CallOutcome,
    LeadType,
    SummaryDeleteResponse,
    SummaryDetailResponse,
    SummaryListItemResponse,
    SummarySentiment,
)
from app.services.post_call_intelligence_service import (
    PostCallIntelligenceService,
    get_post_call_intelligence_service,
)

router = APIRouter(prefix="/summaries")


@router.get("", response_model=list[SummaryListItemResponse])
async def list_summaries(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    campaign_id: str | None = Query(default=None),
    lead_type: LeadType | None = Query(default=None),
    outcome: CallOutcome | None = Query(default=None),
    sentiment: SummarySentiment | None = Query(default=None),
    intelligence_service: PostCallIntelligenceService = Depends(get_post_call_intelligence_service),
) -> list[SummaryListItemResponse]:
    return await intelligence_service.list_summaries(
        date_from=date_from,
        date_to=date_to,
        campaign_id=campaign_id,
        lead_type=lead_type,
        outcome=outcome,
        sentiment=sentiment,
    )


@router.get("/{call_id}", response_model=SummaryDetailResponse)
async def get_summary(
    call_id: str,
    intelligence_service: PostCallIntelligenceService = Depends(get_post_call_intelligence_service),
) -> SummaryDetailResponse:
    return await intelligence_service.get_summary(call_id)


@router.delete("/{call_id}", response_model=SummaryDeleteResponse)
async def delete_summary(
    call_id: str,
    intelligence_service: PostCallIntelligenceService = Depends(get_post_call_intelligence_service),
) -> SummaryDeleteResponse:
    return await intelligence_service.delete_summary(call_id)
