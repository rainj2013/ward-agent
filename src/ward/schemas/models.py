"""Pydantic schemas for API request/response models."""

from __future__ import annotations

from pydantic import BaseModel


# ─── Chat Context Schemas ────────────────────────────────────────────────────

class MarketDataItem(BaseModel):
    """Single market index today's snapshot."""
    name: str
    close: float
    change: float
    change_pct: float
    open: float
    high: float
    low: float
    volume: float


class StockDataItem(BaseModel):
    """Single stock today's snapshot."""
    name: str
    close: float
    change: float
    change_pct: float
    open: float
    high: float
    low: float
    volume: float


class KlineItem(BaseModel):
    """OHLCV bar for a single trading day."""
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class ExtendedHoursItem(BaseModel):
    """Pre-market / regular / after-hours snapshot for an index (via ETF)."""
    pre: dict | None = None       # {"price": float}
    regular: dict | None = None   # {"price": float}
    after: dict | None = None     # {"price": float}
    previous_close: float = 0


class ChatContext(BaseModel):
    """Full context data from UI — all loaded data is sent for rich AI answers."""
    # Today's snapshot (same as before)
    indices: list[MarketDataItem] = []
    stocks: list[StockDataItem] = []
    # 60-day raw kline data keyed by index prefix or stock symbol
    index_klines: dict[str, list[KlineItem]] = {}
    stock_klines: dict[str, list[KlineItem]] = {}
    # AI analysis texts keyed by stock symbol
    stock_analyses: dict[str, str] = {}
    # Index AI analysis reports: prefix -> report text
    index_analyses: dict[str, str] = {}
    # Extended hours data: prefix -> ExtendedHoursItem
    extended_hours: dict[str, ExtendedHoursItem] = {}


# ─── Request / Response Schemas ──────────────────────────────────────────────

class QuoteResponse(BaseModel):
    ok: bool
    data: dict | None = None
    error: str | None = None


class MarketOverviewResponse(BaseModel):
    ok: bool
    nasdaq_composite: dict | None = None
    nasdaq_100: dict | None = None
    dow_jones: dict | None = None
    sp500: dict | None = None


class ReportResponse(BaseModel):
    ok: bool
    report: str | None = None
    data: dict | None = None
    error: str | None = None


class ChatRequest(BaseModel):
    conversation_id: int | None = None
    message: str
    context: ChatContext | None = None


class MessageResponse(BaseModel):
    role: str
    content: str
    created_at: str


class ChatResponse(BaseModel):
    ok: bool
    conversation_id: int | None = None
    reply: str | None = None
    messages: list[MessageResponse] | None = None
    error: str | None = None


class HistoryResponse(BaseModel):
    ok: bool
    conversation_id: int
    messages: list[MessageResponse]
    has_more: bool = False
    next_before_id: int | None = None
    error: str | None = None


class HistoryPaginatedResponse(BaseModel):
    ok: bool
    conversation_id: int
    messages: list[MessageResponse]
    has_more: bool
    next_before_id: int | None = None
    error: str | None = None


class StockSearchResponse(BaseModel):
    ok: bool
    results: list[dict] = []


class StockQuoteResponse(BaseModel):
    ok: bool
    data: dict | None = None
    error: str | None = None


class StockHistoryResponse(BaseModel):
    ok: bool
    symbol: str | None = None
    name: str | None = None
    data: list[dict] = []
    error: str | None = None


class StockAnalysisResponse(BaseModel):
    ok: bool
    symbol: str | None = None
    name: str | None = None
    report: str | None = None
    data: dict | None = None
    error: str | None = None


class StockKlineResponse(BaseModel):
    ok: bool
    symbol: str | None = None
    name: str | None = None
    data: list[dict] = []
    error: str | None = None


class IndexAnalysisResponse(BaseModel):
    ok: bool
    prefix: str | None = None
    name: str | None = None
    report: str | None = None
    data: dict | None = None
    error: str | None = None


class ExtendedPriceResponse(BaseModel):
    ok: bool
    symbol: str | None = None
    name: str | None = None
    date: str | None = None
    pre_market: dict | None = None  # {"price": float, "time": str}
    regular: dict | None = None     # {"price": float, "time": str}
    after_hours: dict | None = None  # {"price": float, "time": str}
    previous_close: float | None = None
    error: str | None = None
