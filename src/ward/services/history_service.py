"""Read-only chat history service."""

from __future__ import annotations

from typing import Any

from ward.services.db.conversation_service import ConversationService


class HistoryService:
    """Expose conversation history without the legacy chat implementation."""

    def __init__(self):
        self.conversations = ConversationService()

    def get_history(self, conversation_id: int) -> dict[str, Any]:
        messages, has_more, next_before_id = self.conversations.get_messages_paginated(
            conversation_id, limit=20, before_id=None
        )
        return {
            "ok": True,
            "conversation_id": conversation_id,
            "messages": messages,
            "has_more": has_more,
            "next_before_id": next_before_id,
        }

    def get_history_paginated(
        self,
        conversation_id: int,
        limit: int = 20,
        before_id: int | None = None,
    ) -> dict[str, Any]:
        messages, has_more, next_before_id = self.conversations.get_messages_paginated(
            conversation_id, limit, before_id
        )
        return {
            "ok": True,
            "conversation_id": conversation_id,
            "messages": messages,
            "has_more": has_more,
            "next_before_id": next_before_id,
        }
