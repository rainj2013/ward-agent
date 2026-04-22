"""Interactive chat service — supports multi-turn conversations with market data context."""

from __future__ import annotations

import json
import re
from typing import Any

from anthropic import Anthropic

from ward.core.config import get_config
from ward.schemas.models import ChatContext
from ward.services.db.conversation_service import ConversationService
from ward.services.nasdaq_service import MarketService


# ─── Tool Definitions ─────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "get_stock_quote",
        "description": "获取美股个股的实时行情（今日开盘价、收盘价、涨跌幅、成交量等）。当用户问起某只股票的当前价格或今日表现时调用。",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "股票代码（美股），如 AAPL、TSLA、MSFT、NVDA"
                }
            },
            "required": ["symbol"]
        }
    },
    {
        "name": "get_stock_kline",
        "description": "获取美股个股的历史K线数据（60日日K线，OHLCV格式）。当用户问起某只股票的历史走势、近期趋势时调用。",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "股票代码，如 AAPL、TSLA"
                },
                "days": {
                    "type": "integer",
                    "description": "天数，默认60",
                    "default": 60
                }
            },
            "required": ["symbol"]
        }
    },
    {
        "name": "get_stock_analyze",
        "description": "获取AI驱动的个股分析报告（含技术面、基本面、市场情绪综合分析）。当用户问某只股票的AI分析或投资建议时调用。",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "股票代码，如 AAPL、TSLA"
                }
            },
            "required": ["symbol"]
        }
    },
    {
        "name": "get_index_analyze",
        "description": "获取AI驱动的指数分析报告。当用户问起标普500、纳斯达克综合、道琼斯某指数的AI分析时调用。",
        "input_schema": {
            "type": "object",
            "properties": {
                "prefix": {
                    "type": "string",
                    "description": "指数前缀：spx（标普500）、ixic（纳斯达克综合）、dji（道琼斯）",
                    "enum": ["spx", "ixic", "dji"]
                }
            },
            "required": ["prefix"]
        }
    },
    {
        "name": "get_market_overview",
        "description": "获取美股三大指数（标普500、纳斯达克、道琼斯）和黄金的今日行情概览。当用户问起今日市场整体表现或各指数涨跌时调用。",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_extended_hours",
        "description": "获取指数或个股的盘前、盘中、盘后价格数据。当用户问起盘前/盘后交易情况时调用。",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "指数前缀（spx/ixic/dji）或股票代码（如 AAPL）"
                }
            },
            "required": ["symbol"]
        }
    },
]


# ─── System Prompt Templates ─────────────────────────────────────────────────

_SYSTEM_PROMPT_WITH_DATA = """你是一个专业的金融分析师，专注于美国股市分析。你有以下工具可以调用来获取实时数据：

{tool_descriptions}

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
- 优先使用工具获取最新数据，而不是依赖对话历史或已有数据
- 如果界面已加载的数据足以回答，直接使用即可
- 如果数据不足，使用上述工具获取最新数据后再回答
- 工具调用完成后，用返回的真实数据回答用户问题
- 不要编造任何数据或事实
- 无论对话历史中出现过什么内容，当前问题是你唯一需要回答的问题"""


_SYSTEM_PROMPT_GENERAL = """你是一个友好的AI助手，你可以使用工具获取实时信息。

{tool_descriptions}

【对话历史】
{history_summary}

【当前问题】
{current_query}

规则：
- 用中文回答
- 如果需要实时市场数据，使用工具获取
- 如果对话历史中有多轮交流，当前问题是你唯一需要回答的问题
- 保持友好、简洁的回答风格"""


# ─── ChatService ─────────────────────────────────────────────────────────────

