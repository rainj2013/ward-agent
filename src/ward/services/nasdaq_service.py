"""Market data service — business logic for US market indices."""

from __future__ import annotations

from typing import Any

from ward.core.data_fetcher import DataFetcher


class MarketService:
    """Business logic for US market indices."""

    def __init__(self):
        self.fetcher = DataFetcher()

    def get_dji_quote(self) -> dict[str, Any]:
        """Get Dow Jones quote."""
        data = self.fetcher.get_dji_quote()
        if "error" in data:
            return {"ok": False, "error": data["error"]}
        return {"ok": True, "data": data}

    def get_spx_quote(self) -> dict[str, Any]:
        """Get S&P 500 quote."""
        data = self.fetcher.get_spx_quote()
        if "error" in data:
            return {"ok": False, "error": data["error"]}
        return {"ok": True, "data": data}

    def get_quote(self) -> dict[str, Any]:
        """Get Nasdaq Composite quote with formatted response."""
        data = self.fetcher.get_nasdaq_quote()
        if "error" in data:
            return {"ok": False, "error": data["error"]}

        return {
            "ok": True,
            "data": {
                "symbol": data["symbol"],
                "name": data["name"],
                "date": data["date"],
                "close": data["close"],
                "open": data["open"],
                "high": data["high"],
                "low": data["low"],
                "volume": data["volume"],
                "change": data["change"],
                "change_pct": data["change_pct"],
            },
        }

    def get_ndx_quote(self) -> dict[str, Any]:
        """Get Nasdaq 100 quote."""
        data = self.fetcher.get_nasdaq_100_quote()
        if "error" in data:
            return {"ok": False, "error": data["error"]}

        return {
            "ok": True,
            "data": {
                "symbol": data["symbol"],
                "name": data["name"],
                "date": data["date"],
                "close": data["close"],
                "open": data["open"],
                "high": data["high"],
                "low": data["low"],
                "volume": data["volume"],
                "change": data["change"],
                "change_pct": data["change_pct"],
            },
        }

    def get_market_overview(self) -> dict[str, Any]:
        """Get combined market overview for all three US indices."""
        ixic = self.fetcher.get_nasdaq_quote()
        ndx = self.fetcher.get_nasdaq_100_quote()
        dji = self.fetcher.get_dji_quote()
        spx = self.fetcher.get_spx_quote()

        return {
            "ok": True,
            "nasdaq_composite": ixic if "error" not in ixic else None,
            "nasdaq_100": ndx if "error" not in ndx else None,
            "dow_jones": dji if "error" not in dji else None,
            "sp500": spx if "error" not in spx else None,
        }
