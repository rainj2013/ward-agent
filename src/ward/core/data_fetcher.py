"""AKShare wrapper — single entry point for all market data."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import akshare as ak


class DataFetcher:
    """Unified data fetching via AKShare."""

    @staticmethod
    def get_nasdaq_quote() -> dict[str, Any]:
        """Fetch Nasdaq Composite (.IXIC) quote."""
        try:
            df = ak.index_us_stock_sina(symbol=".IXIC")
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            close = float(latest.get("close", 0))
            prev_close = float(prev.get("close", 0))
            change = round(close - prev_close, 2)
            change_pct = round((change / prev_close) * 100, 2) if prev_close else 0
            return {
                "symbol": ".IXIC",
                "name": "Nasdaq Composite",
                "date": str(latest.get("date", datetime.now().strftime("%Y-%m-%d"))),
                "close": close,
                "open": float(latest.get("open", 0)),
                "high": float(latest.get("high", 0)),
                "low": float(latest.get("low", 0)),
                "volume": float(latest.get("volume", 0)),
                "change": change,
                "change_pct": change_pct,
            }
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def get_nasdaq_100_quote() -> dict[str, Any]:
        """Fetch Nasdaq 100 (.NDX) quote."""
        try:
            df = ak.index_us_stock_sina(symbol=".NDX")
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            close = float(latest.get("close", 0))
            prev_close = float(prev.get("close", 0))
            change = round(close - prev_close, 2)
            change_pct = round((change / prev_close) * 100, 2) if prev_close else 0
            return {
                "symbol": ".NDX",
                "name": "Nasdaq 100",
                "date": str(latest.get("date", datetime.now().strftime("%Y-%m-%d"))),
                "close": close,
                "open": float(latest.get("open", 0)),
                "high": float(latest.get("high", 0)),
                "low": float(latest.get("low", 0)),
                "volume": float(latest.get("volume", 0)),
                "change": change,
                "change_pct": change_pct,
            }
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def get_us_index_spot() -> dict[str, Any]:
        """Fetch US spot indices (S&P 500, Dow, etc.)."""
        try:
            df = ak.index_us_spot_index()
            return {"data": df.to_dict("records") if not df.empty else [], "error": None}
        except Exception as e:
            return {"data": [], "error": str(e)}

    @staticmethod
    def get_dji_quote() -> dict[str, Any]:
        """Fetch Dow Jones Industrial Average (.DJI) quote."""
        try:
            df = ak.index_us_stock_sina(symbol=".DJI")
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            close = float(latest.get("close", 0))
            prev_close = float(prev.get("close", 0))
            change = round(close - prev_close, 2)
            change_pct = round((change / prev_close) * 100, 2) if prev_close else 0
            return {
                "symbol": ".DJI",
                "name": "Dow Jones",
                "date": str(latest.get("date", datetime.now().strftime("%Y-%m-%d"))),
                "close": close,
                "open": float(latest.get("open", 0)),
                "high": float(latest.get("high", 0)),
                "low": float(latest.get("low", 0)),
                "volume": float(latest.get("volume", 0)),
                "change": change,
                "change_pct": change_pct,
            }
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def get_spx_quote() -> dict[str, Any]:
        """Fetch S&P 500 (.INX) quote."""
        try:
            df = ak.index_us_stock_sina(symbol=".INX")
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            close = float(latest.get("close", 0))
            prev_close = float(prev.get("close", 0))
            change = round(close - prev_close, 2)
            change_pct = round((change / prev_close) * 100, 2) if prev_close else 0
            return {
                "symbol": ".INX",
                "name": "S&P 500",
                "date": str(latest.get("date", datetime.now().strftime("%Y-%m-%d"))),
                "close": close,
                "open": float(latest.get("open", 0)),
                "high": float(latest.get("high", 0)),
                "low": float(latest.get("low", 0)),
                "volume": float(latest.get("volume", 0)),
                "change": change,
                "change_pct": change_pct,
            }
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def get_nasdaq_100_components() -> dict[str, Any]:
        """Fetch Nasdaq 100 component stocks."""
        try:
            df = ak.index_nasdaq_100_cons()
            return {"data": df.to_dict("records") if not df.empty else [], "error": None}
        except Exception as e:
            return {"data": [], "error": str(e)}
