"""
AKShare (Sina) data fetcher — NO LOGIN REQUIRED.
基于新浪财经的数据接口，免费即用。
适合：美股历史日线（stock_us_daily）、指数历史（index_us_stock_sina）
不稳定/不可用：美股实时行情（需要 JS 解密）、东方财富接口（需登录）
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any

import akshare as ak
import pandas as pd


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def _with_retry(fn, max_attempts=3, delay=2):
    """带重试的调用。"""
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as e:
            if attempt == max_attempts - 1:
                raise
            time.sleep(delay * (attempt + 1))


# ── 美股：历史日线（稳定）────────────────────────────────────────────────────

def stock_us_daily(symbol: str, adjust: str = "") -> pd.DataFrame:
    """
    新浪财经-美股历史日线（无需登录，稳定可用）。
    :param symbol:  股票代码，如 "AAPL"、"NVDA"
    :param adjust: "" | "qfq" | "hfq" | "qfq-factor"
    :return: DataFrame，index 为日期，columns: open/high/low/close/volume/amount
    """
    return ak.stock_us_daily(symbol=symbol, adjust=adjust)


def stock_us_hist_sina(symbol: str, days: int = 30) -> list[dict[str, Any]]:
    """
    获取美股历史 K 线（新浪日线）。
    :param symbol:  股票代码
    :param days:    最近多少个交易日
    :return: [{date, open, high, low, close, volume}, ...]
    """
    df = ak.stock_us_daily(symbol=symbol, adjust="")
    if df.empty:
        return []
    df = df.tail(days)
    records = []
    for _, row in df.iterrows():
        records.append({
            "date":   str(row.get("date", "")),
            "open":   round(float(row["open"]), 2),
            "high":   round(float(row["high"]), 2),
            "low":    round(float(row["low"]), 2),
            "close":  round(float(row["close"]), 2),
            "volume": float(row.get("volume", 0)),
        })
    return records


# ── 美股：指数（稳定）────────────────────────────────────────────────────────

def index_us_stock_sina(symbol: str = ".IXIC") -> pd.DataFrame:
    """
    新浪财经-美股指数历史（无需登录，稳定可用）。
    :param symbol: ".IXIC"=Nasdaq Composite, ".NDX"=Nasdaq 100,
                   ".DJI"=Dow Jones, ".INX"=S&P 500
    :return: DataFrame，index 为日期
    """
    return ak.index_us_stock_sina(symbol=symbol)


def index_quote(symbol: str = ".IXIC", days: int = 5) -> dict[str, Any]:
    """
    获取指数最新报价和近期统计。
    :param symbol:  .IXIC | .NDX | .DJI | .INX
    :param days:    用于计算近期高低点
    :return: {symbol, name, date, close, open, high, low, volume, change, change_pct}
    """
    df = ak.index_us_stock_sina(symbol=symbol)
    if df.empty:
        return {"error": f"No data for {symbol}"}
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest
    name_map = {
        ".IXIC": "Nasdaq Composite",
        ".NDX": "Nasdaq 100",
        ".DJI": "Dow Jones",
        ".INX": "S&P 500",
    }
    close = float(latest.get("close", 0))
    prev_close = float(prev.get("close", 0))
    change = round(close - prev_close, 2)
    change_pct = round((change / prev_close) * 100, 2) if prev_close else 0

    recent = df.tail(days)
    return {
        "symbol":     symbol,
        "name":      name_map.get(symbol, symbol),
        "date":      str(latest.name.date()) if hasattr(latest.name, "date") else str(latest.get("date", "")),
        "close":     close,
        "open":      round(float(latest.get("open", 0)), 2),
        "high":      round(float(recent["high"].max()), 2) if not recent.empty else 0,
        "low":       round(float(recent["low"].min()), 2) if not recent.empty else 0,
        "volume":    float(latest.get("volume", 0)),
        "change":    change,
        "change_pct": change_pct,
        "recent_high": round(float(recent["high"].max()), 2),
        "recent_low":  round(float(recent["low"].min()), 2),
    }


# ── A股：实时行情（东方财富封禁，需登录）─────────────────────────────────────
# 如需使用，请先配置 data_fetcher_akshare_em.py 的 Cookie

def stock_zh_a_spot_ak() -> list[dict[str, Any]]:
    """
    A股实时行情（akshare 默认接口，内部调用东方财富）。
    注意：需要配置 data_fetcher_akshare_em.py 的登录 Cookie！
    无 Cookie 时返回空列表。
    """
    try:
        df = ak.stock_zh_a_spot_em()
        return df.to_dict("records") if not df.empty else []
    except Exception as e:
        return []


# ── 宏观/经济数据（通常无需登录）─────────────────────────────────────────────

def macro_usa_nasdaq() -> pd.DataFrame | None:
    """美国纳斯达克综合指数宏观数据。"""
    try:
        return ak.macro_usa_nasdaq()
    except Exception:
        return None


def macro_usa_interest_rate() -> pd.DataFrame | None:
    """美国联邦基金利率。"""
    try:
        return ak.macro_bank_usa_interest_rate()
    except Exception:
        return None


def macro_usa_cpi() -> pd.DataFrame | None:
    """美国 CPI 数据。"""
    try:
        return ak.macro_usa_cpi_monthly()
    except Exception:
        return None


# ── 港股（需要登录东方财富，暂不可用）────────────────────────────────────────

def stock_hk_spot_em() -> list[dict[str, Any]]:
    """
    东方财富-港股实时行情（需要登录 Cookie）。
    需要先在 data_fetcher_akshare_em.py 中配置 COOKIES。
    """
    raise NotImplementedError(
        "港股数据需要东方财富登录 Cookie。"
        "请先运行 data_fetcher_akshare_em.py --setup 配置 Cookie。"
    )


# ── 测试入口 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json, time

    print("=== 测试 Sina 美股历史日线 ===")
    df = ak.stock_us_daily("AAPL")
    print(f"AAPL 历史数据: {len(df)} 条，最新: {df.iloc[-1].to_dict()}")

    print()
    print("=== 测试指数报价 ===")
    for sym in [".IXIC", ".NDX", ".DJI", ".INX"]:
        r = index_quote(sym, days=5)
        print(f"{sym}: close={r['close']}, change={r['change_pct']}%")
        time.sleep(1)
