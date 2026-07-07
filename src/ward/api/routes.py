"""FastAPI routes."""

from __future__ import annotations

import json
import asyncio
import re

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from typing import Any

from ward.schemas.models import (
    ChatRequest,
    ChatMessageUpdateRequest,
    ChatResponse,
    HistoryResponse, HistoryPaginatedResponse,
    MessageResponse,
)
from ward.agent.ward_agent import WardMiniAgent
from ward.services.history_service import HistoryService
from ward.services.stock_service import StockService
from ward.services.stock_symbols import normalize_stock_symbol
from ward.api.dependencies import RuntimeServices, get_services

router = APIRouter()
_conversation_cancels: dict[int, asyncio.Event] = {}

def _get_or_create_cancel_event(conversation_id: int) -> asyncio.Event:
    """Get existing cancel event or create new one for a conversation."""
    if conversation_id not in _conversation_cancels:
        _conversation_cancels[conversation_id] = asyncio.Event()
    return _conversation_cancels[conversation_id]


def _clear_cancel_event(conversation_id: int) -> None:
    """Remove cancel event after conversation ends."""
    _conversation_cancels.pop(conversation_id, None)


# ── SSE helper ────────────────────────────────────────────────────────────────

def _compact_tool_result(tool_result: dict | None) -> dict | None:
    """Keep SSE tool status events small; the agent already has the full result."""
    if not tool_result:
        return None
    return {
        "id": tool_result.get("id"),
        "name": tool_result.get("name"),
        "ok": tool_result.get("ok"),
        "error": tool_result.get("error"),
    }


async def sse_format(chunk: dict, conversation_id: int) -> str:
    """Format a chunk dict as an SSE data line."""
    conv_id = chunk.get("conversation_id", conversation_id)
    data = json.dumps({
        "ok": True,
        "conversation_id": conv_id,
        "chunk": chunk.get("chunk", ""),
        "thinking": chunk.get("thinking"),
        "tool_call": chunk.get("tool_call"),
        "tool_result": _compact_tool_result(chunk.get("tool_result")),
        "context_event": chunk.get("context_event"),
        "job": chunk.get("job"),
        "assistant_message_id": chunk.get("assistant_message_id"),
        "done": chunk.get("done", False),
        "messages": chunk.get("messages"),
    }, ensure_ascii=False, separators=(",", ":"))
    return f"data: {data}\n\n"


# ── Chat endpoints ────────────────────────────────────────────────────────────

_COMPARE_INTENT_WORDS = (
    "比较",
    "对比",
    "哪个更好",
    "哪只更好",
    "选哪个",
    "买哪个",
    "排序",
    "排名",
    "相对机会",
    "相对风险",
    "compare",
    "versus",
    " vs ",
)


def _detect_stock_comparison_intent(message: str, stock_service: StockService) -> dict[str, Any] | None:
    """Detect simple multi-stock comparison requests without an LLM call."""
    text = f" {message.strip()} "
    lowered = text.lower()
    if not any(word in lowered for word in _COMPARE_INTENT_WORDS):
        return None

    candidates = re.findall(r"(?<![A-Za-z])(\$?)([A-Za-z]{1,5})(?![A-Za-z])", text)
    symbols: list[str] = []
    for dollar, candidate in candidates:
        # Only fast-path explicit ticker-like tokens. Lowercase words such as
        # "from" and "angle" should fall through to the regular agent.
        if not dollar and candidate != candidate.upper():
            continue
        symbol = normalize_stock_symbol(candidate)
        if symbol and symbol not in symbols:
            symbols.append(symbol)

    if len(symbols) < 2 or len(symbols) > 6:
        return None

    valid_symbols: list[str] = []
    for symbol in symbols:
        try:
            quote = stock_service.get_quote(symbol)
        except Exception:
            quote = {"ok": False}
        if quote.get("ok") and symbol not in valid_symbols:
            valid_symbols.append(symbol)

    if len(valid_symbols) < 2:
        return None

    return {"symbols": valid_symbols, "objective": message.strip()}


