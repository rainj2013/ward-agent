"""Ward Mini-Agent wrapper — provides SSE streaming interface using Mini-Agent Agent."""

from __future__ import annotations

import re
from typing import Any, AsyncGenerator

from ward.mini_agent.llm import LLMClient
from ward.mini_agent.llm.llm_wrapper import LLMClient as MiniLLMClient
from ward.mini_agent.schema import LLMProvider, Message
from ward.mini_agent.agent import Agent as MiniAgent

from ward.agent.context_manager import (
    SUMMARY_RECENT_MESSAGE_COUNT,
    build_context_digest,
    build_summary_prompt,
    estimate_messages_tokens,
    estimate_tokens,
    should_update_summary,
)
from ward.agent.ward_tools import get_all_tools


CHAT_CONTEXT_META_RE = re.compile(r"^<!--ward-context-events:[\s\S]*?-->\n?")


def _strip_chat_context_meta(content: str) -> str:
    """Remove UI-only context event metadata from persisted assistant messages."""
    return CHAT_CONTEXT_META_RE.sub("", content, count=1)


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
    Wrapper around Mini-Agent's Agent class that exposes Ward's SSE streaming
    interface.

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

    def _build_context_message(self, context: Any | None, message: str) -> tuple[str, dict[str, Any]]:
        """Place current page digest next to the current user message."""
        digest = build_context_digest(context)
        event = {
            "type": "context_digest",
            "message": "页面上下文已摘要并靠后注入，system prompt 保持稳定。",
            **digest.stats,
        }
        if not digest.text:
            return message, event
        return f"{digest.text}\n\n[当前用户问题]\n{message}", event

    def reset_conversation(self):
        """Reset the agent's message history for a fresh conversation."""
        self._agent.messages = [Message(role="system", content=WARD_SYSTEM_PROMPT)]

    def load_conversation_history(
        self,
        messages: list[dict[str, Any]] | None,
        summary: dict[str, Any] | None = None,
        max_messages: int = 20,
    ) -> dict[str, Any]:
        """Load persisted user/assistant turns into a fresh agent instance."""
        self.reset_conversation()
        summary_text = ""
        if summary and summary.get("summary"):
            summary_text = str(summary["summary"]).strip()
            self._agent.messages.append(
                Message(
                    role="user",
                    content=(
                        "[历史摘要]\n"
                        "以下是已经离开最近保护区的对话摘要。行情类事实可能过期，实时价格必须重新查询工具。\n\n"
                        f"{summary_text}"
                    ),
                )
            )
        if not messages:
            return {
                "type": "history_load",
                "summary_tokens_est": estimate_tokens(summary_text),
                "summary_until_message_id": summary.get("summarized_until_message_id") if summary else None,
                "recent_messages": 0,
                "recent_tokens_est": 0,
            }
        recent_messages = []
        for msg in messages[-max_messages:]:
            role = msg.get("role")
            content = _strip_chat_context_meta(str(msg.get("content") or ""))
            if role in {"user", "assistant"} and content:
                recent_messages.append({**msg, "content": content})
                self._agent.messages.append(Message(role=role, content=content))
        return {
            "type": "history_load",
            "summary_tokens_est": estimate_tokens(summary_text),
            "summary_until_message_id": summary.get("summarized_until_message_id") if summary else None,
            "recent_messages": len(recent_messages),
            "recent_tokens_est": estimate_messages_tokens(recent_messages),
        }

    async def update_persistent_summary(self, conversation_id: int, conversation_service: Any) -> dict[str, Any]:
        """Incrementally update the persisted conversation summary when useful."""
        all_messages = conversation_service.get_messages(conversation_id, limit=None)
        for msg in all_messages:
            msg["content"] = _strip_chat_context_meta(str(msg.get("content") or ""))
        if len(all_messages) <= SUMMARY_RECENT_MESSAGE_COUNT:
            return {
                "type": "summary_skip",
                "message": "消息仍在最近保护区内，暂不摘要。",
                "total_messages": len(all_messages),
                "protected_recent_messages": SUMMARY_RECENT_MESSAGE_COUNT,
            }

        summary = conversation_service.get_summary(conversation_id)
        summarized_until = int(summary.get("summarized_until_message_id") or 0) if summary else 0
        cutoff_messages = all_messages[:-SUMMARY_RECENT_MESSAGE_COUNT]
        delta = [msg for msg in cutoff_messages if int(msg.get("id") or 0) > summarized_until]
        should_update, decision = should_update_summary(delta)
        if not should_update:
            return {
                "type": "summary_skip",
                "message": "新增历史不足阈值，保留现有摘要。",
                "summary_until_message_id": summarized_until or None,
                **decision,
            }

        target_until = int(delta[-1]["id"])
        prompt = build_summary_prompt(
            previous_summary=str(summary.get("summary") or "") if summary else "",
            delta_messages=delta,
            summarized_until_message_id=summarized_until or None,
        )
        response = await self._llm_client.generate(
            messages=[
                Message(role="system", content="你是 Ward 的对话摘要维护器，只输出可继续工作的事实摘要。"),
                Message(role="user", content=prompt),
            ],
            tools=None,
        )
        new_summary = response.content.strip()
        usage = {}
        if response.usage:
            usage = {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        conversation_service.upsert_summary(conversation_id, new_summary, target_until, usage)
        return {
            "type": "summary_update",
            "message": "持久摘要已增量更新。",
            "summary_until_message_id": target_until,
            "summary_tokens_est": estimate_tokens(new_summary),
            **decision,
            **usage,
        }

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
        user_message, context_event = self._build_context_message(context, message)
        yield _make_sse_event(conversation_id, context_event=context_event)

        # Add user message
        self._agent.add_user_message(user_message)

        # Delegate entirely to framework's run_streaming()
        streamed_text = ""
        async for event in self._agent.run_streaming(cancel_event=cancel_event):
            if event.type == "final":
                final_text = event.final_text or ""
                if final_text and not streamed_text.endswith(final_text):
                    streamed_text += final_text
                    yield _make_sse_event(conversation_id, chunk=final_text)
            elif event.type == "content":
                streamed_text += event.content or ""
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

        # Final done event. Content has already been streamed as chunk events.
        yield _make_sse_event(conversation_id, done=True)


def _make_sse_event(
    conversation_id: int,
    chunk: str | None = None,
    thinking: str | None = None,
    tool_call: dict | None = None,
    tool_result: dict | None = None,
    context_event: dict | None = None,
    done: bool = False,
) -> dict[str, Any]:
    return {
        "conversation_id": conversation_id,
        "ok": True,
        "chunk": chunk,
        "thinking": thinking,
        "tool_call": tool_call,
        "tool_result": tool_result,
        "context_event": context_event,
        "done": done,
    }


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: WardMiniAgent | None = None


def get_ward_agent() -> WardMiniAgent:
    global _instance
    if _instance is None:
        _instance = WardMiniAgent()
    return _instance
