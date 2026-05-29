from app.schemas.callback import CallbackPriority, CallbackSource


class CallbackPriorityService:
    high_keywords = {"callback", "call back", "meeting", "demo", "pricing", "proposal", "interested"}
    medium_keywords = {"unavailable", "busy later", "in meeting", "reach later", "call later"}

    def resolve_priority(
        self,
        *,
        callback_reason: str,
        source: CallbackSource,
        explicit_priority: CallbackPriority | None = None,
    ) -> CallbackPriority:
        if explicit_priority is not None:
            return explicit_priority

        normalized_reason = callback_reason.strip().lower()
        if any(keyword in normalized_reason for keyword in self.high_keywords):
            return "high"
        if any(keyword in normalized_reason for keyword in self.medium_keywords):
            return "medium"
        if source == "webhook":
            return "low"
        return "medium"


def get_callback_priority_service() -> CallbackPriorityService:
    return CallbackPriorityService()
