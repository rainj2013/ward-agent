"""Ward market data tools — Mini-Agent Tool subclasses."""

import json
from typing import Any

from ward.mini_agent.tools.base import Tool, ToolResult


class GetStockQuoteTool(Tool):
    """获取美股个股的实时行情（今日开盘价、收盘价、涨跌幅、成交量等）。"""

    @property
    def name(self) -> str:
        return "get_stock_quote"

    @property
    def description(self) -> str:
        return "获取美股个股的实时行情（今日开盘价、收盘价、涨跌幅、成交量等）。当用户问起某只股票的当前价格或今日表现时调用。"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "股票代码（美股），如 AAPL、TSLA、MSFT、NVDA",
                }
            },
            "required": ["symbol"],
        }

    async def execute(self, symbol: str = "", **kwargs) -> ToolResult:
        from ward.services.stock_service import StockService

        sym = symbol.upper()
        ss = StockService()
        result = ss.get_quote(sym)
        if result.get("ok"):
            d = result["data"]
            return ToolResult(
                success=True,
                content=json.dumps(
                    {
                        "ok": True,
                        "symbol": sym,
                        "name": d.get("name", sym),
                        "close": d.get("close"),
                        "change": d.get("change"),
                        "change_pct": d.get("change_pct"),
                        "open": d.get("open"),
                        "high": d.get("high"),
                        "low": d.get("low"),
                        "volume": d.get("volume"),
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            )
        return ToolResult(success=False, content="", error=result.get("error", "获取失败"))


class GetStockKlineTool(Tool):
    """获取美股个股的历史K线数据（60日日K线，OHLCV格式）。注意：此工具仅适用于个股，不适用于指数。"""

    @property
    def name(self) -> str:
        return "get_stock_kline"

    @property
    def description(self) -> str:
        return "获取美股个股的历史K线数据（60日日K线，OHLCV格式）。当用户问起某只股票的历史走势、近期趋势时调用。此工具仅适用于个股（如AAPL、TSLA），不适用于指数。"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "股票代码（仅限美股个股），如 AAPL、TSLA、MSFT、NVDA"},
                "days": {
                    "type": "integer",
                    "description": "天数，默认60",
                    "default": 60,
                },
            },
            "required": ["symbol"],
        }

    async def execute(self, symbol: str = "", days: int = 60, **kwargs) -> ToolResult:
        from ward.services.stock_service import StockService

        sym = symbol.upper()
        ss = StockService()
        result = ss.get_kline(sym, days)
        if result.get("ok"):
            return ToolResult(
                success=True,
                content=json.dumps({"ok": True, "symbol": sym, "bars": result.get("data", [])}, ensure_ascii=False, default=str),
            )
        return ToolResult(success=False, content="", error=result.get("error", "获取失败"))


