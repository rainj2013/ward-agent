"""Stock data service — yfinance primary + AKShare (sina) fallback."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import pandas as pd

import akshare as ak
import yfinance as yf
from anthropic import Anthropic

from ward.core.config import get_config


# Extended stock list for search
POPULAR_STOCKS = {
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corporation",
    "NVDA": "NVIDIA Corporation",
    "GOOGL": "Alphabet Inc. (Google)",
    "AMZN": "Amazon.com Inc.",
    "META": "Meta Platforms Inc.",
    "TSLA": "Tesla Inc.",
    "AMD": "Advanced Micro Devices",
    "NFLX": "Netflix Inc.",
    "AVGO": "Broadcom Inc.",
    "COST": "Costco Wholesale",
    "ORCL": "Oracle Corporation",
    "CRM": "Salesforce Inc.",
    "INTC": "Intel Corporation",
    "PYPL": "PayPal Holdings",
    "DIS": "Walt Disney Company",
    "V": "Visa Inc.",
    "MA": "Mastercard Inc.",
    "JPM": "JPMorgan Chase",
    "JNJ": "Johnson & Johnson",
}


class StockService:
    """Fetch individual US stock data via yfinance + AKShare fallback."""

    SYSTEM_PROMPT = """你是一个专业的金融分析师，擅长分析美国科技股的基本面和技术面。
根据提供的股票数据，生成结构化分析报告。

**输出格式要求（严格按此结构输出，每节必须有实质内容）：**

## 一、公司概况
[一句话概括公司核心业务和行业地位]

## 二、今日行情
| 指标 | 数值 |
|------|------|
| 当前股价 | $XXX.XX |
| 今日涨跌幅 | +X.XX% |
| 今日成交量 | X万/X百万股 |
| 日内高点 | $XXX.XX |
| 日内低点 | $XXX.XX |
| 52周高点 | $XXX.XX |
| 52周低点 | $XXX.XX |

## 三、估值分析
| 指标 | 数值 | 行业参考 |
|------|------|----------|
| 市盈率 (P/E) | X.X | 行业均值 XX |
| Forward P/E | X.X | - |
| 市销率 (P/S) | X.X | - |
| 市净率 (P/B) | X.X | - |
| PEG | X.X | <1 为低估 |

[指标若无数据标注"无数据"，并给出基于已知数据的解读]

## 四、财务数据
### 营收与盈利
- **近季度营收**：$XX亿（YoY +X%）
- **净利润率**：XX%
- **每股收益 (EPS)**：$X.XX

### 资产负债表
- **总资产**：$XX亿
- **总负债**：$XX亿
- **净资产收益率 (ROE)**：XX%

### 现金流
- **经营性现金流**：$XX亿
- **自由现金流 (FCF)**：$XX亿

[若无相关数据标注"无数据"，但必须基于现有数据给出尽可能完整的分析]

## 五、资金流向
### 机构持仓
- **机构持股比例**：XX%（如无数据标注"无数据"）
- **前三大机构股东**：列出前3大机构名称及持股比例

### 内部人员交易
- **近期内部人买卖**：列出最近3条重要内部人交易，注明是买入还是卖出

### 做空数据
- **做空股数/流通股数**：X%（如无数据标注"无数据"）
- **做空天数（Short Ratio）**：X天（如无数据标注"无数据"）

## 六、新闻舆情
### 近期新闻标题
|（新闻标题已在下方「=== 新闻舆情 ===」数据节提供）

### 新闻要点摘要
[根据以上新闻，用2-3句话概括市场关注焦点和舆论走向，如有10条以上新闻则重点总结前5条]

## 七、分析师观点
- **评级**：买入/持有/减持（如无数据标注"无数据"）
- **目标价**：$XXX（如无数据标注"无数据"）
- **核心逻辑**：[简述2-3条分析师看好或不看好的主要原因]

## 八、技术面分析
- **均线判断**：当前价格 vs MA5/MA20/MA60（突破/跌破/粘合）
- **近期趋势**：近5日走势（上涨/下跌/震荡）
- **关键价位**：重要支撑 $XXX，重要压力 $XXX
- **成交量**：今日量能对比5日均量（放量X% / 缩量X%）

## 九、投资亮点
[列出2-3条公司最主要的投资亮点，用数据说话]

