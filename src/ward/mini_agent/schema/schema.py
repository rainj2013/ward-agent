from enum import Enum
from typing import Any

from pydantic import BaseModel


class LLMProvider(str, Enum):
    """LLM provider types."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"


class FunctionCall(BaseModel):
    """Function call details."""

    name: str
    arguments: dict[str, Any]  # Function arguments as dict


class ToolCall(BaseModel):
    """Tool call structure."""

    id: str
    type: str  # "function"
    function: FunctionCall


class Message(BaseModel):
    """Chat message."""

    role: str  # "system", "user", "assistant", "tool"
    content: str | list[dict[str, Any]]  # Can be string or list of content blocks
    thinking: str | None = None  # Extended thinking content for assistant messages
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None  # For tool role


class TokenUsage(BaseModel):
    """Token usage statistics from LLM API response."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMResponse(BaseModel):
    """LLM response."""

    content: str
    thinking: str | None = None  # Extended thinking blocks
    tool_calls: list[ToolCall] | None = None
    finish_reason: str
    usage: TokenUsage | None = None  # Token usage from API response


class ToolCallEvent(BaseModel):
    """A tool call event emitted before tool execution."""

    id: str  # tool_call id
    name: str  # function name
    arguments: dict[str, Any]  # function arguments


class ToolResultEvent(BaseModel):
    """A tool result event emitted after tool execution."""

    id: str  # tool_call id
    name: str  # function name
    success: bool
    content: str = ""
    error: str | None = None


class AgentEvent(BaseModel):
    """Streaming event emitted by Agent.run_streaming()."""

    # Event type discriminator
    type: str  # "thinking" | "content" | "tool_call" | "tool_result" | "step_complete" | "final"

    # Text/think chunks
    content: str | None = None
    thinking: str | None = None

    # Tool events
    tool_call: ToolCallEvent | None = None
    tool_result: ToolResultEvent | None = None

    # Step metadata
    step: int | None = None

    # Final result
    final_text: str | None = None

    # Token usage
    total_tokens: int | None = None