class ChatService:
    """Handle multi-turn chat with market data context and tool use."""

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

    # ── Tool registry ─────────────────────────────────────────────────────────

    def _get_tool_descriptions(self) -> str:
        """Render all available tools as a readable description string."""
        lines = []
        for t in TOOLS:
            lines.append(f"- {t['name']}: {t['description']}")
        return "\n".join(lines)

    def _execute_tool(self, name: str, arguments: dict) -> dict[str, Any]:
        """Execute a tool by name and return its result."""
        from ward.services.stock_service import StockService
        from ward.services.index_service import IndexService
        from ward.services.report_service import ReportService

        ss = StockService()
        is_ = IndexService()
        rs = ReportService()

        try:
            if name == "get_stock_quote":
                sym = arguments.get("symbol", "").upper()
                result = ss.get_quote(sym)
                if result.get("ok"):
                    d = result["data"]
                    return {
                        "ok": True,
                        "symbol": sym,
                        "name": d.get("name", sym),
                        "close": d.get("close"),
                        "change": d.get("change"),
                        "change_pct": d.get("change_pct"),
                        "open": d.get("open"),
                        "high": d.get("high"),
                        "low": d.get("low"),
                        "volume": d.get("volume"),
                    }
                return {"ok": False, "error": result.get("error", "获取失败")}

            elif name == "get_stock_kline":
                sym = arguments.get("symbol", "").upper()
                days = arguments.get("days", 60)
                result = ss.get_kline(sym, days)
                if result.get("ok"):
                    return {"ok": True, "symbol": sym, "bars": result.get("data", [])}
                return {"ok": False, "error": result.get("error", "获取失败")}

            elif name == "get_stock_analyze":
                sym = arguments.get("symbol", "").upper()
                result = ss.generate_analysis(sym)
                if result.get("ok"):
                    return {
                        "ok": True,
                        "symbol": sym,
                        "name": result.get("name", sym),
                        "report": result.get("report", ""),
                        "data": result.get("data"),
                    }
                return {"ok": False, "error": result.get("error", "分析失败")}

            elif name == "get_index_analyze":
                prefix = arguments.get("prefix", "")
                result = is_.generate_analysis(prefix)
                if result.get("ok"):
                    return {
                        "ok": True,
                        "prefix": prefix,
                        "name": result.get("name", prefix),
                        "report": result.get("report", ""),
                        "data": result.get("data"),
                    }
                return {"ok": False, "error": result.get("error", "分析失败")}

            elif name == "get_market_overview":
                return self.ns.get_market_overview()

            elif name == "get_extended_hours":
                sym = arguments.get("symbol", "")
                result = ss.get_extended_price(sym)
                if result.get("ok"):
                    return {
                        "ok": True,
                        "symbol": sym,
                        "date": result.get("date"),
                        "pre_market": result.get("pre_market"),
                        "regular": result.get("regular"),
                        "after_hours": result.get("after_hours"),
                        "previous_close": result.get("previous_close"),
                    }
                return {"ok": False, "error": result.get("error", "获取失败")}

            else:
                return {"ok": False, "error": f"未知工具: {name}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

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
        """
        if not history:
            return "（暂无历史记录）"

        lines = []
        for m in history:
            role = "用户" if m["role"] == "user" else "助手"
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
          1. Role definition + tool descriptions
          2. Available market data (only if context has data)
          3. Conversation history (context for what's happened)
          4. Current user query (highest priority — what to answer RIGHT NOW)
        """
        history_summary = self._summarize_history(history)
        tool_descriptions = self._get_tool_descriptions()

        if context is None or not self._has_context_data(context):
            return _SYSTEM_PROMPT_GENERAL.format(
                tool_descriptions=tool_descriptions,
                history_summary=history_summary,
                current_query=current_query,
            )

        # Financial analyst mode: inject market data
        return _SYSTEM_PROMPT_WITH_DATA.format(
            tool_descriptions=tool_descriptions,
            market_overview=self._render_market_overview(),
            card_context=self._render_card_context(context),
            history_summary=history_summary,
            current_query=current_query,
        )

    # ── Tool-use streaming ────────────────────────────────────────────────────

    def _stream_with_tools(
        self,
        system_prompt: str,
        conversation_id: int,
        current_message: str,
    ):
        """
        Stream response with tool use support.
        Yields dicts like:
          - {"type": "thinking", "content": "..."}
          - {"type": "tool_call", "name": "...", "input": {...}}
          - {"type": "tool_result", "name": "...", "result": {...}}
          - {"type": "text", "content": "..."}
          - {"type": "done", ...}
        """
        accumulated_tool_input: dict | None = None
        accumulated_tool_name: str | None = None
        accumulated_tool_args: dict | None = None
        tool_executed: bool = False
        tool_use_content_blocks: list = []  # track content blocks for tool_use
        text_content_blocks: list = []  # track text content blocks

        with self.client.messages.stream(
            model=self.config.llm.model,
            max_tokens=65536,
            system=system_prompt,
            messages=[{"role": "user", "content": current_message}],
            tools=TOOLS,
        ) as stream:
            for event in stream:
                event_type = type(event).__name__

                # ── Thinking (模型在思考) ──────────────────────────────────
                if event_type == "ThinkingEvent":
                    yield {
                        "type": "thinking",
                        "content": event.thinking,
                    }
                    continue

                # ── Text delta ──────────────────────────────────────────────
                if event_type == "RawContentBlockDeltaEvent" and hasattr(event.delta, "text"):
                    yield {"type": "text", "content": event.delta.text}
                    continue

                # ── Content block start (text or tool_use) ──────────────────
                if event_type == "RawContentBlockStartEvent":
                    block_type = event.content_block.type if hasattr(event.content_block, "type") else str(event.content_block)
                    if "tool_use" in block_type or "tool_use" in str(event.content_block):
                        # Get tool name
                        tc = event.content_block
                        name = getattr(tc, "name", None) or str(getattr(tc, "id", "")) or ""
                        accumulated_tool_name = name
                        accumulated_tool_input = ""
                        accumulated_tool_args = None
                        tool_executed = False
                        tool_use_content_blocks.append(event.index)
                    else:
                        text_content_blocks.append(event.index)
                    continue

                # ── Tool input delta (streaming JSON) ─────────────────────────
                if event_type == "InputJsonEvent":
                    partial = getattr(event, "partial_json", None) or getattr(event, "json", "") or ""
                    if partial:
                        accumulated_tool_input = (accumulated_tool_input or "") + partial
                    yield {
                        "type": "tool_call",
                        "name": accumulated_tool_name,
                        "input": partial,  # streaming partial
                    }
                    continue

                # ── Message stop — execute tool if not yet done via content block ──
                if event_type == "ParsedMessageStopEvent":
                    if accumulated_tool_name and not tool_executed and accumulated_tool_input is not None:
                        try:
                            accumulated_tool_args = json.loads(accumulated_tool_input)
                        except json.JSONDecodeError:
                            accumulated_tool_args = {"raw": accumulated_tool_input}
                        tool_result = self._execute_tool(accumulated_tool_name, accumulated_tool_args)
                        yield {
                            "type": "tool_result",
                            "name": accumulated_tool_name,
                            "result": tool_result,
                        }
                        yield from self._continue_after_tool(
                            system_prompt,
                            current_message,
                            accumulated_tool_name,
                            accumulated_tool_args,
                            tool_result,
                        )
                        tool_executed = True
                    continue

                # ── Content block stop ───────────────────────────────────────
                if event_type == "ParsedContentBlockStopEvent":
                    idx = event.index
                    if idx in tool_use_content_blocks and accumulated_tool_name and not tool_executed:
                        # Try to parse accumulated tool input
                        if accumulated_tool_input is not None:
                            try:
                                accumulated_tool_args = json.loads(accumulated_tool_input)
                            except json.JSONDecodeError:
                                accumulated_tool_args = {"raw": accumulated_tool_input}
                            tool_result = self._execute_tool(accumulated_tool_name, accumulated_tool_args)
                            yield {
                                "type": "tool_result",
                                "name": accumulated_tool_name,
                                "result": tool_result,
                            }
                            yield from self._continue_after_tool(
                                system_prompt,
                                current_message,
                                accumulated_tool_name,
                                accumulated_tool_args,
                                tool_result,
                            )
                            tool_executed = True
                        accumulated_tool_name = None
                        accumulated_tool_input = None
                        accumulated_tool_args = None
                    continue

        # Fallback: yield done
        yield {"type": "done"}

    def _continue_after_tool(
        self,
        system_prompt: str,
        original_message: str,
        tool_name: str,
        tool_args: dict,
        tool_result: dict,
    ):
        """
        After executing a tool, continue the conversation with the result injected.
        This re-prompts the LLM with the tool result so it can produce a final answer.
        """
        tool_result_content = json.dumps(tool_result, ensure_ascii=False, default=str)

        continuation_messages = [
            {"role": "user", "content": original_message},
            {
                "role": "assistant",
                "content": "",  # empty, tool result comes via tool use
            },
            {
                "role": "user",
                "content": f"<tool_result name=\"{tool_name}\">{tool_result_content}</tool_result>\n\n请根据以上工具返回的结果，用中文回答用户的问题。"
            },
        ]

        with self.client.messages.stream(
            model=self.config.llm.model,
            max_tokens=65536,
            system=system_prompt,
            messages=continuation_messages,
            tools=TOOLS,
        ) as stream:
            for event in stream:
                event_type = type(event).__name__

                if event_type == "ThinkingEvent":
                    yield {"type": "thinking", "content": event.thinking}
                    continue

                if event_type == "RawContentBlockDeltaEvent" and hasattr(event.delta, "text"):
                    yield {"type": "text", "content": event.delta.text}
                    continue

                if event_type == "ParsedMessageStopEvent":
                    yield {"type": "done"}
                    continue

    # ── Public API ──────────────────────────────────────────────────────────

    def chat_stream(
        self,
        conversation_id: int | None,
        message: str,
        context: dict | None = None,
    ):
        """Streaming chat with tool use — yields structured events as SSE."""
        if conversation_id is None:
            conversation_id = self.cs.create_conversation()

        history, _, _ = self.cs.get_messages_paginated(
            conversation_id, limit=10, before_id=None
        )
        history_for_prompt = history[:-1] if history else []

        system_prompt = self._build_system_prompt(context, history_for_prompt, message)

        try:
            reply_text = ""
            for event in self._stream_with_tools(system_prompt, conversation_id, message):
                etype = event.get("type")

                if etype == "thinking":
                    # Stream thinking as a special chunk (not final text)
                    yield {
                        "ok": True,
                        "conversation_id": conversation_id,
                        "chunk": "",
                        "thinking": event["content"],
                        "done": False,
                    }
                    continue

                if etype == "tool_call":
                    yield {
                        "ok": True,
                        "conversation_id": conversation_id,
                        "chunk": "",
                        "tool_call": {
                            "name": event.get("name"),
                            "input": event.get("input"),
                        },
                        "done": False,
                    }
                    continue

                if etype == "tool_result":
                    yield {
                        "ok": True,
                        "conversation_id": conversation_id,
                        "chunk": "",
                        "tool_result": {
                            "name": event.get("name"),
                            "result": event.get("result"),
                        },
                        "done": False,
                    }
                    continue

                if etype == "text":
                    reply_text += event["content"]
                    yield {
                        "ok": True,
                        "conversation_id": conversation_id,
                        "chunk": event["content"],
                        "done": False,
                    }
                    continue

                if etype == "done":
                    # Persist completed exchange
                    self.cs.add_message(conversation_id, "user", message)
                    self.cs.add_message(conversation_id, "assistant", reply_text)

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
                    continue

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