## 十、主要风险
[列出2-3条公司面临的主要风险]

## 十一、综合简评
[用2-3句话给出综合判断，明确当前估值水平（低估/合理/高估）]

---
注意：所有数据必须来自提供的股票数据，不要编造数字。报告用中文撰写，突出重点，不要废话。"""

    def __init__(self):
        cfg = get_config()
        self._client = Anthropic(api_key=cfg.llm.api_key, base_url=cfg.llm.base_url)

    def _fetch_news(self, symbol: str, limit: int = 10) -> list[dict]:
        """Fetch stock news via akshare eastmoney (中文财经新闻)."""
        try:
            df = ak.stock_news_em(symbol=symbol)
            if df is None or df.empty:
                return []
            rows = []
            for _, row in df.head(limit).iterrows():
                rows.append({
                    "title": str(row.get("新闻标题", "")),
                    "time": str(row.get("发布时间", "")),
                    "source": str(row.get("文章来源", "")),
                })
            return rows
        except Exception:
            return []

    def _get_money_flow(self, symbol: str) -> dict[str, Any]:
        """Fetch institutional holders, insider transactions, short interest."""
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.fast_info
            full_info = ticker.info or {}

            result = {
                "institutions": [],
                "insider_transactions": [],
                "short_data": {},
            }

            # --- Institutional holders ---
            try:
                ih = ticker.institutional_holders
                if ih is not None and not ih.empty:
                    rows = []
                    for _, row in ih.head(5).iterrows():
                        rows.append({
                            "holder": str(row.get("Holder", "")),
                            "pct": float(row.get("pctHeld", 0)) * 100,
                            "shares": int(row.get("Shares", 0)),
                        })
                    result["institutions"] = rows
                    result["inst_pct"] = float(full_info.get("heldPercentInstitutions", 0)) * 100
            except Exception:
                pass

            # --- Insider transactions ---
            try:
                it = ticker.insider_transactions
                if it is not None and not it.empty:
                    rows = []
                    for _, row in it.head(5).iterrows():
                        rows.append({
                            "insider": str(row.get("Insider", "")),
                            "transaction": str(row.get("Transaction", "")),
                            "shares": int(row.get("Shares", 0)) if row.get("Shares") else 0,
                            "value": float(row.get("Value", 0)) if row.get("Value") else 0,
                            "date": str(row.get("Start Date", "")),
                        })
                    result["insider_transactions"] = rows
            except Exception:
                pass

            # --- Short interest ---
            try:
                result["short_data"] = {
                    "short_ratio": full_info.get("shortRatio"),
                    "short_percent_float": float(full_info.get("shortPercentOfFloat", 0)) * 100,
                    "shares_short": int(full_info.get("sharesShort", 0)),
                }
            except Exception:
                pass

            return result
        except Exception:
            return {"institutions": [], "insider_transactions": [], "short_data": {}}

    def _llm(self) -> Anthropic:
        return self._client

    def generate_analysis(self, symbol: str) -> dict[str, Any]:
        """Generate AI-powered stock analysis report."""
        symbol = symbol.upper()
        name = POPULAR_STOCKS.get(symbol, symbol)

        # Gather all available data
        quote = self.get_quote(symbol)
        hist_30d = self.get_historical(symbol, 30)
        hist_5d = self.get_historical(symbol, 5)
        financials = self._get_financials(symbol)
        news = self._fetch_news(symbol)
        money_flow = self._get_money_flow(symbol)

        # Build data context for LLM
        context = {
            "symbol": symbol,
            "name": name,
            "quote": quote.get("data") if quote.get("ok") else None,
            "history_5d": hist_5d.get("data") if hist_5d.get("ok") else [],
            "history_30d": hist_30d.get("data") if hist_30d.get("ok") else [],
            "financials": financials,
            "news": news,
            "money_flow": money_flow,
        }

        quote_data = context["quote"]
        fin = financials

        # Format financials as readable text for the prompt
        def fmt_currency(v):
            if v is None: return "无数据"
            if abs(v) >= 1e12: return f"${v/1e12:.2f}万亿"
            if abs(v) >= 1e9: return f"${v/1e9:.2f}亿"
            if abs(v) >= 1e6: return f"${v/1e6:.2f}百万"
            return f"${v:.2f}"

        def fmt_pct(v):
            if v is None: return "无数据"
            return f"{v*100:.2f}%" if isinstance(v, float) else str(v)

        income_lines = []
        if fin.get("income_stmt"):
            is_ = fin["income_stmt"]
            income_lines.append(f"  营收 (Revenue): {fmt_currency(is_.get('Total Revenue'))}")
            income_lines.append(f"  毛利润 (Gross Profit): {fmt_currency(is_.get('Gross Profit'))}")
            income_lines.append(f"  净利润 (Net Income): {fmt_currency(is_.get('Net Income'))}")
            income_lines.append(f"  运营利润 (Operating Income): {fmt_currency(is_.get('Operating Income'))}")
            income_lines.append(f"  EPS (Diluted): {is_.get('Diluted EPS', '无数据')}")

        balance_lines = []
        if fin.get("balance_sheet"):
            bs = fin["balance_sheet"]
            balance_lines.append(f"  总资产 (Total Assets): {fmt_currency(bs.get('Total Assets'))}")
            balance_lines.append(f"  总负债 (Total Liabilities): {fmt_currency(bs.get('Total Liabilities'))}")
            balance_lines.append(f"  股东权益 (Total Equity): {fmt_currency(bs.get('Total Equity'))}")
            balance_lines.append(f"  流动资产 (Current Assets): {fmt_currency(bs.get('Current Assets'))}")

        cashflow_lines = []
        if fin.get("cashflow"):
            cf = fin["cashflow"]
            cashflow_lines.append(f"  运营现金流 (Operating Cashflow): {fmt_currency(cf.get('Operating Cash Flow'))}")
            cashflow_lines.append(f"  自由现金流 (Free Cashflow): {fmt_currency(cf.get('Free Cash Flow'))}")
            cashflow_lines.append(f"  资本支出 (Capex): {fmt_currency(cf.get('Capital Expenditure'))}")

        analyst_info = quote_data.get("analyst_targets", {}) if quote_data else {}
        recommendation = quote_data.get("recommendation", "无数据") if quote_data else "无数据"
        target_low = analyst_info.get("target_low", "无数据")
        target_high = analyst_info.get("target_high", "无数据")
        target_mean = analyst_info.get("target_mean", "无数据")
        target_upside = analyst_info.get("target_upside", "无数据")

        # Format news section
        if news:
            news_section = "\n".join(
                f"- [{n['time'][:10]}] {n['title']}（来源: {n['source']}）"
                for n in news
            )
        else:
            news_section = "无数据"

        # Format money flow section
        mf = money_flow
        inst_pct = mf.get("inst_pct", "无数据")
        if inst_pct != "无数据":
            inst_pct = f"{inst_pct:.2f}%"

        inst_lines = []
        for row in mf.get("institutions", [])[:5]:
            inst_lines.append(f"  {row['holder']}: {row['pct']:.2f}% 持股")

        insider_lines = []
        for row in mf.get("insider_transactions", [])[:5]:
            val_str = f"${row['value']/1e6:.2f}百万" if row['value'] else "未披露金额"
            insider_lines.append(f"  {row['date'][:10]} | {row['insider']} | {row['transaction']} | {row['shares']}股 | {val_str}")

        sd = mf.get("short_data", {})
        short_str = f"做空比例: {sd.get('short_percent_float', '无数据')}% | 做空天数: {sd.get('short_ratio', '无数据')}天"

        user_prompt = f"""请分析以下股票数据，生成专业分析报告。

