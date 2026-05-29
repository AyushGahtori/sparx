import re


PHONE_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")


def normalize_phone_number(phone_number: str) -> str:
    cleaned = phone_number.strip()
    cleaned = re.sub(r"[^\d+]", "", cleaned)

    if cleaned.startswith("00"):
        cleaned = f"+{cleaned[2:]}"
    elif cleaned and not cleaned.startswith("+"):
        cleaned = f"+{cleaned}"

    if cleaned.startswith("+"):
        digits_only = re.sub(r"\D", "", cleaned[1:])
        cleaned = f"+{digits_only}"

    if not PHONE_PATTERN.fullmatch(cleaned):
        raise ValueError(
            "Phone numbers must resolve to E.164 format, for example +919999999999."
        )

    return cleaned
