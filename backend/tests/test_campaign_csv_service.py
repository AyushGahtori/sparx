from io import BytesIO
import pytest
from fastapi import UploadFile
from openpyxl import Workbook

from app.config.settings import Settings
from app.core.errors import AppError
from app.services.campaign_csv_service import CampaignCsvService


def build_service(**overrides) -> CampaignCsvService:
    base_settings = {
        "CAMPAIGN_CSV_MAX_FILE_SIZE_BYTES": 32768,
        "CAMPAIGN_CSV_MAX_ROWS": 10,
    }
    base_settings.update(overrides)
    settings = Settings(
        _env_file=None,
        **base_settings,
    )
    return CampaignCsvService(settings)


def build_xlsx_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Full Name", "Mobile Number", "Company Name", "Email Address", "Designation", "Custom Field"])
    sheet.append(["Aarav Mehta", "+919999999998", "Northwind Labs", "aarav@example.com", "Founder", "ICP"])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def build_company_only_xlsx_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Company Name", "Number", "Type", "Email"])
    sheet.append(["TechSnitch Solutions", "+919268371808", "IT Services", "contact@techsnitch.in"])
    sheet.append(["Aaron Textiles", "9812345678", "Manufacturing", "info@aarontextiles.in"])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


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

    assert preview.file_type == "csv"
    assert preview.valid_contacts == 1
    assert preview.duplicate_contacts == 1
    assert preview.preview_rows[1].validation_status == "duplicate"


@pytest.mark.asyncio
async def test_campaign_xlsx_preview_maps_header_aliases_and_preserves_extra_fields():
    service = build_service()
    upload = UploadFile(filename="contacts.xlsx", file=BytesIO(build_xlsx_bytes()))

    preview = await service.preview_upload(upload)

    assert preview.file_type == "xlsx"
    assert preview.valid_contacts == 1
    assert preview.contacts[0].name == "Aarav Mehta"
    assert preview.contacts[0].email == "aarav@example.com"
    assert preview.contacts[0].metadata == {"Custom Field": "ICP"}
    assert "Custom Field" in preview.unmapped_columns


@pytest.mark.asyncio
async def test_campaign_xlsx_preview_accepts_company_name_and_number_columns():
    service = build_service()
    upload = UploadFile(filename="company_contacts.xlsx", file=BytesIO(build_company_only_xlsx_bytes()))

    preview = await service.preview_upload(upload)

    assert preview.valid_contacts == 2
    assert preview.contacts[0].name == "TechSnitch Solutions"
    assert preview.contacts[0].company == "TechSnitch Solutions"
    assert preview.contacts[0].phone == "+919268371808"
    assert preview.contacts[0].interest == "IT Services"
    assert preview.contacts[1].name == "Aaron Textiles"
    assert preview.contacts[1].phone == "+919812345678"


@pytest.mark.asyncio
async def test_campaign_preview_rejects_non_spreadsheet_files():
    service = build_service()
    upload = UploadFile(filename="contacts.docx", file=BytesIO(b"not-a-renewal-sheet"))

    with pytest.raises(AppError) as exc_info:
        await service.preview_upload(upload)

    assert exc_info.value.code == "unsupported_lead_file_type"


@pytest.mark.asyncio
async def test_campaign_csv_preview_rejects_oversized_files():
    service = build_service(CAMPAIGN_CSV_MAX_FILE_SIZE_BYTES=1024)
    oversized_payload = ("name,phone,notes\nRahul,+919999999999," + ("x" * 3000)).encode("utf-8")
    upload = UploadFile(
        filename="contacts.csv",
        file=BytesIO(oversized_payload),
    )

    with pytest.raises(AppError) as exc_info:
        await service.preview_upload(upload)

    assert exc_info.value.code == "lead_file_too_large"