=== 股票基本信息 ===
代码: {symbol}
名称: {name}

=== 今日行情 ===
当前价: ${quote_data.get('price', '无数据') if quote_data else '无数据'}
昨收: ${quote_data.get('previous_close', '无数据') if quote_data else '无数据'}
今开: ${quote_data.get('open', '无数据') if quote_data else '无数据'}
日内高: ${quote_data.get('high', '无数据') if quote_data else '无数据'}
日内低: ${quote_data.get('low', '无数据') if quote_data else '无数据'}
涨跌幅: {quote_data.get('change_pct', '无数据')}% if quote_data else '无数据'
成交量: {quote_data.get('volume', '无数据') if quote_data else '无数据'}
市值: {fmt_currency(quote_data.get('market_cap', 0)) if quote_data and quote_data.get('market_cap') else '无数据'}
市盈率 (Trailing P/E): {quote_data.get('pe_ratio', '无数据') if quote_data else '无数据'}
Forward P/E: {quote_data.get('forward_pe', '无数据') if quote_data else '无数据'}
股息率: {fmt_pct(quote_data.get('dividend_yield', 0)) if quote_data and quote_data.get('dividend_yield') else '无数据'}
营收增长 (YoY): {fmt_pct(quote_data.get('revenue_growth', 0)) if quote_data and quote_data.get('revenue_growth') else '无数据'}
利润率 (Profit Margin): {fmt_pct(quote_data.get('profit_margin', 0)) if quote_data and quote_data.get('profit_margin') else '无数据'}
52周高: ${quote_data.get('fifty_two_week_high', '无数据') if quote_data else '无数据'}
52周低: ${quote_data.get('fifty_two_week_low', '无数据') if quote_data else '无数据'}

