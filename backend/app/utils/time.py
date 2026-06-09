from datetime import datetime, timezone
from zoneinfo import ZoneInfo


INDIA_TIMEZONE_NAME = "Asia/Kolkata"
INDIA_TIMEZONE = ZoneInfo(INDIA_TIMEZONE_NAME)


def india_now() -> datetime:
    return datetime.now(INDIA_TIMEZONE)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def coerce_india(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=INDIA_TIMEZONE)
    return value.astimezone(INDIA_TIMEZONE)


def format_uptime(started_at: datetime) -> str:
    elapsed = utc_now() - started_at
    total_seconds = int(elapsed.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
