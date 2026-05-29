import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.request_context import get_request_id


SENSITIVE_PATTERNS = [
    re.compile(r"(AC[a-zA-Z0-9]{8,})"),
    re.compile(r"(SK[a-zA-Z0-9]{8,})"),
    re.compile(r"([A-Za-z0-9_\-]{24,}\.[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{10,})"),
    re.compile(r"(\+?\d{0,3})\d{6,9}(\d{2})"),
]


def _mask_sensitive_text(message: str) -> str:
    masked_message = message
    masked_message = re.sub(r"(Authorization['\"=: ]+)([^,\s]+)", r"\1***", masked_message, flags=re.IGNORECASE)
    masked_message = re.sub(r"(api[_-]?key['\"=: ]+)([^,\s]+)", r"\1***", masked_message, flags=re.IGNORECASE)
    masked_message = re.sub(r"(token['\"=: ]+)([^,\s]+)", r"\1***", masked_message, flags=re.IGNORECASE)
    for pattern in SENSITIVE_PATTERNS:
        masked_message = pattern.sub(_replace_with_mask, masked_message)
    return masked_message


def _replace_with_mask(match: re.Match) -> str:
    value = match.group(0)
    if len(value) <= 6:
        return "***"
    return f"{value[:3]}***{value[-2:]}"


class ExactLevelFilter(logging.Filter):
    def __init__(self, level: int) -> None:
        super().__init__()
        self.level = level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno == self.level


class MinimumLevelFilter(logging.Filter):
    def __init__(self, level: int) -> None:
        super().__init__()
        self.level = level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= self.level


class ContextEnricherFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        record.category = self._infer_category(record.name)
        message = record.getMessage()
        record.msg = _mask_sensitive_text(message)
        record.args = ()
        return True

    @staticmethod
    def _infer_category(logger_name: str) -> str:
        normalized = logger_name.lower()
        if "twilio" in normalized:
            return "twilio"
        if "deepgram" in normalized:
            return "deepgram"
        if "campaign" in normalized:
            return "campaigns"
        if "callback" in normalized:
            return "callbacks"
        if "gemma" in normalized or "intelligence" in normalized:
            return "gemma"
        if "security" in normalized or "rate_limit" in normalized:
            return "security"
        if "middleware" in normalized or ".api." in normalized:
            return "api"
        if "error" in normalized or "handler" in normalized:
            return "errors"
        return "system"


def _build_formatter() -> logging.Formatter:
    return logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(category)s | %(name)s | request_id=%(request_id)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _build_file_handler(
    file_path: Path,
    level: int,
    level_filter: logging.Filter,
) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        file_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.addFilter(level_filter)
    handler.addFilter(ContextEnricherFilter())
    handler.setFormatter(_build_formatter())
    return handler


def configure_logging(logs_dir: Path, log_level: str) -> None:
    configure_logging_with_files(logs_dir, log_level, enable_file_logging=True)


def configure_logging_with_files(logs_dir: Path, log_level: str, enable_file_logging: bool) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    console_handler.addFilter(ContextEnricherFilter())
    console_handler.setFormatter(_build_formatter())

    root_logger.addHandler(console_handler)

    if enable_file_logging:
        info_handler = _build_file_handler(logs_dir / "info.log", logging.INFO, ExactLevelFilter(logging.INFO))
        warning_handler = _build_file_handler(
            logs_dir / "warning.log",
            logging.WARNING,
            ExactLevelFilter(logging.WARNING),
        )
        error_handler = _build_file_handler(
            logs_dir / "error.log",
            logging.ERROR,
            MinimumLevelFilter(logging.ERROR),
        )

        root_logger.addHandler(info_handler)
        root_logger.addHandler(warning_handler)
        root_logger.addHandler(error_handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