=== 资金流向 ===
机构持股比例: {inst_pct}
前三大机构股东:
{chr(10).join(inst_lines) if inst_lines else '无数据'}

近期内部人交易:
{chr(10).join(insider_lines) if insider_lines else '无数据'}

做空数据: {short_str}

=== 新闻舆情 ===
{news_section}

=== 分析师评级 ===
综合评级: {recommendation}
目标价区间: ${target_low} - ${target_high}
目标价均值: ${target_mean}
上涨空间: {fmt_pct(target_upside) if target_upside else '无数据'}

=== 利润表 (近4季度) ===
{chr(10).join(income_lines) if income_lines else '无数据'}

=== 资产负债表 ===
{chr(10).join(balance_lines) if balance_lines else '无数据'}

=== 现金流量表 ===
{chr(10).join(cashflow_lines) if cashflow_lines else '无数据'}

=== 近5日K线 ===
{json.dumps(context['history_5d'], indent=2, ensure_ascii=False, default=str) if context['history_5d'] else '无数据'}

=== 近30日K线 ===
{json.dumps(context['history_30d'], indent=2, ensure_ascii=False, default=str) if context['history_30d'] else '无数据'}"""

        try:
            response = self._llm().messages.create(
                model=get_config().llm.model,
                max_tokens=6000,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text_blocks = [block.text if hasattr(block, "text") else "" for block in response.content]
            report = "\n".join(text_blocks) if text_blocks else ""
            return {
                "ok": True,
                "symbol": symbol,
                "name": name,
                "report": report,
                "data": context,
            }
        except Exception as e:
            return {
                "ok": False,
                "symbol": symbol,
                "name": name,
                "error": str(e),
                "data": context,
            }

    def search(self, query: str) -> dict[str, Any]:
        """Search stocks by symbol or name."""
        query = query.upper()
        results = []
        for symbol, name in POPULAR_STOCKS.items():
            if query in symbol or query.upper() in name.upper():
                results.append({"symbol": symbol, "name": name})
        return {"ok": True, "results": results}

    def get_quote(self, symbol: str) -> dict[str, Any]:
        """Get full quote for a single stock — yfinance first, akshare sina fallback."""
        symbol = symbol.upper()
        name = POPULAR_STOCKS.get(symbol, symbol)

        # Try yfinance first
        data = self._yf_quote(symbol)
        if data:
            return {"ok": True, "data": data}

        # Fallback: akshare stock_us_daily (sina historical — last row is latest close)
        data = self._ak_quote_fallback(symbol)
        if data:
            return {"ok": True, "data": data}

        return {"ok": False, "error": f"Could not fetch data for {symbol}"}

    def _get_financials(self, symbol: str) -> dict[str, Any]:
        """Fetch income_stmt, balance_sheet, cashflow from yfinance."""
        try:
            ticker = yf.Ticker(symbol)
            result = {}
            try:
                income = ticker.income_stmt
                if not income.empty:
                    # Last 4 quarters (columns are quarters, most recent first)
                    cols = list(income.columns[:4])
                    result["income_stmt"] = {
                        str(c): income[col].to_dict() if hasattr(income[col], 'to_dict') else dict(income[col])
                        for col, c in zip(cols, cols)
                    }
                    # Flatten: get most recent quarter as dict
                    if income.shape[1] > 0:
                        latest = income.iloc[:, 0]
                        result["income_stmt"] = {
                            "Total Revenue": float(latest.get("Total Revenue", 0)) if latest.get("Total Revenue") is not None else None,
                            "Gross Profit": float(latest.get("Gross Profit", 0)) if latest.get("Gross Profit") is not None else None,
                            "Operating Income": float(latest.get("Operating Income", 0)) if latest.get("Operating Income") is not None else None,
                            "Net Income": float(latest.get("Net Income", 0)) if latest.get("Net Income") is not None else None,
                            "Diluted EPS": float(latest.get("Diluted EPS", 0)) if latest.get("Diluted EPS") is not None else None,
                        }
            except Exception:
                result["income_stmt"] = None
            try:
                balance = ticker.balance_sheet
                if not balance.empty and balance.shape[1] > 0:
                    latest = balance.iloc[:, 0]
                    result["balance_sheet"] = {
                        "Total Assets": float(latest.get("Total Assets", 0)) if latest.get("Total Assets") is not None else None,
                        "Total Liabilities": float(latest.get("Total Liabilities", 0)) if latest.get("Total Liabilities") is not None else None,
                        "Total Equity": float(latest.get("Total Equity", 0)) if latest.get("Total Equity") is not None else None,
                        "Current Assets": float(latest.get("Current Assets", 0)) if latest.get("Current Assets") is not None else None,
                    }
                else:
                    result["balance_sheet"] = None
            except Exception:
                result["balance_sheet"] = None
            try:
                cashflow = ticker.cashflow
                if not cashflow.empty and cashflow.shape[1] > 0:
                    latest = cashflow.iloc[:, 0]
                    result["cashflow"] = {
                        "Operating Cash Flow": float(latest.get("Operating Cash Flow", 0)) if latest.get("Operating Cash Flow") is not None else None,
                        "Free Cash Flow": float(latest.get("Free Cash Flow", 0)) if latest.get("Free Cash Flow") is not None else None,
                        "Capital Expenditure": float(latest.get("Capital Expenditure", 0)) if latest.get("Capital Expenditure") is not None else None,
                    }
                else:
                    result["cashflow"] = None
            except Exception:
                result["cashflow"] = None
            return result
        except Exception:
            return {"income_stmt": None, "balance_sheet": None, "cashflow": None}

    def _yf_quote(self, symbol: str) -> dict[str, Any] | None:
        """Fetch quote via yfinance. Returns None on failure."""
        try:
            ticker = yf.Ticker(symbol)
            # Use info dict for current price — it has currentPrice/previousClose which
            # fast_info doesn't reliably return after hours. fast_info used for
            # market_cap / exchange / currency (cached, no extra API call).
            info = ticker.info or {}
            hist = ticker.history(period="5d")

            # currentPrice from info (most up-to-date for last close)
            price = info.get("currentPrice") or info.get("regularMarketPrice")
            prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")

            # Fallback to history if info doesn't have price
            if price is None and not hist.empty:
                price = hist["Close"].iloc[-1]
            if prev_close is None and len(hist) > 1:
                prev_close = hist["Close"].iloc[-2]

            if price is None:
                return None

            change = round(price - prev_close, 2) if prev_close else 0
            change_pct = round((change / prev_close) * 100, 2) if prev_close else 0

            # Day range from history
            if not hist.empty:
                day_high = float(hist["High"].max())
                day_low = float(hist["Low"].min())
                volume = int(hist["Volume"].iloc[-1])
            else:
                day_high = day_low = volume = 0

            # 52-week range from info
            fifty_two_high = info.get("fiftyTwoWeekHigh")
            fifty_two_low = info.get("fiftyTwoWeekLow")

            return {
                "symbol": symbol,
                "name": POPULAR_STOCKS.get(symbol, symbol),
                "date": str(date.today()),
                "price": round(float(price), 2),
                "previous_close": round(float(prev_close), 2) if prev_close else None,
                "open": round(float(info.get("open") or hist["Open"].iloc[-1] if not hist.empty else 0), 2),
                "high": round(float(info.get("dayHigh") or info.get("regularMarketDayHigh") or day_high), 2),
                "low": round(float(info.get("dayLow") or info.get("regularMarketDayLow") or day_low), 2),
                "volume": volume,
                "change": change,
                "change_pct": change_pct,
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "dividend_yield": info.get("dividendYield"),
                "revenue_growth": info.get("revenueGrowth"),
                "profit_margin": info.get("profitMargins"),
                "fifty_two_week_high": fifty_two_high,
                "fifty_two_week_low": fifty_two_low,
                "currency": info.get("currency", "USD"),
                "exchange": info.get("exchange", "NMS"),
                "data_source": "yfinance",
                "recommendation": info.get("recommendationKey", "无数据"),
                "analyst_targets": {
                    "target_low": info.get("targetLowPrice", "无数据"),
                    "target_high": info.get("targetHighPrice", "无数据"),
                    "target_mean": info.get("targetMeanPrice", "无数据"),
                    "target_upside": info.get("targetUpside", "无数据"),
                },
            }
        except Exception:
            return None

    def _ak_quote_fallback(self, symbol: str) -> dict[str, Any] | None:
        """Fetch latest quote via akshare stock_us_daily (sina)."""
        try:
            df = ak.stock_us_daily(symbol=symbol, adjust="")
            if df.empty:
                return None
            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else latest
            close = float(latest["close"])
            prev_close = float(prev["close"])
            change = round(close - prev_close, 2)
            change_pct = round((change / prev_close) * 100, 2) if prev_close else 0
            return {
                "symbol": symbol,
                "name": POPULAR_STOCKS.get(symbol, symbol),
                "date": str(latest.name.date()) if hasattr(latest.name, "date") else str(latest.get("date", "")),
                "price": close,
                "previous_close": prev_close,
                "open": round(float(latest.get("open", 0)), 2),
                "high": round(float(latest.get("high", 0)), 2),
                "low": round(float(latest.get("low", 0)), 2),
                "volume": float(latest.get("volume", 0)),
                "change": change,
                "change_pct": change_pct,
                "data_source": "akshare_sina",
            }
        except Exception:
            return None

    def get_historical(self, symbol: str, days: int = 30) -> dict[str, Any]:
        """Get historical daily data — yfinance first, akshare sina fallback."""
        symbol = symbol.upper()
        name = POPULAR_STOCKS.get(symbol, symbol)

        # Try yfinance
        data = self._yf_historical(symbol, days)
        if data:
            return {"ok": True, "symbol": symbol, "name": name, "data": data}

        # Fallback: akshare
        data = self._ak_historical_fallback(symbol, days)
        if data:
            return {"ok": True, "symbol": symbol, "name": name, "data": data}

        return {"ok": False, "error": f"Could not fetch historical data for {symbol}"}

    def _yf_historical(self, symbol: str, days: int) -> list[dict] | None:
        """Fetch historical data via yfinance."""
        try:
            ticker = yf.Ticker(symbol)
            end = date.today()
            start = end - timedelta(days=days + 10)
            df = ticker.history(start=start, end=end, interval="1d")
            if df.empty:
                return None
            df = df.tail(days)
            records = []
            for dt, row in df.iterrows():
                records.append({
                    "date": str(dt.date()),
                    "open": round(float(row["Open"]), 2),
                    "high": round(float(row["High"]), 2),
                    "low": round(float(row["Low"]), 2),
                    "close": round(float(row["Close"]), 2),
                    "volume": int(row["Volume"]),
                })
            return records
        except Exception:
            return None

    def _ak_historical_fallback(self, symbol: str, days: int) -> list[dict] | None:
        """Fetch historical data via akshare stock_us_daily (sina)."""
        try:
            end = date.today()
            start = end - timedelta(days=days + 10)
            df = ak.stock_us_daily(symbol=symbol, adjust="")
            if df.empty:
                return None
            cutoff = pd.Timestamp(start)
            df = df[df.index >= cutoff]
            df = df.tail(days)
            records = []
            for dt, row in df.iterrows():
                records.append({
                    "date": str(dt.date()) if hasattr(dt, "date") else str(dt),
                    "open": round(float(row["open"]), 2),
                    "high": round(float(row["high"]), 2),
                    "low": round(float(row["low"]), 2),
                    "close": round(float(row["close"]), 2),
                    "volume": float(row.get("volume", 0)),
                })
            return records
        except Exception:
            return None

    def get_kline(self, symbol: str, days: int = 30) -> dict[str, Any]:
        """Get kline (OHLCV) data — yfinance first, akshare sina fallback."""
        symbol = symbol.upper()
        name = POPULAR_STOCKS.get(symbol, symbol)

        # Try yfinance
        data = self._yf_kline(symbol, days)
        if data:
            return {"ok": True, "symbol": symbol, "name": name, "data": data}

        # Fallback: akshare
        data = self._ak_kline_fallback(symbol, days)
        if data:
            return {"ok": True, "symbol": symbol, "name": name, "data": data}

        return {"ok": False, "error": f"Could not fetch kline data for {symbol}"}

    def _yf_kline(self, symbol: str, days: int) -> list[dict] | None:
        """Fetch kline data via yfinance."""
        try:
            ticker = yf.Ticker(symbol)
            end = date.today()
            start = end - timedelta(days=days + 10)
            df = ticker.history(start=start, end=end, interval="1d")
            if df.empty:
                return None
            df = df.tail(days)
            records = []
            for dt, row in df.iterrows():
                records.append({
                    "date": str(dt.date()),
                    "open": round(float(row["Open"]), 2),
                    "high": round(float(row["High"]), 2),
                    "low": round(float(row["Low"]), 2),
                    "close": round(float(row["Close"]), 2),
                    "volume": int(row["Volume"]),
                })
            return records
        except Exception:
            return None

    def _ak_kline_fallback(self, symbol: str, days: int) -> list[dict] | None:
        """Fetch kline data via akshare stock_us_daily (sina)."""
        try:
            end = date.today()
            start = end - timedelta(days=days + 10)
            df = ak.stock_us_daily(symbol=symbol, adjust="")
            if df.empty:
                return None
            # date is a column, not the index — filter by date column
            df["date"] = pd.to_datetime(df["date"])
            df = df[df["date"] >= pd.Timestamp(start)]
            df = df.tail(days)
            records = []
            for _, row in df.iterrows():
                records.append({
                    "date": str(row["date"].date()),
                    "open": round(float(row["open"]), 2),
                    "high": round(float(row["high"]), 2),
                    "low": round(float(row["low"]), 2),
                    "close": round(float(row["close"]), 2),
                    "volume": float(row.get("volume", 0)),
                })
            return records
        except Exception:
            return None

    def get_extended_price(self, symbol: str) -> dict[str, Any]:
        """Get pre-market / regular / after-hours prices via yfinance hourly prepost data."""
        symbol = symbol.upper()
        try:
            ticker = yf.Ticker(symbol)
            fi = ticker.fast_info
            pp = fi._get_1wk_1h_prepost_prices()

            if pp is None or pp.empty:
                return {"ok": False, "error": "No extended hours data available"}

            # Find the last trading day in the data
            last_ts = pp.index[-1]
            last_date = last_ts.date()

            today_data = pp[pp.index >= pd.Timestamp(last_date, tz="America/New_York")]

            # Pre-market: before 09:30 ET
            pre_mask = today_data.index.time < pd.Timestamp("09:30").time()
            pre = today_data[pre_mask]
            pre_price = round(float(pre["Close"].iloc[-1]), 2) if len(pre) else None
            pre_time = pre.index[-1].strftime("%H:%M") if len(pre) else None

            # Regular market: 09:30 - 16:00 ET
            reg_mask = (today_data.index.time >= pd.Timestamp("09:30").time()) & (
                today_data.index.time <= pd.Timestamp("16:00").time()
            )
            reg = today_data[reg_mask]
            reg_price = round(float(reg["Close"].iloc[-1]), 2) if len(reg) else None
            reg_time = reg.index[-1].strftime("%H:%M") if len(reg) else None

            # After-hours: 16:00 onwards
            after_mask = today_data.index.time >= pd.Timestamp("16:00").time()
            after = today_data[after_mask]
            after_price = round(float(after["Close"].iloc[-1]), 2) if len(after) else None
            after_time = after.index[-1].strftime("%H:%M") if len(after) else None

            info = ticker.info or {}
            prev = info.get("regularMarketPreviousClose") or info.get("previousClose")

            return {
                "ok": True,
                "symbol": symbol,
                "name": POPULAR_STOCKS.get(symbol, symbol),
                "date": str(last_date),
                "pre_market": {"price": pre_price, "time": pre_time},
                "regular": {"price": reg_price, "time": reg_time},
                "after_hours": {"price": after_price, "time": after_time},
                "previous_close": prev,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
