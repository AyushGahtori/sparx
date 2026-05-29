from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class RetryDecision:
    retry_count: int
    next_retry_time: datetime | None
    final_status: str
    backoff_seconds: int = 0


class RetryService:
    retryable_statuses = {"failed", "busy", "no_answer"}

    def build_retry_decision(self, current_retry_count: int, status: str, reference_time: datetime) -> RetryDecision:
        if status not in self.retryable_statuses:
            return RetryDecision(
                retry_count=current_retry_count,
                next_retry_time=None,
                final_status=status,
                backoff_seconds=0,
            )

        next_retry_count = current_retry_count + 1

        if next_retry_count == 1:
            next_retry_time = reference_time + timedelta(hours=2)
            return RetryDecision(
                retry_count=next_retry_count,
                next_retry_time=next_retry_time,
                final_status="retry_scheduled",
                backoff_seconds=int((next_retry_time - reference_time).total_seconds()),
            )

        if next_retry_count == 2:
            next_retry_time = reference_time + timedelta(days=1)
            return RetryDecision(
                retry_count=next_retry_count,
                next_retry_time=next_retry_time,
                final_status="retry_scheduled",
                backoff_seconds=int((next_retry_time - reference_time).total_seconds()),
            )

        return RetryDecision(
            retry_count=next_retry_count,
            next_retry_time=None,
            final_status="permanently_failed",
            backoff_seconds=0,
        )
