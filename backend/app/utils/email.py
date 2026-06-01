from __future__ import annotations

import re

EMAIL_PATTERN = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)

WORD_REPLACEMENTS = {
    " at ": "@",
    " dot ": ".",
    " underscore ": "_",
    " dash ": "-",
    " hyphen ": "-",
    " plus ": "+",
}


def normalize_spoken_email(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = f" {value.strip().lower()} "
    normalized = normalized.replace("[at]", " at ").replace("(at)", " at ")
    normalized = normalized.replace("[dot]", " dot ").replace("(dot)", " dot ")
    normalized = normalized.replace("@", " @ ")
    normalized = normalized.replace(".", " . ")

    for source, replacement in WORD_REPLACEMENTS.items():
        normalized = normalized.replace(source, replacement)

    normalized = re.sub(r"\s+", "", normalized)
    normalized = normalized.replace("..", ".")
    return normalized or None


def is_valid_email(value: str | None) -> bool:
    return bool(value and EMAIL_PATTERN.fullmatch(value))