def _build_chat_agent(conversation_id: int, history_service: HistoryService) -> tuple[WardMiniAgent, dict]:
    agent = WardMiniAgent()
    summary = history_service.conversations.get_summary(conversation_id)
    if summary and summary.get("summarized_until_message_id"):
        summarized_until = int(summary["summarized_until_message_id"])
        history = [
            msg
            for msg in history_service.conversations.get_messages(conversation_id, limit=None)
            if int(msg.get("id") or 0) > summarized_until
        ][-20:]
    else:
        history = history_service.conversations.get_messages(conversation_id, limit=20)
    load_event = agent.load_conversation_history(history, summary=summary)
    return agent, load_event


async def _update_summary_background(conversation_id: int, history_service: HistoryService) -> None:
    """Update persistent chat summary without blocking the client stream."""
    try:
        agent = WardMiniAgent()
        await agent.update_persistent_summary(conversation_id, history_service.conversations)
    except Exception as exc:
        print(f"[Ward] background summary update failed for conversation {conversation_id}: {exc}")


def _resolve_conversation_id(requested_id: int | None, history_service: HistoryService) -> int:
    """Reuse a valid client conversation id or recover with a new conversation."""
    conversations = history_service.conversations
    if requested_id is not None and conversations.conversation_exists(requested_id):
        return requested_id
    return conversations.create_conversation()

@router.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, services: RuntimeServices = Depends(get_services)):
    """Send a chat message and get AI response (non-streaming)."""
    conversation_id = _resolve_conversation_id(req.conversation_id, services.history)
    agent, _load_event = _build_chat_agent(conversation_id, services.history)
    services.history.conversations.add_message(conversation_id, "user", req.message)
    final_reply = ""
    async for chunk in agent.chat_stream(conversation_id, req.message, req.context):
        if chunk.get("chunk"):
            final_reply += chunk.get("chunk", "")
        if chunk.get("done"):
            break
    if final_reply:
        services.history.conversations.add_message(conversation_id, "assistant", final_reply)
        asyncio.create_task(_update_summary_background(conversation_id, services.history))
    return ChatResponse(
        ok=True,
        conversation_id=conversation_id,
        reply=final_reply,
        messages=[],
        error=None,
    )


