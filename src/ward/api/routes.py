"""FastAPI routes."""

from __future__ import annotations

import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from pathlib import Path

from ward.schemas.models import (
    ChatRequest,
    ChatResponse,
    ExtendedPriceResponse,
    HistoryResponse, HistoryPaginatedResponse,
    IndexAnalysisResponse,
    MarketOverviewResponse,
    MessageResponse,
    QuoteResponse,
    ReportResponse,
    StockAnalysisResponse,
    StockHistoryResponse,
    StockKlineResponse,
    StockQuoteResponse,
    StockSearchResponse,
)
from ward.agent.ward_agent import get_ward_agent
from ward.services.chat_service import ChatService
from ward.services.index_service import IndexService
from ward.services.nasdaq_service import MarketService
from ward.services.report_service import ReportService
from ward.services.stock_service import StockService

router = APIRouter()
ms = MarketService()
rs = ReportService()
cs = ChatService()  # kept only for history endpoints
ss = StockService()
is_ = IndexService()

_static_dir = Path(__file__).parent.parent.parent.parent / "static"


# ── Conversation cancellation registry ────────────────────────────────────────

import asyncio
from typing import Optional

_conversation_cancels: dict[int, asyncio.Event] = {}


def _get_or_create_cancel_event(conversation_id: int) -> asyncio.Event:
    """Get existing cancel event or create new one for a conversation."""
    if conversation_id not in _conversation_cancels:
        _conversation_cancels[conversation_id] = asyncio.Event()
    return _conversation_cancels[conversation_id]


def _clear_cancel_event(conversation_id: int) -> None:
    """Remove cancel event after conversation ends."""
    _conversation_cancels.pop(conversation_id, None)


@router.get("/", response_class=HTMLResponse)
async def home():
    """Serve the main web page."""
    return FileResponse(str(_static_dir / "index.html"))


@router.get("/api/quote", response_model=QuoteResponse)
async def get_quote():
    """Get Nasdaq Composite quote."""
    result = ms.get_quote()
    return QuoteResponse(
        ok=result.get("ok", False),
        data=result.get("data"),
        error=result.get("error"),
    )


@router.get("/api/ndx-quote", response_model=QuoteResponse)
async def get_ndx_quote():
    """Get Nasdaq 100 quote."""
    result = ms.get_ndx_quote()
    return QuoteResponse(
        ok=result.get("ok", False),
        data=result.get("data"),
        error=result.get("error"),
    )


@router.get("/api/dji-quote", response_model=QuoteResponse)
async def get_dji_quote():
    """Get Dow Jones quote."""
    result = ms.get_dji_quote()
    return QuoteResponse(
        ok=result.get("ok", False),
        data=result.get("data"),
        error=result.get("error"),
    )


@router.get("/api/spx-quote", response_model=QuoteResponse)
async def get_spx_quote():
    """Get S&P 500 quote."""
    result = ms.get_spx_quote()
    return QuoteResponse(
        ok=result.get("ok", False),
        data=result.get("data"),
        error=result.get("error"),
    )


@router.get("/api/gold-quote", response_model=QuoteResponse)
async def get_gold_quote():
    """Get Gold quote."""
    result = ms.get_gold_quote()
    return QuoteResponse(
        ok=result.get("ok", False),
        data=result.get("data"),
        error=result.get("error"),
    )


@router.get("/api/market-overview", response_model=MarketOverviewResponse)
async def get_market_overview():
    """Get combined market overview."""
    result = ms.get_market_overview()
    return MarketOverviewResponse(
        ok=result.get("ok", False),
        nasdaq_composite=result.get("nasdaq_composite"),
        nasdaq_100=result.get("nasdaq_100"),
        dow_jones=result.get("dow_jones"),
        sp500=result.get("sp500"),
        gold=result.get("gold"),
    )


@router.get("/api/index/{prefix}/analyze", response_model=IndexAnalysisResponse)
async def analyze_index(prefix: str):
    """Generate AI-powered analysis for a single US index (ixic / spx / dji)."""
    result = is_.generate_analysis(prefix)
    return IndexAnalysisResponse(
        ok=result.get("ok", False),
        prefix=result.get("prefix"),
        name=result.get("name"),
        report=result.get("report"),
        data=result.get("data"),
        error=result.get("error"),
    )


@router.get("/api/report", response_model=ReportResponse)
async def generate_report():
    """Generate LLM-powered market report."""
    result = rs.generate_market_report()
    return ReportResponse(
        ok=result.get("ok", False),
        report=result.get("report"),
        data=result.get("data"),
        error=result.get("error"),
    )


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
        "done": chunk.get("done", False),
        "messages": chunk.get("messages"),
    }, ensure_ascii=False, separators=(",", ":"))
    return f"data: {data}\n\n"


# ── Chat endpoints ────────────────────────────────────────────────────────────

