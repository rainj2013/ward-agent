"""Stock quote, history, search, and analysis routes."""

from fastapi import APIRouter, Depends

from ward.api.dependencies import RuntimeServices, get_services
from ward.api.sse import sse_response, stream_sync_chunks
from ward.schemas.models import (
    ExtendedPriceResponse,
    StockAnalysisResponse,
    StockHistoryResponse,
    StockKlineResponse,
    StockQuoteResponse,
    StockSearchResponse,
)


router = APIRouter(prefix="/api/stock", tags=["stock"])


@router.get("/search", response_model=StockSearchResponse)
def search_stock(q: str, services: RuntimeServices = Depends(get_services)):
    result = services.stock.search(q)
    return StockSearchResponse(ok=True, results=result.get("results", []))


@router.get("/{symbol}/quote", response_model=StockQuoteResponse)
def get_stock_quote(symbol: str, services: RuntimeServices = Depends(get_services)):
    result = services.stock.get_quote(symbol)
    return StockQuoteResponse(ok=result.get("ok", False), data=result.get("data"), error=result.get("error"))


@router.get("/{symbol}/history", response_model=StockHistoryResponse)
def get_stock_history(symbol: str, days: int = 30, services: RuntimeServices = Depends(get_services)):
    result = services.stock.get_historical(symbol, days)
    return StockHistoryResponse(
        ok=result.get("ok", False), symbol=result.get("symbol"), name=result.get("name"),
        data=result.get("data", []), error=result.get("error"),
    )


@router.get("/{symbol}/kline", response_model=StockKlineResponse)
def get_stock_kline(symbol: str, days: int = 30, services: RuntimeServices = Depends(get_services)):
    result = services.stock.get_kline(symbol, days)
    return StockKlineResponse(
        ok=result.get("ok", False), symbol=result.get("symbol"), name=result.get("name"),
        data=result.get("data", []), error=result.get("error"),
    )


@router.get("/{symbol}/analyze", response_model=StockAnalysisResponse)
def analyze_stock(symbol: str, services: RuntimeServices = Depends(get_services)):
    result = services.stock.generate_analysis(symbol)
    return StockAnalysisResponse(
        ok=result.get("ok", False), symbol=result.get("symbol"), name=result.get("name"),
        report=result.get("report"), data=result.get("data"), cached=result.get("cached"),
        error=result.get("error"),
    )


@router.get("/{symbol}/analyze/stream")
async def analyze_stock_stream(symbol: str, services: RuntimeServices = Depends(get_services)):
    return sse_response(stream_sync_chunks(services.stock.generate_analysis_stream(symbol)))


@router.get("/{symbol}/extended", response_model=ExtendedPriceResponse)
def get_extended_price(symbol: str, services: RuntimeServices = Depends(get_services)):
    result = services.stock.get_extended_price(symbol)
    return ExtendedPriceResponse(
        ok=result.get("ok", False), symbol=result.get("symbol"), name=result.get("name"),
        date=result.get("date"), pre_market=result.get("pre_market"), regular=result.get("regular"),
        after_hours=result.get("after_hours"), previous_close=result.get("previous_close"),
        error=result.get("error"),
    )
