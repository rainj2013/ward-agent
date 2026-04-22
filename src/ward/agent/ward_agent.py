"""Ward Mini-Agent wrapper — provides SSE streaming interface using Mini-Agent Agent."""

from __future__ import annotations

import asyncio
import json
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
- get_stock_kline: 获取个股历史K线数据
- get_stock_analyze: 获取个股AI分析报告
- get_index_analyze: 获取指数AI分析报告
- get_market_overview: 获取三大指数和黄金的今日行情
- get_extended_hours: 获取盘前/盘后交易数据

规则：
- 用中文回答用户问题
- 优先使用工具获取最新数据
- 不要编造任何数据，所有数据必须来自工具返回结果
- 如果工具返回的数据不足（如某字段为null），如实说明，不要填充
- 回答要简洁、专业，突出重点数据"""


# ── WardMiniAgent ─────────────────────────────────────────────────────────────

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

    def reset_conversation(self):
        """Reset the agent's message history for a fresh conversation."""
        # Keep system prompt (first message), clear everything else
        system_msg = self._agent.messages[0]
        self._agent.messages = [system_msg]

    async def chat_stream(
        self,
        conversation_id: int,
        message: str,
        context: Any | None,
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

        # Add user message
        self._agent.add_user_message(message)

        # Run the agent streaming loop
        final_text = ""
        async for event in self._run_streaming():
            if event.get("final_text") is not None:
                final_text = event["final_text"]
            else:
                # Forward the SSE event
                yield {
                    "conversation_id": conversation_id,
                    "ok": True,
                    "chunk": event.get("chunk"),
                    "thinking": event.get("thinking"),
                    "tool_call": event.get("tool_call"),
                    "tool_result": event.get("tool_result"),
                    "done": False,
                }

        # After run completes, yield final done chunk
        yield {
            "conversation_id": conversation_id,
            "ok": True,
            "done": True,
            "chunk": final_text or "",
            "tool_result": None,
            "tool_call": None,
            "thinking": None,
        }

    # ── Internal streaming loop ────────────────────────────────────────────────

    async def _run_streaming(self) -> AsyncGenerator[dict[str, Any], None]:
        """
        Re-implement Mini-Agent's run() loop but yield SSE events instead of printing.
        Each yield is a dict; a special {"final_text": "..."} signal marks the end.
        """
        step = 0
        max_steps = self._agent.max_steps
        final_text = ""

        self._agent.logger.start_new_run()

        while step < max_steps:
            # Check cancellation
            if self._agent.cancel_event is not None and self._agent.cancel_event.is_set():
                self._agent._cleanup_incomplete_messages()
                final_text = "任务已被用户取消。"
                yield {"final_text": final_text}
                return

            # Summarize if needed
            await self._agent._summarize_messages()

            tool_list = list(self._agent.tools.values())

            self._agent.logger.log_request(messages=self._agent.messages, tools=tool_list)

            try:
                response = await self._agent.llm.generate(messages=self._agent.messages, tools=tool_list)
            except Exception as e:
                from ward.mini_agent.retry import RetryExhaustedError

                if isinstance(e, RetryExhaustedError):
                    final_text = f"LLM 调用失败，已重试 {e.attempts} 次。上次错误：{str(e.last_exception)}"
                else:
                    final_text = f"LLM 调用失败：{str(e)}"
                yield {"final_text": final_text}
                return

            # Accumulate token usage
            if response.usage:
                self._agent.api_total_tokens = response.usage.total_tokens

            self._agent.logger.log_response(
                content=response.content,
                thinking=response.thinking,
                tool_calls=response.tool_calls,
                finish_reason=response.finish_reason,
            )

            # Stream thinking
            if response.thinking:
                yield {"thinking": response.thinking, "chunk": None, "tool_call": None, "tool_result": None}

            # Stream text
            if response.content:
                yield {"chunk": response.content, "thinking": None, "tool_call": None, "tool_result": None}

            # Add assistant message to history
            assistant_msg = Message(
                role="assistant",
                content=response.content or "",
                thinking=response.thinking,
                tool_calls=response.tool_calls,
            )
            self._agent.messages.append(assistant_msg)

            # No tool calls — we're done
            if not response.tool_calls:
                final_text = response.content or ""
                yield {"final_text": final_text}
                return

            # Check cancellation before tool execution
            if self._agent.cancel_event is not None and self._agent.cancel_event.is_set():
                self._agent._cleanup_incomplete_messages()
                final_text = "任务已被用户取消。"
                yield {"final_text": final_text}
                return

            # Execute each tool call
            for tool_call in response.tool_calls:
                tool_call_id = tool_call.id
                fn_name = tool_call.function.name
                fn_args = tool_call.function.arguments

                # Yield tool call start
                yield {"tool_call": {"id": tool_call_id, "name": fn_name, "arguments": fn_args}, "chunk": None, "thinking": None, "tool_result": None}

                # Execute tool
                if fn_name not in self._agent.tools:
                    result_content = ""
                    result_error = f"未知工具：{fn_name}"
                    success = False
                else:
                    try:
                        tool = self._agent.tools[fn_name]
                        result = await tool.execute(**fn_args)
                        success = result.success
                        result_content = result.content
                        result_error = result.error
                    except Exception as e:
                        import traceback

                        success = False
                        result_content = ""
                        result_error = f"工具执行异常：{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"

                self._agent.logger.log_tool_result(
                    tool_name=fn_name,
                    arguments=fn_args,
                    result_success=success,
                    result_content=result_content if success else None,
                    result_error=result_error if not success else None,
                )

                # Yield tool result
                yield {
                    "tool_result": {
                        "id": tool_call_id,
                        "name": fn_name,
                        "ok": success,
                        "result": result_content,
                        "error": result_error,
                    },
                    "chunk": None,
                    "thinking": None,
                    "tool_call": None,
                }

                # Append tool result message
                tool_msg = Message(
                    role="tool",
                    content=result_content if success else f"Error: {result_error}",
                    tool_call_id=tool_call_id,
                    name=fn_name,
                )
                self._agent.messages.append(tool_msg)

                # Check cancellation after each tool
                if self._agent.cancel_event is not None and self._agent.cancel_event.is_set():
                    self._agent._cleanup_incomplete_messages()
                    final_text = "任务已被用户取消。"
                    yield {"final_text": final_text}
                    return

            step += 1

        final_text = f"任务未能在 {max_steps} 步内完成。"
        yield {"final_text": final_text}


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: WardMiniAgent | None = None


def get_ward_agent() -> WardMiniAgent:
    global _instance
    if _instance is None:
        _instance = WardMiniAgent()
    return _instance
