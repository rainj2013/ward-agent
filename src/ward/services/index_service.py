"""Index analysis service — AI-powered market analysis for US indices."""

from __future__ import annotations

import json
import time
from datetime import date, timedelta
from typing import Any

import akshare as ak
import pandas as pd
import yfinance as yf
from anthropic import Anthropic

from ward.core.config import get_config
from ward.services.db.analysis_cache_service import AnalysisCacheService

# Supported indices: (yfinance_symbol, display_name, description)
SUPPORTED_INDICES = {
    "^GSPC": ("S&P 500", "标普500指数", "美国主板市场整体表现"),
    "^IXIC": ("Nasdaq Composite", "纳斯达克综合指数", "美国科技股和成长股风向标"),
    "^NDX": ("Nasdaq 100", "纳斯达克100指数", "美国科技龙头股指数"),
    "^DJI": ("Dow Jones", "道琼斯工业指数", "美国传统蓝筹股指数"),
    "GC=F": ("Gold", "黄金期货", "全球避险资产和通胀对冲工具"),
}


class IndexService:
    """Generate AI-powered index analysis reports."""

    SYSTEM_PROMPT = """你是一个专业的宏观策略分析师，擅长分析美国股市整体走势和技术面状态。
根据提供的指数数据、恐惧贪婪指标和技术指标，生成结构化市场分析报告。

**输出格式要求（严格按此结构输出，每节必须有实质内容）：**

## 一、今日市场概览
|| 指数 | 收盘点位 | 涨跌幅 | 日内高点 | 日内低点 |
||------|--------|--------|--------|--------|
| S&P 500 | XX,XXX | ±X.XX% | XX,XXX | XX,XXX |
| Nasdaq 综合 | XX,XXX | ±X.XX% | XX,XXX | XX,XXX |
| Nasdaq 100 | XX,XXX | ±X.XX% | XX,XXX | XX,XXX |
| Dow Jones | XX,XXX | ±X.XX% | XX,XXX | XX,XXX |

[用2-3句话总结今日整体市场环境]

## 二、恐惧与贪婪（VIX）
- **VIX 当前值**：XX.XX
- **情绪解读**：极度恐慌 / 恐慌 / 中性 / 贪婪 / 极度贪婪（基于VIX数值）
- **历史参考**：VIX 历史均值约 18-20

[解读VIX透露的市场情绪，注意VIX和股价通常反向]

## 三、指数技术面分析
### S&P 500
- **当前点位**：XX,XXX（相比MA20: 突破/跌破/粘合）
- **均线判断**：MA5 / MA20 / MA60（多头排列 / 空头排列 / 粘合）
- **趋势判断**：短期（5日）/ 中期（20日）趋势
- **关键价位**：重要支撑 $XXX，重要压力 $XXX
- **RSI（14）**：XX（超买>70 / 超卖<30 / 中性）
- **MACD**：金叉 / 死叉 / 盘整（能量柱方向）
- **布林带**：价格位置（上轨/中轨/下轨）

### Nasdaq 综合
[同上格式]

### Nasdaq 100
[同上格式]

### Dow Jones
[同上格式]

## 四、市场宽度分析
- **涨跌家数比**：上涨/下跌股票比例（如有数据）
- **指数与成交量**：放量突破 / 缩量上涨 / 放量下跌等判断

## 五、市场新闻与主题
### 近期宏观新闻标题
{news_section}

### 市场主题总结
[根据新闻，总结当前市场最关注的3个核心主题，用中文回答]

## 六、综合市场判断
- **当前市场状态**：强势上涨 / 震荡整理 / 弱势下跌 / 反弹修复
- **操作建议**：积极做多 / 逢低布局 / 谨慎观望 / 控制仓位
- **风险提示**：当前市场主要风险点1-2条

---
注意：所有数据必须来自提供的市场数据，不要编造数字。报告用中文撰写，突出重点，不要废话。"""

    def __init__(self):
        cfg = get_config()
        self._client = Anthropic(api_key=cfg.llm.api_key, base_url=cfg.llm.base_url)
        self._cache = AnalysisCacheService()

    def _calc_rsi(self, prices: pd.Series, period: int = 14) -> float | None:
        """Calculate RSI."""
        if len(prices) < period + 1:
            return None
        delta = prices.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
        avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return round(float(rsi.iloc[-1]), 2)

    def _calc_macd(
        self, prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
    ) -> dict[str, Any]:
        """Calculate MACD."""
        if len(prices) < slow + signal:
            return {"macd": None, "signal": None, "histogram": None, "cross": None}
        ema_fast = prices.ewm(span=fast, adjust=False).mean()
        ema_slow = prices.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        macd_val = round(float(macd_line.iloc[-1]), 4)
        signal_val = round(float(signal_line.iloc[-1]), 4)
        hist_val = round(float(histogram.iloc[-1]), 4)
        # Cross: 1=gold cross, -1=dead cross, 0=none
        if len(histogram) >= 2:
            cross = 1 if histogram.iloc[-2] < 0 and histogram.iloc[-1] > 0 else (-1 if histogram.iloc[-2] > 0 and histogram.iloc[-1] < 0 else 0)
        else:
            cross = 0
        return {"macd": macd_val, "signal": signal_val, "histogram": hist_val, "cross": cross}

    def _calc_bollinger(
        self, prices: pd.Series, period: int = 20, std_dev: float = 2.0
    ) -> dict[str, float]:
        """Calculate Bollinger Bands."""
        if len(prices) < period:
            return {"upper": None, "middle": None, "lower": None, "position": None}
        sma = prices.rolling(period).mean()
        std = prices.rolling(period).std()
        upper = sma + std_dev * std
        lower = sma - std_dev * std
        current = float(prices.iloc[-1])
        mid = float(sma.iloc[-1])
        up = float(upper.iloc[-1])
        low = float(lower.iloc[-1])
        # Position: 0=lower band, 1=upper band
        if up == low:
            position = 0.5
        else:
            position = round((current - low) / (up - low), 3)
        return {
            "upper": round(up, 2),
            "middle": round(mid, 2),
            "lower": round(low, 2),
            "position": position,
        }

    def _get_quote(self, symbol: str) -> dict[str, Any]:
        """Get current quote via yfinance."""
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.fast_info
            hist = ticker.history(period="5d")
            if hist.empty:
                return {"error": "no history data"}
            price = info.get("price") or float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else price
            change = round(price - prev, 2)
            change_pct = round((change / prev) * 100, 2) if prev else 0
            return {
                "price": round(float(price), 2),
                "change": change,
                "change_pct": change_pct,
                "open": round(float(hist["Open"].iloc[-1]), 2),
                "high": round(float(hist["High"].max()), 2),
                "low": round(float(hist["Low"].min()), 2),
                "volume": int(hist["Volume"].iloc[-1]),
            }
        except Exception as e:
            return {"error": str(e)}

    def _get_historical(self, symbol: str, days: int = 60) -> pd.DataFrame | None:
        """Get historical data as DataFrame."""
        try:
            end = date.today()
            start = end - timedelta(days=days + 10)
            ticker = yf.Ticker(symbol)
            df = ticker.history(start=start, end=end, interval="1d")
            if df.empty:
                return None
            return df.tail(days)
        except Exception:
            return None

    def _get_tech_indicators(self, df: pd.DataFrame) -> dict[str, Any]:
        """Calculate all technical indicators from price DataFrame."""
        close = df["Close"]
        if len(close) < 5:
            return {}
        # Moving averages
        ma5 = round(float(close.tail(5).mean()), 2)
        ma20 = round(float(close.tail(20).mean()), 2) if len(close) >= 20 else None
        ma60 = round(float(close.tail(60).mean()), 2) if len(close) >= 60 else None
        current = float(close.iloc[-1])
        # Trend
        if ma5 and ma20:
            if current > ma5 > ma20:
                trend = "多头排列"
            elif current < ma5 < ma20:
                trend = "空头排列"
            else:
                trend = "震荡整理"
        else:
            trend = "数据不足"
        return {
            "current": current,
            "ma5": ma5,
            "ma20": ma20,
            "ma60": ma60,
            "trend": trend,
            "rsi": self._calc_rsi(close),
            "macd": self._calc_macd(close),
            "bollinger": self._calc_bollinger(close),
        }

    def _fetch_news(self, limit: int = 10) -> list[dict]:
        """Fetch macro market news via akshare eastmoney."""
        try:
            df = ak.stock_news_main_cx()
            if df is None or df.empty:
                return []
            rows = []
            for _, row in df.head(limit).iterrows():
                rows.append({
                    "title": str(row.get("summary", ""))[:100],
                    "tag": str(row.get("tag", "")),
                })
            return rows
        except Exception:
            return []

    def _get_vix(self) -> dict[str, Any]:
        """Get VIX data."""
        try:
            ticker = yf.Ticker("^VIX")
            info = ticker.fast_info
            hist = ticker.history(period="5d")
            if hist.empty:
                return {"price": None, "error": "no data"}
            price = info.get("price") or float(hist["Close"].iloc[-1])
            return {"price": round(float(price), 2)}
        except Exception as e:
            return {"price": None, "error": str(e)}

    def _get_dxy(self) -> dict[str, Any]:
        """Get US Dollar Index (DXY) data."""
        try:
            ticker = yf.Ticker("^DXY")
            hist = ticker.history(period="5d")
            if hist.empty or len(hist) < 2:
                return {"price": None, "error": "no data"}
            price = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2])
            change = round(price - prev, 2)
            change_pct = round((change / prev) * 100, 2) if prev else 0
            return {"price": round(price, 2), "change": change, "change_pct": change_pct}
        except Exception as e:
            return {"price": None, "error": str(e)}

    def _get_gld_etf(self) -> dict[str, Any]:
        """Get SPDR Gold Shares ETF (GLD) data."""
        try:
            ticker = yf.Ticker("GLD")
            hist = ticker.history(period="5d")
            if hist.empty or len(hist) < 2:
                return {"price": None, "error": "no data"}
            price = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2])
            change = round(price - prev, 2)
            change_pct = round((change / prev) * 100, 2) if prev else 0
            return {"price": round(price, 2), "change": change, "change_pct": change_pct}
        except Exception as e:
            return {"price": None, "error": str(e)}

    def _get_sp500_quote(self) -> dict[str, Any]:
        """Get S&P 500 quote for GP ratio calculation."""
        try:
            ticker = yf.Ticker("^GSPC")
            hist = ticker.history(period="5d")
            if hist.empty:
                return {"price": None}
            return {"price": round(float(hist["Close"].iloc[-1]), 2)}
        except Exception:
            return {"price": None}

    # Map prefix -> (yfinance_symbol, display_name, chn_name)
    PREFIX_MAP = {
        "ixic": ("^IXIC", "Nasdaq Composite", "纳斯达克综合指数"),
        "spx":  ("^GSPC", "S&P 500",           "标普500指数"),
        "dji":  ("^DJI", "Dow Jones",          "道琼斯工业指数"),
        "gold": ("GC=F", "Gold",               "黄金期货"),
    }

    GOLD_SYSTEM_PROMPT = """你是一个专业的贵金属分析师，擅长分析黄金、白银等贵金属的价格走势和驱动因素。
根据提供的黄金期货数据、技术指标和宏观经济背景，生成专业的黄金市场分析报告。

**输出格式要求（严格按此结构输出，每节必须有实质内容）：**

## 一、黄金今日行情
| 项目 | 数值 |
|------|------|
| 收盘价 | $X,XXX |
| 涨跌幅 | ±X.XX% |
| 日内高点 | $X,XXX |
| 日内低点 | $X,XXX |
| 成交量 | XXX,XXX 手 |

[用2-3句话总结今日黄金走势]

## 二、宏观经济背景
- **美元指数 (DXY)**：影响黄金的的核心因素，美元强弱与黄金反向
- **实际利率**：实际利率 = 名义利率 - 通胀预期，实际利率走低对黄金利好
- **地缘政治风险**：当前主要风险事件（如有）
- **央行购金动态**：各国央行黄金储备变化趋势

## 三、技术面分析
- **当前价格**：$X,XXX（相比 MA20: 突破/跌破/粘合）
- **均线系统**：MA5 / MA20 / MA60（多头排列 / 空头排列 / 震荡）
- **趋势判断**：短期 / 中期趋势
- **关键支撑位**：$X,XXX
- **关键阻力位**：$X,XXX
- **RSI（14）**：XX（超买>70 / 超卖<30 / 中性）
- **MACD**：金叉 / 死叉 / 盘整（能量柱方向）
- **布林带**：价格位置（上轨/中轨/下轨）

## 四、黄金专属指标
- **黄金与标普500比值（GP）**：判断股金跷跷板效应
- **黄金仓位变化**：投机多头 vs 套保空头持仓变化
- **黄金ETF持仓（SPDR GLD）**：全球最大黄金ETF持仓量变化

## 五、综合判断与操作建议
- **当前市场状态**：强势上涨 / 震荡整理 / 弱势下跌
- **核心驱动因素**：当前黄金最主要的1-2个驱动逻辑
- **操作建议**：逢低买入 / 逢高减仓 / 区间操作 / 观望
- **风险提示**：当前主要风险

---
注意：所有数据必须来自提供的市场数据，不要编造数字。报告用中文撰写，突出重点，不要废话。"""

    def generate_analysis(self, prefix: str) -> dict[str, Any]:
        """Generate AI analysis for a single index (or gold), with raw 60-day K-line data."""
        cache_key = f"index:{prefix}"
        cached = self._cache.get(cache_key)
        if cached:
            # Look up by PREFIX_MAP first (has all prefixes), then by yfinance symbol
            mapping = self.PREFIX_MAP.get(prefix)
            if mapping:
                chn_name = mapping[2]
            else:
                chn_name = next(
                    (v[2] for k, v in SUPPORTED_INDICES.items() if prefix.upper().replace("^", "").replace("=", "") == k.upper().replace("^", "").replace("=", "")),
                    prefix
                )
            return {"ok": True, "prefix": prefix, "name": chn_name, "report": cached["report"], "data": cached["data"], "cached": True}

        # ── Gold branch ────────────────────────────────────────────────
        if prefix == "gold":
            return self._generate_gold_analysis(cache_key)

        # ── Regular index branch ────────────────────────────────────────
        mapping = self.PREFIX_MAP.get(prefix)
        if not mapping:
            return {"ok": False, "error": f"Unknown index prefix: {prefix}"}

        yf_sym, eng_name, chn_name = mapping

        # 1. Quote
        quote = self._get_quote(yf_sym)
        time.sleep(0.1)

        # 2. Raw 60-day K-line (OHLCV)
        df = self._get_historical(yf_sym, 60)
        klines = []
        if df is not None and not df.empty:
            for dt, row in df.iterrows():
                klines.append({
                    "date":   dt.strftime("%Y-%m-%d"),
                    "open":   round(float(row["Open"]), 2),
                    "high":   round(float(row["High"]), 2),
                    "low":    round(float(row["Low"]), 2),
                    "close":  round(float(row["Close"]), 2),
                    "volume": int(row["Volume"]),
                })

        # 3. Technical indicators
        tech = self._get_tech_indicators(df) if df is not None else {}

        # 4. VIX
        vix = self._get_vix()

        # 5. News
        news = self._fetch_news(limit=8)

        context = {
            "prefix": prefix,
            "yf_symbol": yf_sym,
            "name": chn_name,
            "quote": quote,
            "klines": klines,
            "tech": tech,
            "vix": vix,
            "news": news,
        }

        # Format VIX sentiment
        vix_price = vix.get("price")
        if vix_price:
            if vix_price < 15:    vix_sentiment = "极度贪婪"
            elif vix_price < 20:  vix_sentiment = "中性偏乐观"
            elif vix_price < 30:  vix_sentiment = "恐慌"
            else:                  vix_sentiment = "极度恐慌"
        else:
            vix_sentiment = "无数据"

        # Format K-line table
        if klines:
            kline_table = "\n".join(
                f"| {k['date']} | {k['open']:.2f} | {k['high']:.2f} | "
                f"{k['low']:.2f} | {k['close']:.2f} | {k['volume']:,} |"
                for k in klines
            )
            kline_md = f"| 日期 | 开盘 | 最高 | 最低 | 收盘 | 成交量 |\n|-----------|------|------|------|------|----------|\n{kline_table}"
        else:
            kline_md = "无数据"

        # Format technical summary
        macd = tech.get("macd", {})
        bb   = tech.get("bollinger", {})
        macd_cross = {1: "金叉", -1: "死叉", 0: "中性"}.get(macd.get("cross", 0), "无数据")
        tech_md = (
            f"- **当前点位**: {tech.get('current', '无数据')}\n"
            f"- **均线**: MA5={tech.get('ma5')}, MA20={tech.get('ma20')}, MA60={tech.get('ma60')}\n"
            f"- **趋势**: {tech.get('trend', '无数据')}\n"
            f"- **RSI(14)**: {tech.get('rsi', '无数据')}\n"
            f"- **MACD**: {macd_cross} (MACD={macd.get('macd')}, Signal={macd.get('signal')})\n"
            f"- **布林带**: 上轨={bb.get('upper')}, 中轨={bb.get('middle')}, 下轨={bb.get('lower')}, 位置={bb.get('position')}"
        )

        # News
        news_md = "\n".join(f"- [{n.get('tag','?')}] {n.get('title','')}" for n in news) if news else "无数据"

        user_prompt = f"""分析以下美国指数数据，生成结构化分析报告。

=== {chn_name} 今日行情 ===
- 现价: {quote.get('price', '无数据')}
- 涨跌幅: {quote.get('change_pct', '?')}%
- 今日开盘: {quote.get('open', '?')} | 最高: {quote.get('high', '?')} | 最低: {quote.get('low', '?')}
- 成交量: {quote.get('volume', '无数据'):,}

=== VIX 恐惧贪婪指标 ===
- 当前值: {vix_price if vix_price else '无数据'}
- 情绪: {vix_sentiment}

=== {chn_name} 过去60个交易日K线 ===
{kline_md}

=== {chn_name} 技术指标 ===
{tech_md}

=== 市场新闻 ===
{news_md}

请生成专业分析报告，包含：今日行情总结、技术面深度分析、当前市场状态判断、操作建议。
所有数据必须来自上面提供的数据，不要编造。报告用中文，突出重点。"""

        text = ""
        try:
            response = self._client.messages.create(
                model=get_config().llm.model,
                max_tokens=6000,
                system="你是一个专业的宏观策略分析师，擅长分析美国股市技术面和宏观走势。",
                messages=[{"role": "user", "content": user_prompt}],
            )
            text = "\n".join(
                block.text if hasattr(block, "text") else ""
                for block in response.content
            )
            return {
                "ok": True,
                "prefix": prefix,
                "name": chn_name,
                "report": text,
                "data": context,
            }
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "data": context,
            }
        finally:
            if text:
                self._cache.set(cache_key, text, context)

    # ── Gold-specific analysis ────────────────────────────────────────────────

    def _generate_gold_analysis(self, cache_key: str) -> dict[str, Any]:
        """Generate AI analysis for gold futures."""
        yf_sym = "GC=F"
        chn_name = "黄金期货"

        # 1. Gold quote
        quote = self._get_quote(yf_sym)
        time.sleep(0.1)

        # 2. 60-day K-line
        df = self._get_historical(yf_sym, 60)
        klines = []
        if df is not None and not df.empty:
            for dt, row in df.iterrows():
                klines.append({
                    "date":   dt.strftime("%Y-%m-%d"),
                    "open":   round(float(row["Open"]), 2),
                    "high":   round(float(row["High"]), 2),
                    "low":    round(float(row["Low"]), 2),
                    "close":  round(float(row["Close"]), 2),
                    "volume": int(row["Volume"]),
                })

        # 3. Technical indicators
        tech = self._get_tech_indicators(df) if df is not None else {}

        # 4. DXY (dollar index)
        dxy = self._get_dxy()
        time.sleep(0.1)

        # 5. GLD ETF
        gld = self._get_gld_etf()
        time.sleep(0.1)

        # 6. S&P 500 for GP ratio
        spx = self._get_sp500_quote()

        # 7. VIX
        vix = self._get_vix()

        context = {
            "prefix": "gold",
            "yf_symbol": yf_sym,
            "name": chn_name,
            "quote": quote,
            "klines": klines,
            "tech": tech,
            "dxy": dxy,
            "gld_etf": gld,
            "sp500": spx,
            "vix": vix,
        }

        # Calculate Gold/S&P 500 ratio
        gold_price = quote.get("price")
        spx_price = spx.get("price")
        if gold_price and spx_price:
            gp_ratio = round(gold_price / spx_price, 4)
        else:
            gp_ratio = None

        # Format K-line table
        if klines:
            kline_table = "\n".join(
                f"| {k['date']} | {k['open']:.2f} | {k['high']:.2f} | "
                f"{k['low']:.2f} | {k['close']:.2f} | {k['volume']:,} |"
                for k in klines
            )
            kline_md = f"| 日期 | 开盘 | 最高 | 最低 | 收盘 | 成交量 |\n|-----------|------|------|------|------|----------|\n{kline_table}"
        else:
            kline_md = "无数据"

        macd = tech.get("macd", {})
        bb   = tech.get("bollinger", {})
        macd_cross = {1: "金叉", -1: "死叉", 0: "中性"}.get(macd.get("cross", 0), "无数据")
        tech_md = (
            f"- **当前价格**: ${tech.get('current', '无数据')}\n"
            f"- **均线**: MA5={tech.get('ma5')}, MA20={tech.get('ma20')}, MA60={tech.get('ma60')}\n"
            f"- **趋势**: {tech.get('trend', '无数据')}\n"
            f"- **RSI(14)**: {tech.get('rsi', '无数据')}\n"
            f"- **MACD**: {macd_cross} (MACD={macd.get('macd')}, Signal={macd.get('signal')})\n"
            f"- **布林带**: 上轨=${bb.get('upper')}, 中轨=${bb.get('middle')}, 下轨=${bb.get('lower')}, 位置={bb.get('position')}"
        )

        # Key support/resistance from bollinger + recent extremes
        if df is not None and not df.empty:
            recent_low = round(float(df["Low"].tail(20).min()), 2)
            recent_high = round(float(df["High"].tail(20).max()), 2)
        else:
            recent_low = recent_high = None

        user_prompt = f"""分析以下黄金期货数据，生成专业的贵金属市场分析报告。

=== 黄金今日行情 ===
- 现货价（GC=F）: ${quote.get('price', '无数据')}
- 涨跌幅: {quote.get('change_pct', '?')}%
- 今日开盘: ${quote.get('open', '?')} | 最高: ${quote.get('high', '?')} | 最低: ${quote.get('low', '?')}
- 成交量: {quote.get('volume', '无数据'):,} 手

=== 关联市场数据 ===
- **美元指数 (DXY)**: {dxy.get('price', '无数据')}（涨跌: {dxy.get('change_pct', '无数据')}%）
- **SPDR黄金ETF (GLD)**: ${gld.get('price', '无数据')}（涨跌: {gld.get('change_pct', '无数据')}%）
- **标普500**: {spx.get('price', '无数据')}
- **黄金/标普500比值**: {gp_ratio if gp_ratio else '无数据'}
- **VIX恐慌指数**: {vix.get('price', '无数据')}

=== 黄金过去60个交易日K线 ===
{kline_md}

=== 黄金技术指标 ===
{tech_md}

=== 关键价位参考 ===
- 近期支撑: ${recent_low if recent_low else '无数据'}
- 近期阻力: ${recent_high if recent_high else '无数据'}

请生成专业黄金分析报告，包含：今日行情总结、宏观背景（美元/利率/通胀）、技术面深度分析、关键价位、操作建议。
所有数据必须来自上面提供的数据，不要编造。报告用中文，突出重点。"""

        text = ""
        try:
            response = self._client.messages.create(
                model=get_config().llm.model,
                max_tokens=6000,
                system=self.GOLD_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text = "\n".join(
                block.text if hasattr(block, "text") else ""
                for block in response.content
            )
            return {
                "ok": True,
                "prefix": "gold",
                "name": chn_name,
                "report": text,
                "data": context,
            }
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "data": context,
            }
        finally:
            if text:
                self._cache.set(cache_key, text, context)
