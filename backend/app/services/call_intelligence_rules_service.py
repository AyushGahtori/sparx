from functools import lru_cache

from app.models.firestore_documents import CallDocument, TranscriptEntryDocument


class CallIntelligenceRulesService:
    hot_keywords = {
        "pricing",
        "price",
        "proposal",
        "demo",
        "budget",
        "purchase",
        "buy",
        "contract",
    }
    warm_keywords = {
        "later",
        "follow up",
        "callback",
        "call back",
        "next week",
        "busy",
        "review",
        "check internally",
    }
    cold_keywords = {
        "not interested",
        "already using",
        "do not call",
        "stop calling",
        "no need",
        "not now",
        "not required",
    }
    objection_keywords = {
        "expensive": "Pricing concern",
        "price": "Pricing concern",
        "budget": "Budget concern",
        "approval": "Needs approval",
        "manager": "Needs management approval",
        "already using": "Already using another system",
        "later": "Requested later follow-up",
        "busy": "Lead was unavailable",
        "not interested": "Not interested at the moment",
    }
    callback_intent_phrases = {
        "call me later",
        "call later",
        "call you later",
        "call me back",
        "call back",
        "call tomorrow",
        "call next week",
        "call after",
        "callback",
        "follow up later",
        "talk later",
        "speak later",
        "busy right now",
        "i am busy",
        "i'm busy",
    }
    hard_no_followup_phrases = {
        "do not call",
        "don't call",
        "stop calling",
        "not interested",
        "not required",
        "no need",
    }

    def build_rule_hints(
        self,
        call_document: CallDocument,
        transcript_entries: list[TranscriptEntryDocument],
        transcript_metrics: dict[str, int],
    ) -> dict[str, object]:
        transcript_text = " ".join(entry.text.lower() for entry in transcript_entries)
        lead_text = " ".join(entry.text.lower() for entry in transcript_entries if entry.speaker == "lead")

        lead_type, lead_reason = self._infer_lead_type(call_document, transcript_text, lead_text)
        call_outcome, outcome_reason = self._infer_outcome(call_document, transcript_text, lead_text)
        next_action = self._infer_next_action(call_document, lead_type, call_outcome)
        objection_hints = self._extract_objection_hints(transcript_text, lead_text)

        return {
            **transcript_metrics,
            "lead_type": lead_type,
            "lead_reason": lead_reason,
            "call_outcome": call_outcome,
            "outcome_reason": outcome_reason,
            "next_action": next_action,
            "objection_hints": objection_hints,
        }

    def _infer_lead_type(
        self,
        call_document: CallDocument,
        transcript_text: str,
        lead_text: str,
    ) -> tuple[str, str]:
        if call_document.meeting_requested or "demo" in transcript_text:
            return "hot", "The lead requested a meeting or discussed a demo."
        if any(keyword in transcript_text for keyword in self.hot_keywords):
            return "hot", "The conversation included strong commercial intent such as pricing, proposal, or purchase terms."
        if call_document.callback_requested or any(keyword in lead_text for keyword in self.warm_keywords):
            return "warm", "The lead showed interest but deferred a decision or follow-up."
        if any(keyword in lead_text for keyword in self.cold_keywords):
            return "cold", "The lead expressed low or negative intent."
        return "warm", "The lead engaged in the conversation but did not show a decisive buying signal."

    def _infer_outcome(
        self,
        call_document: CallDocument,
        transcript_text: str,
        lead_text: str,
    ) -> tuple[str, str]:
        if call_document.final_status == "not_interested":
            return "not_interested", "The lead did not pick up after configured retry attempts."
        if call_document.status in {"failed", "busy", "no_answer"}:
            return "failed", "The call did not complete successfully."
        if call_document.meeting_requested:
            return "meeting_requested", "A meeting or demo request was captured."
        if call_document.callback_requested:
            return "callback", "The lead requested a callback."
        if self._has_callback_intent(lead_text):
            return "callback", "The lead asked to continue the conversation later or requested a callback."
        if any(keyword in lead_text for keyword in self.cold_keywords):
            return "not_interested", "The lead stated they were not interested or did not need the solution."
        if any(keyword in transcript_text for keyword in self.hot_keywords):
            return "interested", "The lead asked commercially meaningful questions."
        return "successful", "The conversation completed with usable engagement."

    def _has_callback_intent(self, lead_text: str) -> bool:
        if any(phrase in lead_text for phrase in self.hard_no_followup_phrases):
            return False
        return any(phrase in lead_text for phrase in self.callback_intent_phrases)

    @staticmethod
    def _infer_next_action(call_document: CallDocument, lead_type: str, call_outcome: str) -> str:
        if call_outcome == "meeting_requested":
            return "Book the requested meeting or demo."
        if call_outcome == "callback":
            return "Honor the callback request at the requested time."
        if call_outcome == "not_interested":
            return "Mark the lead as not interested and stop active follow-up."
        if lead_type == "hot":
            return "Follow up within 48 hours with pricing or a tailored proposal."
        if lead_type == "warm":
            return "Follow up with a helpful recap and a clear next step."
        if call_document.status in {"failed", "busy", "no_answer"}:
            return "Retry the call according to the retry policy."
        return "Review the transcript and decide whether another follow-up is justified."

    def _extract_objection_hints(self, transcript_text: str, lead_text: str) -> list[str]:
        hints: list[str] = []
        for keyword, label in self.objection_keywords.items():
            if keyword in transcript_text or keyword in lead_text:
                hints.append(label)
        return sorted(set(hints))


@lru_cache
def get_call_intelligence_rules_service() -> CallIntelligenceRulesService:
    return CallIntelligenceRulesService()