class GetStockAnalyzeTool(Tool):
    """获取AI驱动的个股分析报告（含技术面、基本面、市场情绪综合分析）。"""

    @property
    def name(self) -> str:
        return "get_stock_analyze"

    @property
    def description(self) -> str:
        return "获取AI驱动的个股分析报告（含技术面、基本面、市场情绪综合分析）。当用户问某只股票的AI分析或投资建议时调用。"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "股票代码，如 AAPL、TSLA"},
            },
            "required": ["symbol"],
        }

    async def execute(self, symbol: str = "", **kwargs) -> ToolResult:
        from ward.services.stock_service import StockService

        sym = symbol.upper()
        ss = StockService()
        result = ss.generate_analysis(sym)
        if result.get("ok"):
            return ToolResult(
                success=True,
                content=json.dumps(
                    {
                        "ok": True,
                        "symbol": sym,
                        "name": result.get("name", sym),
                        "report": result.get("report", ""),
                        "data": result.get("data"),
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            )
        return ToolResult(success=False, content="", error=result.get("error", "分析失败"))


class GetIndexAnalyzeTool(Tool):
    """获取AI驱动的指数分析报告。"""

    @property
    def name(self) -> str:
        return "get_index_analyze"

    @property
    def description(self) -> str:
        return "获取AI驱动的指数分析报告，包含技术面、基本面情绪综合分析。当用户问某指数（标普500、纳斯达克、道琼斯）的AI分析或投资建议时调用。"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prefix": {
                    "type": "string",
                    "description": "指数前缀：spx（标普500）、ixic（纳斯达克综合）、dji（道琼斯）",
                    "enum": ["spx", "ixic", "dji"],
                }
            },
            "required": ["prefix"],
        }

    async def execute(self, prefix: str = "", **kwargs) -> ToolResult:
        from ward.services.index_service import IndexService

        is_ = IndexService()
        result = is_.generate_analysis(prefix)
        if result.get("ok"):
            return ToolResult(
                success=True,
                content=json.dumps(
                    {
                        "ok": True,
                        "prefix": prefix,
                        "name": result.get("name", prefix),
                        "report": result.get("report", ""),
                        "data": result.get("data"),
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            )
        return ToolResult(success=False, content="", error=result.get("error", "分析失败"))


class GetIndexKlineTool(Tool):
    """获取美股指数的历史K线数据（60日日K线，OHLCV格式）。注意：此工具仅适用于指数，不适用于个股。"""

    @property
    def name(self) -> str:
        return "get_index_kline"

    @property
    def description(self) -> str:
        return "获取美股指数的历史K线数据（60日日K线，OHLCV格式）。当用户问起某个指数（标普500、纳斯达克、道琼斯）的近期走势或K线数据时调用。此工具仅适用于指数（spx/ixic/dji），不适用于个股。"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prefix": {
                    "type": "string",
                    "description": "指数前缀：spx（标普500）、ixic（纳斯达克综合）、dji（道琼斯）",
                    "enum": ["spx", "ixic", "dji"],
                },
                "days": {
                    "type": "integer",
                    "description": "天数，默认60",
                    "default": 60,
                },
            },
            "required": ["prefix"],
        }

    async def execute(self, prefix: str = "", days: int = 60, **kwargs) -> ToolResult:
        from ward.services.index_service import IndexService

        is_ = IndexService()
        result = is_.get_kline(prefix, days)
        if result.get("ok"):
            return ToolResult(
                success=True,
                content=json.dumps(
                    {
                        "ok": True,
                        "prefix": prefix,
                        "name": result.get("name", prefix),
                        "bars": result.get("data", []),
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            )
        return ToolResult(success=False, content="", error=result.get("error", "获取K线失败"))


class GetMarketOverviewTool(Tool):
    """获取美股三大指数（标普500、纳斯达克、道琼斯）和黄金的今日行情概览。"""

    @property
    def name(self) -> str:
        return "get_market_overview"

    @property
    def description(self) -> str:
        return "获取美股三大指数（标普500、纳斯达克、道琼斯）和黄金的今日行情概览。当用户问起今日市场整体表现或各指数涨跌时调用。"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> ToolResult:
        from ward.services.nasdaq_service import MarketService

        ms = MarketService()
        result = ms.get_market_overview()
        return ToolResult(success=True, content=json.dumps(result, ensure_ascii=False, default=str))


class GetExtendedHoursTool(Tool):
    """获取指数或个股的盘前、盘中、盘后价格数据。"""

    @property
    def name(self) -> str:
        return "get_extended_hours"

    @property
    def description(self) -> str:
        return "获取指数或个股的盘前、盘中、盘后价格数据。当用户问起盘前/盘后交易情况时调用。"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "指数前缀（spx/ixic/dji）或股票代码（如 AAPL）",
                }
            },
            "required": ["symbol"],
        }

    async def execute(self, symbol: str = "", **kwargs) -> ToolResult:
        from ward.services.stock_service import StockService

        result = StockService().get_extended_price(symbol)
        if result.get("ok"):
            return ToolResult(
                success=True,
                content=json.dumps(
                    {
                        "ok": True,
                        "symbol": symbol,
                        "date": result.get("date"),
                        "pre_market": result.get("pre_market"),
                        "regular": result.get("regular"),
                        "after_hours": result.get("after_hours"),
                        "previous_close": result.get("previous_close"),
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            )
        return ToolResult(success=False, content="", error=result.get("error", "获取失败"))


def get_all_tools() -> list[Tool]:
    """Return all Ward market data tools."""
    return [
        GetStockQuoteTool(),
        GetStockKlineTool(),
        GetStockAnalyzeTool(),
        GetIndexAnalyzeTool(),
        GetIndexKlineTool(),
        GetMarketOverviewTool(),
        GetExtendedHoursTool(),
    ]
