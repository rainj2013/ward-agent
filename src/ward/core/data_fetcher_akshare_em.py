"""
AKShare (Eastmoney) — 无需手动配置 Cookie。
前提：在运行此代码的机器上打开浏览器访问 eastmoney.com 并登录一次。
登录后 Cookie 会自动与该 IP 绑定，之后 akshare 的东方财富接口即可正常使用。
（参考：https://www.cnblogs.com/snowlove67/p/19015348）

如需手动传入 Cookie（可选），请设置环境变量 EASTMONEY_COOKIES 为 JSON 格式。
"""

from __future__ import annotations

import json
import os
from typing import Any

import akshare as ak


# ── 可选：环境变量传入 Cookie（不推荐，仅特殊场景使用）────────────────────────
def _get_env_cookies() -> dict[str, str] | None:
    raw = os.environ.get("EASTMONEY_COOKIES")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


# ── 东方财富接口（需要 IP 已登录）─────────────────────────────────────────────

def stock_us_spot_em() -> list[dict[str, Any]]:
    """
    东方财富-美股实时行情。
    返回所有美股实时报价（最新价、涨跌幅、成交量、市盈率等）。
    需要：运行本代码的机器 IP 已登录 eastmoney.com
    """
    return ak.stock_us_spot_em()


def stock_us_hist_em(symbol: str, period: str = "daily",
                    start_date: str = "19700101",
                    end_date: str = "22220101",
                    adjust: str = "") -> list[dict[str, Any]]:
    """
    东方财富-美股历史行情。
    :param symbol:   股票代码，如 "AAPL"
    :param period:   "daily" | "weekly" | "monthly"
    :param start_date: YYYYMMDD
    :param end_date:   YYYYMMDD
    :param adjust:   "" | "qfq" | "hfq"
    """
    df = ak.stock_us_hist(
        symbol=symbol, period=period,
        start_date=start_date, end_date=end_date,
        adjust=adjust,
    )
    if df is None or df.empty:
        return []
    return df.to_dict("records")


def stock_zh_a_spot_em() -> list[dict[str, Any]]:
    """
    东方财富-A股实时行情。
    需要：运行本代码的机器 IP 已登录 eastmoney.com
    """
    df = ak.stock_zh_a_spot_em()
    return df.to_dict("records") if not df.empty else []


def stock_zh_a_hist(symbol: str, period: str = "daily",
                    start_date: str = "19700101",
                    end_date: str = "22220101",
                    adjust: str = "") -> list[dict[str, Any]]:
    """
    东方财富-A股历史行情。
    :param symbol:  股票代码，如 "000001"（平安银行）
    :param adjust: "" | "qfq" | "hfq"
    """
    df = ak.stock_zh_a_hist(
        symbol=symbol, period=period,
        start_date=start_date, end_date=end_date,
        adjust=adjust,
    )
    if df is None or df.empty:
        return []
    return df.to_dict("records")


def index_spot_em(market: str = "美股") -> list[dict[str, Any]]:
    """
    东方财富-指数实时行情。
    :param market: "美股" | "沪深" | "港股"
    """
    df = ak.index_us_spot_em() if market == "美股" else ak.index_zh_a_spot_em()
    return df.to_dict("records") if not df.empty else []


def financial_us_report_em(symbol: str) -> list[dict[str, Any]]:
    """
    东方财富-美股财务报告（利润表、资产负债表、现金流量表）。
    """
    df = ak.stock_financial_us_report_em(symbol=symbol)
    return df.to_dict("records") if not df.empty else []


def financial_us_indicator_em(symbol: str) -> list[dict[str, Any]]:
    """
    东方财富-美股财务分析指标（ROE、ROA、毛利率、净利率等）。
    """
    df = ak.stock_financial_us_analysis_indicator_em(symbol=symbol)
    return df.to_dict("records") if not df.empty else []


# ── 验证接口是否可用 ─────────────────────────────────────────────────────────

def is_em_available() -> bool:
    """
    检测东方财富接口是否可用（IP 已登录返回 True）。
    """
    try:
        ak.stock_us_spot_em()
        return True
    except Exception:
        return False


if __name__ == "__main__":
    print("检测东方财富接口可用性...")
    if is_em_available():
        print("✓ 东方财富接口可用（IP 已登录）")
    else:
        print("✗ 东方财富接口不可用")
        print("  请在运行本程序的机器上打开浏览器访问 https://www.eastmoney.com 并登录一次")
