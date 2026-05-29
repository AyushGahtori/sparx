from fastapi import APIRouter, Depends, File, UploadFile

from app.schemas.campaign import (
    CampaignCreateRequest,
    CampaignCsvPreviewResponse,
    CampaignDeleteResponse,
    CampaignContactResponse,
    CampaignResponse,
)
from app.services.campaign_service import CampaignService, get_campaign_service

router = APIRouter(prefix="/campaigns")


@router.post("/preview-csv", response_model=CampaignCsvPreviewResponse)
async def preview_campaign_csv(
    file: UploadFile = File(...),
    campaign_service: CampaignService = Depends(get_campaign_service),
) -> CampaignCsvPreviewResponse:
    return await campaign_service.preview_csv_upload(file)


@router.get("", response_model=list[CampaignResponse])
async def list_campaigns(
    campaign_service: CampaignService = Depends(get_campaign_service),
) -> list[CampaignResponse]:
    return await campaign_service.list_campaigns()


@router.post("", response_model=CampaignResponse)
async def create_campaign(
    payload: CampaignCreateRequest,
    campaign_service: CampaignService = Depends(get_campaign_service),
) -> CampaignResponse:
    return await campaign_service.create_campaign(payload)


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    campaign_id: str,
    campaign_service: CampaignService = Depends(get_campaign_service),
) -> CampaignResponse:
    return await campaign_service.get_campaign(campaign_id)


@router.get("/{campaign_id}/contacts", response_model=list[CampaignContactResponse])
async def get_campaign_contacts(
    campaign_id: str,
    campaign_service: CampaignService = Depends(get_campaign_service),
) -> list[CampaignContactResponse]:
    return await campaign_service.get_campaign_contacts(campaign_id)


@router.post("/{campaign_id}/start", response_model=CampaignResponse)
async def start_campaign(
    campaign_id: str,
    campaign_service: CampaignService = Depends(get_campaign_service),
) -> CampaignResponse:
    return await campaign_service.start_campaign(campaign_id)


@router.post("/{campaign_id}/pause", response_model=CampaignResponse)
async def pause_campaign(
    campaign_id: str,
    campaign_service: CampaignService = Depends(get_campaign_service),
) -> CampaignResponse:
    return await campaign_service.pause_campaign(campaign_id)


@router.post("/{campaign_id}/resume", response_model=CampaignResponse)
async def resume_campaign(
    campaign_id: str,
    campaign_service: CampaignService = Depends(get_campaign_service),
) -> CampaignResponse:
    return await campaign_service.resume_campaign(campaign_id)


@router.post("/{campaign_id}/stop", response_model=CampaignResponse)
async def stop_campaign(
    campaign_id: str,
    campaign_service: CampaignService = Depends(get_campaign_service),
) -> CampaignResponse:
    return await campaign_service.stop_campaign(campaign_id)


@router.delete("/{campaign_id}", response_model=CampaignDeleteResponse)
async def delete_campaign(
    campaign_id: str,
    campaign_service: CampaignService = Depends(get_campaign_service),
) -> CampaignDeleteResponse:
    return await campaign_service.delete_campaign(campaign_id)
