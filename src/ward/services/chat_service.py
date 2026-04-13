"""Interactive chat service — supports multi-turn conversations with market data context."""

from __future__ import annotations

import json
from typing import Any

from anthropic import Anthropic

from ward.core.config import get_config
from ward.schemas.models import ChatContext
from ward.services.db.conversation_service import ConversationService
from ward.services.nasdaq_service import MarketService


SYSTEM_PROMPT = """你是一个专业的金融分析师，专注于美国股市分析。
你可以参考以下实时市场数据回答用户问题：

{market_data}

{card_context}

规则：
- 回答用中文
- 如果用户问到具体的股价、指数、涨跌幅，用上面提供的数据
- 如果数据不足以回答，可以说明不知道
- 不要编造任何数据或事实"""


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

    def _build_system_prompt(self, context: ChatContext | None = None) -> str:
        overview = self.ns.get_market_overview()
        card_ctx = ""
        if context:
            parts = []
            if context.indices:
                lines = []
                for idx in context.indices:
                    lines.append(
                        f"- {idx.name}：现价 {idx.close:.2f}，涨跌 {idx.change:+.2f} ({idx.change_pct:+.2f}%)，"
                        f"开盘 {idx.open:.2f}，最高 {idx.high:.2f}，最低 {idx.low:.2f}，成交量 {idx.volume:,.0f}"
                    )
                parts.append("【界面已展示的指数今日数据】\n" + "\n".join(lines))
            if context.stocks:
                lines = []
                for stk in context.stocks:
                    lines.append(
                        f"- {stk.name}：现价 {stk.close:.2f}，涨跌 {stk.change:+.2f} ({stk.change_pct:+.2f}%)，"
                        f"开盘 {stk.open:.2f}，最高 {stk.high:.2f}，最低 {stk.low:.2f}，成交量 {stk.volume:,.0f}"
                    )
                parts.append("【界面已查询的个股今日数据】\n" + "\n".join(lines))
            if context.index_klines:
                for prefix, bars in context.index_klines.items():
                    if bars:
                        index_name = {k: v for k, v in [("ixic", "Nasdaq 综合"), ("dji", "道琼斯"), ("spx", "标普500")]}.get(prefix, prefix)
                        lines = [f"{b.date} open={b.open:.2f} high={b.high:.2f} low={b.low:.2f} close={b.close:.2f} vol={b.volume:,.0f}" for b in bars]
                        parts.append(f"【{index_name} 60日K线数据】\n" + "\n".join(lines))
            if context.stock_klines:
                for sym, bars in context.stock_klines.items():
                    if bars:
                        lines = [f"{b.date} open={b.open:.2f} high={b.high:.2f} low={b.low:.2f} close={b.close:.2f} vol={b.volume:,.0f}" for b in bars]
                        parts.append(f"【{sym} 60日K线数据】\n" + "\n".join(lines))
            if context.stock_analyses:
                for sym, report in context.stock_analyses.items():
                    if report:
                        parts.append(f"【{sym} AI分析报告】\n{report}")
            if context.index_analyses:
                for prefix, report in context.index_analyses.items():
                    if report:
                        index_name = {"ixic": "纳斯达克综合", "dji": "道琼斯", "spx": "标普500"}.get(prefix, prefix)
                        parts.append(f"【{index_name} AI分析报告】\n{report}")
            if context.extended_hours:
                for prefix, eh in context.extended_hours.items():
                    index_name = {"ixic": "纳斯达克综合", "dji": "道琼斯", "spx": "标普500"}.get(prefix, prefix)
                    prev = eh.previous_close or 0
                    pre_line = f"盘前: {eh.pre['price']:.2f} ({eh.pre['price']-prev:+.2f} / {((eh.pre['price']-prev)/prev*100):+.2f}%)" if eh.pre else "盘前: --"
                    reg_line = f"盘中: {eh.regular['price']:.2f} ({eh.regular['price']-prev:+.2f} / {((eh.regular['price']-prev)/prev*100):+.2f}%)" if eh.regular else "盘中: --"
                    aft_line = f"盘后: {eh.after['price']:.2f} ({eh.after['price']-prev:+.2f} / {((eh.after['price']-prev)/prev*100):+.2f}%)" if eh.after else "盘后: --"
                    parts.append(f"【{index_name} 盘前/盘中/盘后】\n  {pre_line}\n  {reg_line}\n  {aft_line}")
            if parts:
                card_ctx = "\n\n当前界面已加载的数据（可优先参考）：\n" + "\n\n".join(parts)
        return SYSTEM_PROMPT.format(
            market_data=json.dumps(overview, indent=2, ensure_ascii=False, default=str),
            card_context=card_ctx,
        )

    def chat(self, conversation_id: int | None, message: str, context: dict | None = None) -> dict[str, Any]:
        """Send a message and return the assistant reply."""
        # Create new conversation if needed
        if conversation_id is None:
            conversation_id = self.cs.create_conversation()

        # Add user message
        self.cs.add_message(conversation_id, "user", message)

        # Cursor-based: fetch last 20 messages using max id as anchor
        # We pass before_id=None to get the newest messages directly via SQL
        history, _, _ = self.cs.get_messages_paginated(conversation_id, limit=20, before_id=None)

        llm_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in history
        ]

        try:
            with self.client.messages.stream(
                model=self.config.llm.model,
                max_tokens=65536,
                system=self._build_system_prompt(context),
                messages=llm_messages,
            ) as stream:
                response = stream.get_final_message()
            text_blocks = [
                block.text if hasattr(block, "text") else ""
                for block in response.content
            ]
            reply = "".join(text_blocks) if text_blocks else ""

            # Save assistant reply
            self.cs.add_message(conversation_id, "assistant", reply)

            messages, has_more, next_before_id = self.cs.get_messages_paginated(conversation_id, limit=20, before_id=None)
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

    def chat_stream(self, conversation_id: int | None, message: str, context: dict | None = None):
        """Streaming chat — yields text chunks as they arrive."""
        if conversation_id is None:
            conversation_id = self.cs.create_conversation()

        self.cs.add_message(conversation_id, "user", message)

        history, _, _ = self.cs.get_messages_paginated(conversation_id, limit=20)
        llm_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in history
        ]

        try:
            with self.client.messages.stream(
                model=self.config.llm.model,
                max_tokens=65536,
                system=self._build_system_prompt(context),
                messages=llm_messages,
            ) as stream:
                reply = ""
                for content_block in stream.text_stream:
                    reply += content_block
                    yield {"ok": True, "conversation_id": conversation_id, "chunk": content_block, "done": False}

            self.cs.add_message(conversation_id, "assistant", reply)
            messages, has_more, next_before_id = self.cs.get_messages_paginated(conversation_id, limit=20, before_id=None)
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
            yield {"ok": False, "conversation_id": conversation_id, "error": str(e), "done": True}

    def get_history(self, conversation_id: int) -> dict[str, Any]:
        messages, has_more, next_before_id = self.cs.get_messages_paginated(conversation_id, limit=20, before_id=None)
        return {
            "ok": True,
            "conversation_id": conversation_id,
            "messages": messages,
            "has_more": has_more,
            "next_before_id": next_before_id,
        }

    def get_history_paginated(self, conversation_id: int, limit: int = 20, before_id: int | None = None) -> dict[str, Any]:
        messages, has_more, next_before_id = self.cs.get_messages_paginated(conversation_id, limit, before_id)
        return {
            "ok": True,
            "conversation_id": conversation_id,
            "messages": messages,
            "has_more": has_more,
            "next_before_id": next_before_id,
        }

    def list_conversations(self) -> dict[str, Any]:
        return {"ok": True, "conversations": self.cs.list_conversations()}
