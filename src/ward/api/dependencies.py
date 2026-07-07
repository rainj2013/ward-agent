"""Application service container and FastAPI dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from ward.services.analysis_job_service import AnalysisJobService
from ward.services.history_service import HistoryService
from ward.services.index_service import IndexService
from ward.services.nasdaq_service import MarketService
from ward.services.report_service import ReportService
from ward.services.settings_service import SettingsService
from ward.services.stock_comparison_service import StockComparisonService
from ward.services.stock_service import StockService


@dataclass
class RuntimeServices:
    market: MarketService
    report: ReportService
    history: HistoryService
    stock: StockService
    comparison: StockComparisonService
    index: IndexService
    settings: SettingsService
    jobs: AnalysisJobService


def create_runtime_services() -> RuntimeServices:
    market = MarketService()
    report = ReportService()
    history = HistoryService()
    stock = StockService()
    comparison = StockComparisonService()
    index = IndexService()
    settings = SettingsService()
    jobs = AnalysisJobService(concurrency=1)
    jobs.register_handler("stock_analysis", lambda payload: stock.generate_analysis(payload["symbol"], trace=payload.get("_trace")))
    jobs.register_handler("index_analysis", lambda payload: index.generate_analysis(payload["prefix"], trace=payload.get("_trace")))
    jobs.register_handler("market_report", lambda payload: report.generate_market_report(trace=payload.get("_trace")))
    jobs.register_handler(
        "stock_comparison",
        lambda payload: comparison.generate_comparison(
            payload["symbols"], payload.get("objective"), trace=payload.get("_trace")
        ),
    )
    return RuntimeServices(market, report, history, stock, comparison, index, settings, jobs)


def get_services(request: Request) -> RuntimeServices:
    return request.app.state.services
