"""Interactive chat service — supports multi-turn conversations with market data context."""

from __future__ import annotations

import json
from typing import Any

from anthropic import Anthropic

from ward.core.config import get_config
from ward.schemas.models import ChatContext
from ward.services.db.conversation_service import ConversationService
from ward.services.nasdaq_service import MarketService


# ─── System Prompt Templates ─────────────────────────────────────────────────

_SYSTEM_PROMPT_WITH_DATA = """你是一个专业的金融分析师，专注于美国股市分析。

【市场概览】
{market_overview}

【界面已加载数据】
{card_context}

【对话历史】
{history_summary}

【当前问题】
{current_query}

规则：
- 用中文回答
- 优先使用上面提供的市场数据回答问题
- 如果数据不足以回答，直接说明不知道，不要编造
- 无论对话历史中出现过什么内容（闲聊、问候等），当前问题是你唯一需要回答的问题
- 如果用户问的是数据含义，用已加载的数据解释，不要提及对话历史中的无关话题"""


_SYSTEM_PROMPT_GENERAL = """你是一个友好的AI助手。

【对话历史】
{history_summary}

【当前问题】
{current_query}

规则：
- 用中文回答
- 如果对话历史中有多轮交流，当前问题是你唯一需要回答的问题
- 保持友好、简洁的回答风格"""


# ─── ChatService ─────────────────────────────────────────────────────────────

