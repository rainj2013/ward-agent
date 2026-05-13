"""FastAPI routes."""

from __future__ import annotations

import json
import asyncio
import re

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from pathlib import Path
from typing import Any

from ward.schemas.models import (
    AnalysisJobCreateResponse,
    AnalysisJobResponse,
    ChatRequest,
    ChatMessageUpdateRequest,
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
from ward.agent.ward_agent import WardMiniAgent
from ward.services.analysis_job_service import AnalysisJobService
from ward.services.history_service import HistoryService
from ward.services.index_service import IndexService
from ward.services.nasdaq_service import MarketService
from ward.services.report_service import ReportService
from ward.services.stock_comparison_service import StockComparisonService
from ward.services.stock_service import StockService
from ward.services.stock_symbols import normalize_stock_symbol

router = APIRouter()
ms = MarketService()
rs = ReportService()
hs = HistoryService()
ss = StockService()
scs = StockComparisonService()
is_ = IndexService()
ajs = AnalysisJobService(concurrency=1)
ajs.register_handler("stock_analysis", lambda payload: ss.generate_analysis(payload["symbol"], trace=payload.get("_trace")))
ajs.register_handler("index_analysis", lambda payload: is_.generate_analysis(payload["prefix"], trace=payload.get("_trace")))
ajs.register_handler("market_report", lambda payload: rs.generate_market_report(trace=payload.get("_trace")))
ajs.register_handler(
    "stock_comparison",
    lambda payload: scs.generate_comparison(payload["symbols"], payload.get("objective"), trace=payload.get("_trace")),
)

_static_dir = Path(__file__).parent.parent.parent.parent / "static"


_conversation_cancels: dict[int, asyncio.Event] = {}

_CACHED_STREAM_CHARS = 32


def _get_or_create_cancel_event(conversation_id: int) -> asyncio.Event:
    """Get existing cancel event or create new one for a conversation."""
    if conversation_id not in _conversation_cancels:
        _conversation_cancels[conversation_id] = asyncio.Event()
    return _conversation_cancels[conversation_id]


def _clear_cancel_event(conversation_id: int) -> None:
    """Remove cancel event after conversation ends."""
    _conversation_cancels.pop(conversation_id, None)


def _sse_data(chunk: dict) -> str:
    """Format a chunk dict as a compact SSE data event."""
    data = json.dumps(chunk, ensure_ascii=False, separators=(",", ":"))
    return f"data: {data}\n\n"


def _split_cached_text(text: str, size: int = _CACHED_STREAM_CHARS):
    """Split cached reports so the UI still renders progressively."""
    for i in range(0, len(text), size):
        yield text[i:i + size]


async def _stream_llm_chunks(chunks):
    """Stream sync LLM chunk generators as SSE, including cached reports."""
    try:
        for chunk in chunks:
            text = chunk.get("chunk")
            if chunk.get("cached") and text and not chunk.get("done"):
                base = dict(chunk)
                base.pop("chunk", None)
                for part in _split_cached_text(text):
                    yield _sse_data({**base, "chunk": part})
                    await asyncio.sleep(0.02)
            else:
                yield _sse_data(chunk)
                await asyncio.sleep(0)

            if chunk.get("done"):
                break
    except Exception as exc:
        yield _sse_data({"ok": False, "error": str(exc), "done": True})


def _sse_response(generator):
    """Create a StreamingResponse with headers that discourage buffering."""
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Transfer-Encoding": "chunked",
        },
    )


def _terminal_job_status(status: str | None) -> bool:
    return status in {"succeeded", "failed", "cancelled"}


async def _analysis_job_event_stream(job_id: str):
    """Stream persisted analysis job events until the job reaches a terminal state."""
    last_event_id = 0
    while True:
        job = ajs.get_job(job_id)
        if not job:
            yield _sse_data({"ok": False, "error": "Job not found", "done": True})
            return

        events = ajs.get_events(job_id, last_event_id)
        for event in events:
            last_event_id = event["id"]
            payload = {"ok": True, **event, "job": job, "done": False}
            if _terminal_job_status(job.get("status")) and event["event"] in {"succeeded", "failed"}:
                payload["job"] = ajs.get_job(job_id)
                payload["done"] = True
            yield _sse_data(payload)

        if _terminal_job_status(job.get("status")):
            if not events:
                yield _sse_data({"ok": True, "event": "done", "job": job, "done": True})
            return

        await asyncio.sleep(0.5)


@router.get("/", response_class=HTMLResponse)
async def home():
    """Serve the main web page."""
    return FileResponse(str(_static_dir / "index.html"))


@router.get("/runtime", response_class=HTMLResponse)
async def runtime_page():
    """Serve the runtime observability page."""
    return FileResponse(str(_static_dir / "runtime.html"))


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


@router.get("/api/index/{prefix}/analyze/stream")
async def analyze_index_stream(prefix: str):
    """Stream AI-powered analysis for a single US index."""
    return _sse_response(_stream_llm_chunks(is_.generate_analysis_stream(prefix)))


@router.post("/api/analysis-jobs/index/{prefix}", response_model=AnalysisJobCreateResponse)
async def create_index_analysis_job(prefix: str):
    """Create a queued AI analysis job for an index."""
    try:
        job = await ajs.create_job("index_analysis", {"prefix": prefix})
        return AnalysisJobCreateResponse(ok=True, job=job)
    except Exception as exc:
        return AnalysisJobCreateResponse(ok=False, error=str(exc))


@router.post("/api/analysis-jobs/stock/{symbol}", response_model=AnalysisJobCreateResponse)
async def create_stock_analysis_job(symbol: str):
    """Create a queued AI analysis job for a stock."""
    try:
        job = await ajs.create_job("stock_analysis", {"symbol": symbol.upper()})
        return AnalysisJobCreateResponse(ok=True, job=job)
    except Exception as exc:
        return AnalysisJobCreateResponse(ok=False, error=str(exc))


