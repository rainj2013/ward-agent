"""Market quote, index analysis, and market report routes."""

from fastapi import APIRouter, Depends

from ward.api.dependencies import RuntimeServices, get_services
from ward.api.sse import sse_response, stream_sync_chunks
from ward.schemas.models import IndexAnalysisResponse, MarketOverviewResponse, QuoteResponse, ReportResponse


router = APIRouter(prefix="/api", tags=["market"])


def _quote_response(result: dict) -> QuoteResponse:
    return QuoteResponse(ok=result.get("ok", False), data=result.get("data"), error=result.get("error"))


@router.get("/quote", response_model=QuoteResponse)
def get_quote(services: RuntimeServices = Depends(get_services)):
    return _quote_response(services.market.get_quote())


@router.get("/ndx-quote", response_model=QuoteResponse)
def get_ndx_quote(services: RuntimeServices = Depends(get_services)):
    return _quote_response(services.market.get_ndx_quote())


@router.get("/dji-quote", response_model=QuoteResponse)
def get_dji_quote(services: RuntimeServices = Depends(get_services)):
    return _quote_response(services.market.get_dji_quote())


@router.get("/spx-quote", response_model=QuoteResponse)
def get_spx_quote(services: RuntimeServices = Depends(get_services)):
    return _quote_response(services.market.get_spx_quote())


@router.get("/gold-quote", response_model=QuoteResponse)
def get_gold_quote(services: RuntimeServices = Depends(get_services)):
    return _quote_response(services.market.get_gold_quote())


@router.get("/market-overview", response_model=MarketOverviewResponse)
def get_market_overview(services: RuntimeServices = Depends(get_services)):
    result = services.market.get_market_overview()
    return MarketOverviewResponse(
        ok=result.get("ok", False), nasdaq_composite=result.get("nasdaq_composite"),
        nasdaq_100=result.get("nasdaq_100"), dow_jones=result.get("dow_jones"),
        sp500=result.get("sp500"), gold=result.get("gold"),
    )


@router.get("/index/{prefix}/analyze", response_model=IndexAnalysisResponse)
def analyze_index(prefix: str, services: RuntimeServices = Depends(get_services)):
    result = services.index.generate_analysis(prefix)
    return IndexAnalysisResponse(
        ok=result.get("ok", False), prefix=result.get("prefix"), name=result.get("name"),
        report=result.get("report"), data=result.get("data"), error=result.get("error"),
    )


@router.get("/index/{prefix}/analyze/stream")
async def analyze_index_stream(prefix: str, services: RuntimeServices = Depends(get_services)):
    return sse_response(stream_sync_chunks(services.index.generate_analysis_stream(prefix)))


@router.get("/report", response_model=ReportResponse)
def generate_report(services: RuntimeServices = Depends(get_services)):
    result = services.report.generate_market_report()
    return ReportResponse(
        ok=result.get("ok", False), report=result.get("report"),
        data=result.get("data"), error=result.get("error"),
    )


@router.get("/report/stream")
async def generate_report_stream(services: RuntimeServices = Depends(get_services)):
    return sse_response(stream_sync_chunks(services.report.generate_market_report_stream()))
