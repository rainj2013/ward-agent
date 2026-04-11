"""FastAPI routes."""

from __future__ import annotations

import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from pathlib import Path

from ward.schemas.models import (
    ChatRequest,
    ChatResponse,
    HistoryResponse, HistoryPaginatedResponse,
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
from ward.services.chat_service import ChatService
from ward.services.nasdaq_service import MarketService
from ward.services.report_service import ReportService
from ward.services.stock_service import StockService

router = APIRouter()
ms = MarketService()
rs = ReportService()
cs = ChatService()
ss = StockService()

_static_dir = Path(__file__).parent.parent.parent.parent / "static"


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


@router.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Send a chat message and get AI response."""
    result = cs.chat(req.conversation_id, req.message, req.context)
    return ChatResponse(
        ok=result.get("ok", False),
        conversation_id=result.get("conversation_id"),
        reply=result.get("reply"),
        messages=[MessageResponse(**m) for m in result.get("messages", [])],
        error=result.get("error"),
    )


async def chat_event_generator(result, conversation_id):
    for chunk in result:
        # Use chunk's conversation_id (generated inside chat_stream) if available
        conv_id = chunk.get("conversation_id", conversation_id)
        if chunk.get("ok"):
            data = json.dumps({
                "ok": True,
                "conversation_id": conv_id,
                "chunk": chunk.get("chunk", ""),
                "done": chunk.get("done", False),
                "messages": chunk.get("messages"),
            })
            yield f"data: {data}\n\n"
            if chunk.get("done"):
                break
        else:
            data = json.dumps({"ok": False, "conversation_id": conv_id, "error": chunk.get("error", "Unknown error"), "done": True})
            yield f"data: {data}\n\n"
            break


@router.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """Send a chat message and stream AI response chunks via SSE."""
    conversation_id = req.conversation_id
    result = cs.chat_stream(conversation_id, req.message, req.context)
    return StreamingResponse(
        chat_event_generator(result, conversation_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Transfer-Encoding": "chunked",
        },
    )


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
        error=result.get("error"),
    )
