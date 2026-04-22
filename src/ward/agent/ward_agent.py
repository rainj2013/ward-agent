"""Ward Mini-Agent wrapper — provides SSE streaming interface using Mini-Agent Agent."""

from __future__ import annotations

from typing import Any, AsyncGenerator

from ward.mini_agent.llm import LLMClient
from ward.mini_agent.llm.llm_wrapper import LLMClient as MiniLLMClient
from ward.mini_agent.schema import LLMProvider, Message
from ward.mini_agent.agent import Agent as MiniAgent

from ward.agent.ward_tools import get_all_tools


# ── System Prompt ──────────────────────────────────────────────────────────────

WARD_SYSTEM_PROMPT = """你是一个专业的美国股市分析助手，专注于美股个股、指数、黄金的实时行情和AI分析。

你有以下工具可以调用：
- get_stock_quote: 获取个股实时行情（价格、涨跌幅、成交量等）
- get_stock_kline: 获取个股历史K线数据（仅限个股，如AAPL、TSLA，不适用于指数）
- get_stock_analyze: 获取个股AI分析报告
- get_index_kline: 获取指数K线数据（仅限指数：spx=标普500、ixic=纳斯达克、dji=道琼斯，不适用于个股）
- get_index_analyze: 获取指数AI分析报告
- get_market_overview: 获取三大指数和黄金的今日行情
- get_extended_hours: 获取盘前/盘后交易数据

重要规则：
- 个股用 stock 工具（symbol 如 AAPL、TSLA），指数用 index 工具（prefix 如 spx、ixic、dji）
- get_stock_kline 不能用于指数，get_index_kline 不能用于个股
- 优先使用上述[页面已有数据]中的数据直接回答，只有当上下文数据不足时才调用工具查询
- 用中文回答用户问题
- 不要编造任何数据，所有数据必须来自工具返回结果
- 如果工具返回的数据不足（如某字段为null），如实说明，不要填充
- 回答要简洁、专业，突出重点数据"""


# ── WardMiniAgent ──────────────────────────────────────────────────────────────