@router.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Send a chat message and get AI response (non-streaming)."""
    agent = get_ward_agent()
    final_reply = ""
    async for chunk in agent.chat_stream(req.conversation_id, req.message, req.context):
        if chunk.get("chunk"):
            final_reply = chunk.get("chunk", "")
        if chunk.get("done"):
            break
    return ChatResponse(
        ok=True,
        conversation_id=req.conversation_id,
        reply=final_reply,
        messages=[],
        error=None,
    )


@router.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """Send a chat message and stream AI response chunks via SSE."""
    agent = get_ward_agent()
    cancel_event = _get_or_create_cancel_event(req.conversation_id)

    async def event_generator():
        try:
            async for chunk in agent.chat_stream(req.conversation_id, req.message, req.context, cancel_event):
                if not chunk.get("ok"):
                    yield f"data: {json.dumps({'ok': False, 'error': chunk.get('error', 'Unknown error'), 'done': True})}\n\n"
                    break
                yield await sse_format(chunk, req.conversation_id)
                if chunk.get("done"):
                    break
        except asyncio.CancelledError:
            # Fetch was aborted by client (e.g. user clicked cancel) — signal done
            yield f"data: {json.dumps({'ok': True, 'done': True, 'cancelled': True})}\n\n"
            raise
        finally:
            _clear_cancel_event(req.conversation_id)

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


@router.get("/api/history/{conversation_id}", response_model=HistoryResponse)
async def get_history(conversation_id: int):
    """Get chat history for a conversation (latest 20 messages)."""
    result = cs.get_history(conversation_id)
    return HistoryResponse(
        ok=result.get("ok", False),
        conversation_id=result.get("conversation_id"),
        messages=[MessageResponse(**m) for m in result.get("messages", [])],
        error=result.get("error"),
    )


@router.get("/api/history/{conversation_id}/messages", response_model=HistoryPaginatedResponse)
async def get_history_paginated(conversation_id: int, limit: int = 20, before_id: int | None = None):
    """Get older messages using cursor pagination (waterfall load)."""
    result = cs.get_history_paginated(conversation_id, limit, before_id)
    return HistoryPaginatedResponse(
        ok=result.get("ok", False),
        conversation_id=result.get("conversation_id"),
        messages=[MessageResponse(**m) for m in result.get("messages", [])],
        has_more=result.get("has_more", False),
        next_before_id=result.get("next_before_id"),
        error=result.get("error"),
    )


# Stock APIs

@router.get("/api/stock/search", response_model=StockSearchResponse)
async def search_stock(q: str):
    """Search stocks by symbol or name."""
    result = ss.search(q)
    return StockSearchResponse(ok=True, results=result.get("results", []))


@router.get("/api/stock/{symbol}/quote", response_model=StockQuoteResponse)
async def get_stock_quote(symbol: str):
    """Get quote for a single stock."""
    result = ss.get_quote(symbol)
    return StockQuoteResponse(
        ok=result.get("ok", False),
        data=result.get("data"),
        error=result.get("error"),
    )


@router.get("/api/stock/{symbol}/history", response_model=StockHistoryResponse)
async def get_stock_history(symbol: str, days: int = 30):
    """Get historical daily data for a stock."""
    result = ss.get_historical(symbol, days)
    return StockHistoryResponse(
        ok=result.get("ok", False),
        symbol=result.get("symbol"),
        name=result.get("name"),
        data=result.get("data", []),
        error=result.get("error"),
    )


@router.get("/api/stock/{symbol}/kline", response_model=StockKlineResponse)
async def get_stock_kline(symbol: str, days: int = 30):
    """Get kline (OHLCV) data for a stock."""
    result = ss.get_kline(symbol, days)
    return StockKlineResponse(
        ok=result.get("ok", False),
        symbol=result.get("symbol"),
        name=result.get("name"),
        data=result.get("data", []),
        error=result.get("error"),
    )


@router.get("/api/stock/{symbol}/analyze", response_model=StockAnalysisResponse)
async def analyze_stock(symbol: str):
    """Generate AI-powered stock analysis report."""
    result = ss.generate_analysis(symbol)
    return StockAnalysisResponse(
        ok=result.get("ok", False),
        symbol=result.get("symbol"),
        name=result.get("name"),
        report=result.get("report"),
        data=result.get("data"),
        cached=result.get("cached"),
        error=result.get("error"),
    )


@router.get("/api/stock/{symbol}/extended", response_model=ExtendedPriceResponse)
async def get_extended_price(symbol: str):
    """Get pre-market / regular / after-hours prices for a stock or index."""
    result = ss.get_extended_price(symbol)
    return ExtendedPriceResponse(
        ok=result.get("ok", False),
        symbol=result.get("symbol"),
        name=result.get("name"),
        date=result.get("date"),
        pre_market=result.get("pre_market"),
        regular=result.get("regular"),
        after_hours=result.get("after_hours"),
        previous_close=result.get("previous_close"),
        error=result.get("error"),
    )
