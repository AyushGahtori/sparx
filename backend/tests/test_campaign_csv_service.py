from io import BytesIO

import pytest
from fastapi import UploadFile

from app.config.settings import Settings
from app.core.errors import AppError
from app.services.campaign_csv_service import CampaignCsvService


def build_service(**overrides) -> CampaignCsvService:
    settings_values = {
        "CAMPAIGN_CSV_MAX_FILE_SIZE_BYTES": 2048,
        "CAMPAIGN_CSV_MAX_ROWS": 10,
        **overrides,
    }
    settings = Settings(_env_file=None, **settings_values)
    return CampaignCsvService(settings)


@pytest.mark.asyncio
async def test_campaign_csv_preview_marks_duplicate_rows():
    service = build_service()
    csv_payload = (
        "name,phone,company\n"
        "Rahul,+919999999999,ABC\n"
        "Priya,+919999999999,XYZ\n"
    ).encode("utf-8")
    upload = UploadFile(filename="contacts.csv", file=BytesIO(csv_payload))

    preview = await service.preview_upload(upload)

    assert preview.valid_contacts == 1
    assert preview.duplicate_contacts == 1
    assert preview.preview_rows[1].validation_status == "duplicate"


@pytest.mark.asyncio
async def test_campaign_csv_preview_rejects_oversized_files():
    service = build_service(CAMPAIGN_CSV_MAX_FILE_SIZE_BYTES=1024)
    upload = UploadFile(
        filename="contacts.csv",
        file=BytesIO(b"name,phone\nRahul,+919999999999\n" + (b"A" * 1200)),
    )

    with pytest.raises(AppError) as exc_info:
        await service.preview_upload(upload)

    assert exc_info.value.code == "csv_file_too_large"