class WardMiniAgent:
    """
    Wrapper around Mini-Agent's Agent class that provides the same SSE streaming
    interface as the original ChatService.

    External API (synchronous generators for FastAPI):
      - chat_stream(conversation_id, message, context) -> AsyncGenerator[dict, None]
    """

    def __init__(self):
        from ward.core.config import get_config

        cfg = get_config()

        # Build Mini-Agent LLM client
        self._llm_client: LLMClient = MiniLLMClient(
            api_key=cfg.llm.api_key,
            api_base=cfg.llm.base_url,
            model=cfg.llm.model,
            provider=LLMProvider.ANTHROPIC,
        )

        # Build agent with Ward tools
        self._agent: MiniAgent = MiniAgent(
            llm_client=self._llm_client,
            system_prompt=WARD_SYSTEM_PROMPT,
            tools=get_all_tools(),
            max_steps=20,
            workspace_dir="./workspace",
            token_limit=80000,
        )

    def _build_context_text(self, ctx: Any) -> str:
        """Format ChatContext into a readable text block for the system prompt."""
        if ctx is None:
            return ""

        parts = ["[页面已有数据]"]

        # Index klines
        if hasattr(ctx, "index_klines") and ctx.index_klines:
            for prefix, bars in ctx.index_klines.items():
                if not bars:
                    continue
                # latest bar
                bar = bars[-1]
                parts.append(
                    f"- {prefix.upper()}指数K线: 最新日期={bar.get('date','?')}, "
                    f"收盘={bar.get('close','?')}, 涨跌={bar.get('change','?')}({bar.get('changePercent','?')})"
                )

        # Stock klines
        if hasattr(ctx, "stock_klines") and ctx.stock_klines:
            for symbol, bars in ctx.stock_klines.items():
                if not bars:
                    continue
                bar = bars[-1]
                parts.append(
                    f"- {symbol.upper()}K线: 最新日期={bar.get('date','?')}, "
                    f"收盘={bar.get('close','?')}, 涨跌={bar.get('change','?')}({bar.get('changePercent','?')})"
                )

        # Stock quotes (个股实时行情)
        if hasattr(ctx, "stocks") and ctx.stocks:
            for stock in ctx.stocks:
                parts.append(
                    f"- {stock.name}({stock.symbol})行情: "
                    f"现价={stock.close}, 涨跌={stock.change}({stock.change_pct}%), "
                    f"开盘={stock.open}, 最高={stock.high}, 最低={stock.low}, 成交量={stock.volume}"
                )

        # Index analyses
        if hasattr(ctx, "index_analyses") and ctx.index_analyses:
            for prefix, report in ctx.index_analyses.items():
                snippet = report[:100].replace("\n", " ") if report else "无"
                parts.append(f"- {prefix.upper()}指数AI分析: {snippet}...")

        # Stock analyses
        if hasattr(ctx, "stock_analyses") and ctx.stock_analyses:
            for symbol, report in ctx.stock_analyses.items():
                snippet = report[:100].replace("\n", " ") if report else "无"
                parts.append(f"- {symbol.upper()}AI分析: {snippet}...")

        # Extended hours
        if hasattr(ctx, "extended_hours") and ctx.extended_hours:
            for prefix, eh in ctx.extended_hours.items():
                parts.append(
                    f"- {prefix.upper()}盘后/盘前: 现价={getattr(eh,'price',None)}, "
                    f"涨跌={getattr(eh,'change',None)}({getattr(eh,'changePercent',None)})"
                )

        return "\n".join(parts) if len(parts) > 1 else ""

    def _inject_context(self, context: Any | None):
        """Re-inject page context into the system prompt (called every request)."""
        ctx_text = self._build_context_text(context)
        if not ctx_text:
            return

        marker = "[页面已有数据]"
        sys_msg = self._agent.messages[0]
        # Strip old block if present
        if marker in sys_msg.content:
            sys_msg.content = sys_msg.content[: sys_msg.content.index(marker)]
        # Append fresh context
        sys_msg.content = sys_msg.content.rstrip() + "\n\n" + ctx_text

    def reset_conversation(self):
        """Reset the agent's message history for a fresh conversation."""
        self._agent.messages = [Message(role="system", content=WARD_SYSTEM_PROMPT)]

    async def chat_stream(
        self,
        conversation_id: int,
        message: str,
        context: Any | None,
        cancel_event: Any | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Stream agent response chunks via SSE-compatible dicts.

        Yields dicts with keys:
          - conversation_id: int
          - ok: bool
          - chunk: str (text delta)
          - thinking: str (thinking delta)
          - tool_call: dict (tool invocation start)
          - tool_result: dict (tool execution result)
          - done: bool
        """
        # Reset history if new conversation
        if conversation_id == 0:
            self.reset_conversation()

        # Inject page context into system prompt so the model knows what's already loaded
        self._inject_context(context)

        # Add user message
        self._agent.add_user_message(message)

        # Delegate entirely to framework's run_streaming()
        final_text = ""
        async for event in self._agent.run_streaming(cancel_event=cancel_event):
            if event.type == "final":
                final_text = event.final_text or ""
            elif event.type == "content":
                yield _make_sse_event(conversation_id, chunk=event.content)
            elif event.type == "thinking":
                yield _make_sse_event(conversation_id, thinking=event.thinking)
            elif event.type == "tool_call":
                yield _make_sse_event(
                    conversation_id,
                    tool_call={
                        "id": event.tool_call.id,
                        "name": event.tool_call.name,
                        "arguments": event.tool_call.arguments,
                    },
                )
            elif event.type == "tool_result":
                tr = event.tool_result
                # Parse result content (JSON string) for the SSE tool_result dict.
                try:
                    import json
                    parsed = json.loads(tr.content) if tr.content else {}
                except Exception:
                    parsed = {"raw": tr.content}
                yield _make_sse_event(
                    conversation_id,
                    tool_result={
                        "id": tr.id,
                        "name": tr.name,
                        "ok": tr.success,
                        "result": parsed,
                        "error": tr.error,
                    },
                )

        # Final done event
        yield _make_sse_event(conversation_id, done=True, chunk=final_text)


def _make_sse_event(
    conversation_id: int,
    chunk: str | None = None,
    thinking: str | None = None,
    tool_call: dict | None = None,
    tool_result: dict | None = None,
    done: bool = False,
) -> dict[str, Any]:
    return {
        "conversation_id": conversation_id,
        "ok": True,
        "chunk": chunk,
        "thinking": thinking,
        "tool_call": tool_call,
        "tool_result": tool_result,
        "done": done,
    }


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: WardMiniAgent | None = None


def get_ward_agent() -> WardMiniAgent:
    global _instance
    if _instance is None:
        _instance = WardMiniAgent()
    return _instance
