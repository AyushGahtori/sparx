import csv
import io
from functools import lru_cache

from fastapi import UploadFile

from app.config.settings import Settings, get_settings
from app.core.errors import AppError
from app.schemas.campaign import (
    CampaignContactInput,
    CampaignCsvPreviewResponse,
    CampaignCsvPreviewRow,
)
from app.utils.phone import normalize_phone_number


class CampaignCsvService:
    required_columns = {"name", "phone"}
    optional_columns = {"company", "city", "role", "interest"}
    supported_columns = required_columns | optional_columns

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def preview_upload(self, upload_file: UploadFile) -> CampaignCsvPreviewResponse:
        filename = upload_file.filename or "campaign-contacts.csv"
        if not filename.lower().endswith(".csv"):
            raise AppError(
                status_code=400,
                code="invalid_csv_file",
                message="Only CSV uploads are supported for campaign contacts.",
            )

        raw_content = await upload_file.read()
        if not raw_content:
            raise AppError(
                status_code=400,
                code="empty_csv_file",
                message="The uploaded CSV file is empty.",
            )
        if len(raw_content) > self.settings.campaign_csv_max_file_size_bytes:
            raise AppError(
                status_code=413,
                code="csv_file_too_large",
                message=(
                    f"CSV uploads must be smaller than {self.settings.campaign_csv_max_file_size_bytes} bytes."
                ),
            )

        try:
            decoded_content = raw_content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise AppError(
                status_code=400,
                code="invalid_csv_encoding",
                message="CSV files must use UTF-8 encoding.",
            ) from exc

        reader = csv.DictReader(io.StringIO(decoded_content))
        if reader.fieldnames is None:
            raise AppError(
                status_code=400,
                code="missing_csv_header",
                message="The CSV file must include a header row.",
            )

        normalized_headers = [header.strip().lower() for header in reader.fieldnames if header]
        unsupported_columns = sorted(set(normalized_headers) - self.supported_columns)
        if unsupported_columns:
            raise AppError(
                status_code=400,
                code="unsupported_csv_columns",
                message=f"Unsupported CSV columns: {', '.join(unsupported_columns)}.",
                details={"supported_columns": sorted(self.supported_columns)},
            )
        missing_columns = sorted(self.required_columns - set(normalized_headers))
        if missing_columns:
            raise AppError(
                status_code=400,
                code="missing_csv_columns",
                message=f"Missing required CSV columns: {', '.join(missing_columns)}.",
            )

        preview_rows: list[CampaignCsvPreviewRow] = []
        valid_contacts: list[CampaignContactInput] = []
        seen_phones: set[str] = set()

        for row_number, row in enumerate(reader, start=1):
            if row_number > self.settings.campaign_csv_max_rows:
                raise AppError(
                    status_code=400,
                    code="csv_row_limit_exceeded",
                    message=f"CSV uploads cannot contain more than {self.settings.campaign_csv_max_rows} rows.",
                )
            sanitized_row = self._sanitize_row(row, normalized_headers)
            preview_row = CampaignCsvPreviewRow(
                row_number=row_number,
                validation_status="invalid",
                validation_message="Pending validation.",
                **sanitized_row,
            )

            try:
                normalized_phone = normalize_phone_number(sanitized_row.get("phone") or "")
                preview_row.normalized_phone = normalized_phone

                if normalized_phone in seen_phones:
                    preview_row.validation_status = "duplicate"
                    preview_row.validation_message = "Duplicate phone number found in this upload."
                elif not sanitized_row.get("name"):
                    preview_row.validation_status = "invalid"
                    preview_row.validation_message = "The name column is required."
                else:
                    contact = CampaignContactInput(
                        name=sanitized_row["name"],
                        phone=normalized_phone,
                        company=sanitized_row.get("company"),
                        city=sanitized_row.get("city"),
                        role=sanitized_row.get("role"),
                        interest=sanitized_row.get("interest"),
                    )
                    valid_contacts.append(contact)
                    seen_phones.add(normalized_phone)
                    preview_row.validation_status = "valid"
                    preview_row.validation_message = "Ready for campaign import."
            except ValueError as exc:
                preview_row.validation_status = "invalid"
                preview_row.validation_message = str(exc)

            preview_rows.append(preview_row)

        valid_count = len([row for row in preview_rows if row.validation_status == "valid"])
        invalid_count = len([row for row in preview_rows if row.validation_status == "invalid"])
        duplicate_count = len([row for row in preview_rows if row.validation_status == "duplicate"])

        return CampaignCsvPreviewResponse(
            filename=filename,
            total_rows=len(preview_rows),
            valid_contacts=valid_count,
            invalid_contacts=invalid_count,
            duplicate_contacts=duplicate_count,
            preview_rows=preview_rows,
            contacts=valid_contacts,
        )

    def _sanitize_row(self, row: dict[str, str | None], normalized_headers: list[str]) -> dict[str, str | None]:
        sanitized: dict[str, str | None] = {column: None for column in self.supported_columns}
        for original_header, value in row.items():
            if original_header is None:
                continue
            normalized_header = original_header.strip().lower()
            if normalized_header not in normalized_headers or normalized_header not in self.supported_columns:
                continue
            sanitized[normalized_header] = value.strip() if isinstance(value, str) and value.strip() else None
        return sanitized


@lru_cache
def get_campaign_csv_service() -> CampaignCsvService:
    return CampaignCsvService(get_settings())