@router.post("/api/analysis-jobs/report", response_model=AnalysisJobCreateResponse)
async def create_market_report_job():
    """Create a queued AI market report job."""
    try:
        job = await ajs.create_job("market_report", {})
        return AnalysisJobCreateResponse(ok=True, job=job)
    except Exception as exc:
        return AnalysisJobCreateResponse(ok=False, error=str(exc))


@router.get("/api/analysis-jobs/{job_id}", response_model=AnalysisJobResponse)
async def get_analysis_job(job_id: str):
    """Get the latest persisted state for an analysis job."""
    job = ajs.get_job(job_id)
    if not job:
        return AnalysisJobResponse(ok=False, error="Job not found")
    return AnalysisJobResponse(ok=True, job=job)


@router.get("/api/analysis-jobs/{job_id}/trace")
async def get_analysis_job_trace(job_id: str):
    """Get full structured trace for an analysis job."""
    trace = ajs.get_trace(job_id)
    if not trace:
        return {"ok": False, "error": "Job not found"}
    return {"ok": True, **trace}


@router.get("/api/analysis-jobs/{job_id}/events")
async def stream_analysis_job_events(job_id: str):
    """Stream queued/running/completed events for an analysis job."""
    return _sse_response(_analysis_job_event_stream(job_id))


@router.get("/api/runtime/stats")
async def get_runtime_stats(range: str = "1d"):
    """Get aggregate runtime stats for analysis jobs."""
    return {"ok": True, "stats": ajs.get_stats(range)}


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


@router.get("/api/report/stream")
async def generate_report_stream():
    """Stream LLM-powered market report."""
    return _sse_response(_stream_llm_chunks(rs.generate_market_report_stream()))


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


def _detect_stock_comparison_intent(message: str) -> dict[str, Any] | None:
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
            quote = ss.get_quote(symbol)
        except Exception:
            quote = {"ok": False}
        if quote.get("ok") and symbol not in valid_symbols:
            valid_symbols.append(symbol)

    if len(valid_symbols) < 2:
        return None

    return {"symbols": valid_symbols, "objective": message.strip()}


def _build_chat_agent(conversation_id: int) -> WardMiniAgent:
    agent = WardMiniAgent()
    history = hs.conversations.get_messages(conversation_id, limit=20)
    agent.load_conversation_history(history)
    return agent

@router.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Send a chat message and get AI response (non-streaming)."""
    conversation_id = req.conversation_id or hs.conversations.create_conversation()
    agent = _build_chat_agent(conversation_id)
    hs.conversations.add_message(conversation_id, "user", req.message)
    final_reply = ""
    async for chunk in agent.chat_stream(conversation_id, req.message, req.context):
        if chunk.get("chunk"):
            final_reply += chunk.get("chunk", "")
        if chunk.get("done"):
            break
    if final_reply:
        hs.conversations.add_message(conversation_id, "assistant", final_reply)
    return ChatResponse(
        ok=True,
        conversation_id=conversation_id,
        reply=final_reply,
        messages=[],
        error=None,
    )


@router.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """Send a chat message and stream AI response chunks via SSE."""
    conversation_id = req.conversation_id or hs.conversations.create_conversation()
    agent = _build_chat_agent(conversation_id)
    hs.conversations.add_message(conversation_id, "user", req.message)
    cancel_event = _get_or_create_cancel_event(conversation_id)

    async def event_generator():
        reply_parts: list[str] = []
        try:
            yield await sse_format({"conversation_id": conversation_id}, conversation_id)
            comparison = _detect_stock_comparison_intent(req.message)
            if comparison:
                job = await ajs.create_job("stock_comparison", comparison)
                symbols = "、".join(comparison["symbols"])
                reply = (
                    f"已为 {symbols} 创建多股对比 Team 任务。"
                    f"你可以在 Runtime 查看 Leader / Worker / Verifier 的执行过程：/runtime?job_id={job['id']}"
                )
                assistant_message_id = hs.conversations.add_message(conversation_id, "assistant", reply)
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
                yield await sse_format(chunk, conversation_id)
                if chunk.get("done"):
                    reply = "".join(reply_parts).strip()
                    if reply:
                        hs.conversations.add_message(conversation_id, "assistant", reply)
                    break
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
async def update_chat_message(conversation_id: int, message_id: int, req: ChatMessageUpdateRequest):
    """Update a persisted assistant message after an async job completes."""
    ok = hs.conversations.update_message(conversation_id, message_id, "assistant", req.content)
    if not ok:
        return {"ok": False, "error": "Message not found"}
    return {"ok": True}


@router.get("/api/history/{conversation_id}", response_model=HistoryResponse)
async def get_history(conversation_id: int):
    """Get chat history for a conversation (latest 20 messages)."""
    result = hs.get_history(conversation_id)
    return HistoryResponse(
        ok=result.get("ok", False),
        conversation_id=result.get("conversation_id"),
        messages=[MessageResponse(**m) for m in result.get("messages", [])],
        error=result.get("error"),
    )


@router.get("/api/history/{conversation_id}/messages", response_model=HistoryPaginatedResponse)
async def get_history_paginated(conversation_id: int, limit: int = 20, before_id: int | None = None):
    """Get older messages using cursor pagination (waterfall load)."""
    result = hs.get_history_paginated(conversation_id, limit, before_id)
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


@router.get("/api/stock/{symbol}/analyze/stream")
async def analyze_stock_stream(symbol: str):
    """Stream AI-powered stock analysis report."""
    return _sse_response(_stream_llm_chunks(ss.generate_analysis_stream(symbol)))


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