@router.post("/api/chat/stream")
async def chat_stream(req: ChatRequest, services: RuntimeServices = Depends(get_services)):
    """Send a chat message and stream AI response chunks via SSE."""
    conversation_id = _resolve_conversation_id(req.conversation_id, services.history)
    agent, load_event = _build_chat_agent(conversation_id, services.history)
    services.history.conversations.add_message(conversation_id, "user", req.message)
    cancel_event = _get_or_create_cancel_event(conversation_id)

    async def event_generator():
        reply_parts: list[str] = []
        try:
            yield await sse_format({"conversation_id": conversation_id}, conversation_id)
            yield await sse_format({"conversation_id": conversation_id, "context_event": load_event}, conversation_id)
            comparison = await asyncio.to_thread(_detect_stock_comparison_intent, req.message, services.stock)
            if comparison:
                job = await services.jobs.create_job("stock_comparison", comparison)
                symbols = "、".join(comparison["symbols"])
                reply = (
                    f"已为 {symbols} 创建多股对比 Team 任务。"
                    f"你可以在 Runtime 查看 Leader / Worker / Verifier 的执行过程：/runtime?job_id={job['id']}"
                )
                assistant_message_id = services.history.conversations.add_message(conversation_id, "assistant", reply)
                yield await sse_format(
                    {
                        "conversation_id": conversation_id,
                        "chunk": reply,
                        "assistant_message_id": assistant_message_id,
                        "job": {
                            "id": job["id"],
                            "type": job["type"],
                            "symbols": comparison["symbols"],
                            "objective": comparison["objective"],
                            "trace_url": f"/runtime?job_id={job['id']}",
                        },
                        "done": True,
                    },
                    conversation_id,
                )
                return

            async for chunk in agent.chat_stream(conversation_id, req.message, req.context, cancel_event):
                if not chunk.get("ok"):
                    yield f"data: {json.dumps({'ok': False, 'error': chunk.get('error', 'Unknown error'), 'done': True})}\n\n"
                    break
                if chunk.get("chunk"):
                    reply_parts.append(chunk["chunk"])
                if chunk.get("done"):
                    reply = "".join(reply_parts).strip()
                    assistant_message_id = None
                    if reply:
                        assistant_message_id = services.history.conversations.add_message(conversation_id, "assistant", reply)
                    asyncio.create_task(_update_summary_background(conversation_id, services.history))
                    summary_event = {
                        "type": "summary_skip",
                        "message": "摘要更新已转入后台，不阻塞本轮回答完成。",
                    }
                    yield await sse_format(
                        {"conversation_id": conversation_id, "context_event": summary_event},
                        conversation_id,
                    )
                    if assistant_message_id:
                        chunk["assistant_message_id"] = assistant_message_id
                    yield await sse_format(chunk, conversation_id)
                    break
                yield await sse_format(chunk, conversation_id)
        except asyncio.CancelledError:
            # Fetch was aborted by client (e.g. user clicked cancel) — signal done
            yield f"data: {json.dumps({'ok': True, 'done': True, 'cancelled': True})}\n\n"
            raise
        except Exception as exc:
            yield f"data: {json.dumps({'ok': False, 'error': str(exc), 'done': True}, ensure_ascii=False)}\n\n"
        finally:
            _clear_cancel_event(conversation_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Transfer-Encoding": "chunked",
        },
    )


@router.post("/api/chat/{conversation_id}/cancel")
async def cancel_chat(conversation_id: int):
    """Cancel an ongoing chat conversation."""
    # Also check id=0 for brand-new conversations (ID not yet assigned by server)
    cancel_event = _conversation_cancels.get(conversation_id) or _conversation_cancels.get(0)
    if cancel_event:
        cancel_event.set()
        return {"ok": True, "message": "Cancelled"}
    return {"ok": False, "error": "No active conversation to cancel"}


@router.put("/api/chat/{conversation_id}/messages/{message_id}")
def update_chat_message(conversation_id: int, message_id: int, req: ChatMessageUpdateRequest, services: RuntimeServices = Depends(get_services)):
    """Update a persisted assistant message after an async job completes."""
    ok = services.history.conversations.update_message(conversation_id, message_id, "assistant", req.content)
    if not ok:
        return {"ok": False, "error": "Message not found"}
    return {"ok": True}


@router.get("/api/history/{conversation_id}", response_model=HistoryResponse)
def get_history(conversation_id: int, services: RuntimeServices = Depends(get_services)):
    """Get chat history for a conversation (latest 20 messages)."""
    result = services.history.get_history(conversation_id)
    return HistoryResponse(
        ok=result.get("ok", False),
        conversation_id=result.get("conversation_id"),
        messages=[MessageResponse(**m) for m in result.get("messages", [])],
        error=result.get("error"),
    )


@router.get("/api/history/{conversation_id}/messages", response_model=HistoryPaginatedResponse)
def get_history_paginated(conversation_id: int, limit: int = 20, before_id: int | None = None, services: RuntimeServices = Depends(get_services)):
    """Get older messages using cursor pagination (waterfall load)."""
    result = services.history.get_history_paginated(conversation_id, limit, before_id)
    return HistoryPaginatedResponse(
        ok=result.get("ok", False),
        conversation_id=result.get("conversation_id"),
        messages=[MessageResponse(**m) for m in result.get("messages", [])],
        has_more=result.get("has_more", False),
        next_before_id=result.get("next_before_id"),
        error=result.get("error"),
    )