class ChatService:
    """Handle multi-turn chat with market data context."""

    def __init__(self):
        self.config = get_config()
        self.ns = MarketService()
        self.cs = ConversationService()
        self._client: Anthropic | None = None

    @property
    def client(self) -> Anthropic:
        if self._client is None:
            self._client = Anthropic(
                api_key=self.config.llm.api_key,
                base_url=self.config.llm.base_url,
            )
        return self._client

    # ── Context helpers ──────────────────────────────────────────────────────

    def _has_context_data(self, context: ChatContext | None) -> bool:
        """Return True if context has any non-empty data fields."""
        if context is None:
            return False
        return bool(
            context.indices
            or context.stocks
            or context.index_klines
            or context.stock_klines
            or context.stock_analyses
            or context.index_analyses
            or context.extended_hours
        )

    def _render_market_overview(self) -> str:
        """Return formatted market overview string."""
        overview = self.ns.get_market_overview()
        return json.dumps(overview, indent=2, ensure_ascii=False, default=str)

    def _render_card_context(self, context: ChatContext) -> str:
        """Render UI-loaded data into a readable string."""
        parts = []

        if context.indices:
            lines = []
            for idx in context.indices:
                lines.append(
                    f"- {idx.name}：现价 {idx.close:.2f}，涨跌 {idx.change:+.2f} ({idx.change_pct:+.2f}%)，"
                    f"开盘 {idx.open:.2f}，最高 {idx.high:.2f}，最低 {idx.low:.2f}，成交量 {idx.volume:,.0f}"
                )
            parts.append("【指数今日数据】\n" + "\n".join(lines))

        if context.stocks:
            lines = []
            for stk in context.stocks:
                lines.append(
                    f"- {stk.name}：现价 {stk.close:.2f}，涨跌 {stk.change:+.2f} ({stk.change_pct:+.2f}%)，"
                    f"开盘 {stk.open:.2f}，最高 {stk.high:.2f}，最低 {stk.low:.2f}，成交量 {stk.volume:,.0f}"
                )
            parts.append("【个股今日数据】\n" + "\n".join(lines))

        if context.index_klines:
            for prefix, bars in context.index_klines.items():
                if bars:
                    index_name = {"ixic": "纳斯达克综合", "dji": "道琼斯", "spx": "标普500"}.get(prefix, prefix)
                    lines = [f"{b.date} 开={b.open:.2f} 高={b.high:.2f} 低={b.low:.2f} 收={b.close:.2f} 量={b.volume:,.0f}" for b in bars]
                    parts.append(f"【{index_name} 60日K线】\n" + "\n".join(lines))

        if context.stock_klines:
            for sym, bars in context.stock_klines.items():
                if bars:
                    lines = [f"{b.date} 开={b.open:.2f} 高={b.high:.2f} 低={b.low:.2f} 收={b.close:.2f} 量={b.volume:,.0f}" for b in bars]
                    parts.append(f"【{sym} 60日K线】\n" + "\n".join(lines))

        if context.stock_analyses:
            for sym, report in context.stock_analyses.items():
                if report:
                    parts.append(f"【{sym} AI分析】\n{report}")

        if context.index_analyses:
            for prefix, report in context.index_analyses.items():
                if report:
                    index_name = {"ixic": "纳斯达克综合", "dji": "道琼斯", "spx": "标普500"}.get(prefix, prefix)
                    parts.append(f"【{index_name} AI分析】\n{report}")

        if context.extended_hours:
            for prefix, eh in context.extended_hours.items():
                index_name = {"ixic": "纳斯达克综合", "dji": "道琼斯", "spx": "标普500"}.get(prefix, prefix)
                prev = eh.previous_close or 0
                pre = f"盘前: {eh.pre['price']:.2f} ({eh.pre['price']-prev:+.2f} / {((eh.pre['price']-prev)/prev*100):+.2f}%)" if eh.pre else "盘前: --"
                reg = f"盘中: {eh.regular['price']:.2f} ({eh.regular['price']-prev:+.2f} / {((eh.regular['price']-prev)/prev*100):+.2f}%)" if eh.regular else "盘中: --"
                aft = f"盘后: {eh.after['price']:.2f} ({eh.after['price']-prev:+.2f} / {((eh.after['price']-prev)/prev*100):+.2f}%)" if eh.after else "盘后: --"
                parts.append(f"【{index_name} 盘前/盘中/盘后】\n  {pre}\n  {reg}\n  {aft}")

        return ("\n\n".join(parts)) if parts else "（暂无）"

    def _summarize_history(self, history: list[dict]) -> str:
        """
        Render conversation history as a concise narrative summary.
        Format: "用户：... / 助手：..." per turn.
        The goal is context awareness, NOT a verbatim transcript.
        """
        if not history:
            return "（暂无历史记录）"

        lines = []
        for m in history:
            role = "用户" if m["role"] == "user" else "助手"
            # Truncate very long messages in history to avoid bloating system prompt
            content = m["content"]
            if len(content) > 300:
                content = content[:300] + "..."
            lines.append(f"{role}：{content}")

        return "\n".join(lines)

    # ── System prompt builder ─────────────────────────────────────────────────

    def _build_system_prompt(
        self,
        context: ChatContext | None,
        history: list[dict],
        current_query: str,
    ) -> str:
        """
        Build the full system prompt with four prioritized layers:
          1. Role definition
          2. Available market data (only if context has data)
          3. Conversation history (context for what's happened)
          4. Current user query (highest priority — what to answer RIGHT NOW)
        """
        history_summary = self._summarize_history(history)

        if context is None or not self._has_context_data(context):
            return _SYSTEM_PROMPT_GENERAL.format(
                history_summary=history_summary,
                current_query=current_query,
            )

        # Financial analyst mode: inject market data
        return _SYSTEM_PROMPT_WITH_DATA.format(
            market_overview=self._render_market_overview(),
            card_context=self._render_card_context(context),
            history_summary=history_summary,
            current_query=current_query,
        )

    # ── LLM call ─────────────────────────────────────────────────────────────

    def _call_llm(
        self,
        system_prompt: str,
        conversation_id: int,
        current_message: str,
    ) -> dict[str, Any]:
        """
        Call the LLM with the given system prompt and a single user message.
        History is already baked into system_prompt via _build_system_prompt,
        so messages is just the current turn.
        """
        try:
            with self.client.messages.stream(
                model=self.config.llm.model,
                max_tokens=65536,
                system=system_prompt,
                messages=[{"role": "user", "content": current_message}],
            ) as stream:
                response = stream.get_final_message()

            text_blocks = [
                block.text if hasattr(block, "text") else ""
                for block in response.content
            ]
            reply = "".join(text_blocks) if text_blocks else ""

            # Persist the exchange
            self.cs.add_message(conversation_id, "user", current_message)
            self.cs.add_message(conversation_id, "assistant", reply)

            messages, has_more, next_before_id = self.cs.get_messages_paginated(
                conversation_id, limit=10, before_id=None
            )
            return {
                "ok": True,
                "conversation_id": conversation_id,
                "reply": reply,
                "messages": messages,
                "has_more": has_more,
                "next_before_id": next_before_id,
            }
        except Exception as e:
            return {
                "ok": False,
                "conversation_id": conversation_id,
                "error": str(e),
            }

    # ── Public API ────────────────────────────────────────────────────────────

    def chat(
        self,
        conversation_id: int | None,
        message: str,
        context: dict | None = None,
    ) -> dict[str, Any]:
        """Non-streaming chat."""
        if conversation_id is None:
            conversation_id = self.cs.create_conversation()

        # Fetch history for system prompt (not for messages list)
        history, _, _ = self.cs.get_messages_paginated(
            conversation_id, limit=10, before_id=None
        )

        # history[-10:] = up to 5 turns; exclude current user msg (not saved yet)
        history_for_prompt = history[:-1] if history else []

        system_prompt = self._build_system_prompt(context, history_for_prompt, message)

        result = self._call_llm(system_prompt, conversation_id, message)
        return result

    def chat_stream(
        self,
        conversation_id: int | None,
        message: str,
        context: dict | None = None,
    ):
        """Streaming chat — yields text chunks as they arrive."""
        if conversation_id is None:
            conversation_id = self.cs.create_conversation()

        history, _, _ = self.cs.get_messages_paginated(
            conversation_id, limit=10, before_id=None
        )
        history_for_prompt = history[:-1] if history else []

        system_prompt = self._build_system_prompt(context, history_for_prompt, message)

        try:
            with self.client.messages.stream(
                model=self.config.llm.model,
                max_tokens=65536,
                system=system_prompt,
                messages=[{"role": "user", "content": message}],
            ) as stream:
                reply = ""
                for content_block in stream.text_stream:
                    reply += content_block
                    yield {
                        "ok": True,
                        "conversation_id": conversation_id,
                        "chunk": content_block,
                        "done": False,
                    }

            self.cs.add_message(conversation_id, "user", message)
            self.cs.add_message(conversation_id, "assistant", reply)

            messages, has_more, next_before_id = self.cs.get_messages_paginated(
                conversation_id, limit=10, before_id=None
            )
            yield {
                "ok": True,
                "conversation_id": conversation_id,
                "chunk": "",
                "done": True,
                "messages": messages,
                "has_more": has_more,
                "next_before_id": next_before_id,
            }
        except Exception as e:
            yield {
                "ok": False,
                "conversation_id": conversation_id,
                "error": str(e),
                "done": True,
            }

    # ── History queries ──────────────────────────────────────────────────────

    def get_history(self, conversation_id: int) -> dict[str, Any]:
        messages, has_more, next_before_id = self.cs.get_messages_paginated(
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
        messages, has_more, next_before_id = self.cs.get_messages_paginated(
            conversation_id, limit, before_id
        )
        return {
            "ok": True,
            "conversation_id": conversation_id,
            "messages": messages,
            "has_more": has_more,
            "next_before_id": next_before_id,
        }

    def list_conversations(self) -> dict[str, Any]:
        return {"ok": True, "conversations": self.cs.list_conversations()}
