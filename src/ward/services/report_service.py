"""LLM-powered report generation service — market report + sentiment analysis."""

from __future__ import annotations

import json
import re
import time
from time import perf_counter
from typing import Any

import yfinance as yf
from anthropic import Anthropic

from ward.core.config import get_config
from ward.core.llm import complete_text, create_anthropic_client, stream_text
from ward.services.db.analysis_cache_service import AnalysisCacheService
from ward.services.nasdaq_service import MarketService


def _zero_usage() -> dict[str, Any]:
    return {
        "provider": "anthropic-compatible",
        "model": get_config().llm.model,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }


def _sum_usage(*items: dict[str, Any] | None) -> dict[str, Any]:
    usage = _zero_usage()
    for item in items:
        if not item:
            continue
        usage["input_tokens"] += int(item.get("input_tokens", 0) or 0)
        usage["output_tokens"] += int(item.get("output_tokens", 0) or 0)
        usage["total_tokens"] += int(item.get("total_tokens", 0) or 0)
    return usage


class ReportService:
    """Generate market analysis reports and sentiment via LLM."""

    SYSTEM_PROMPT = """你是一个专业的金融分析师，专注于美国科技股和纳斯达克市场。
根据提供的市场数据，生成结构化分析报告。

**输出格式要求（严格按此结构输出，每节必须有内容）：**

## 一、今日行情概述
[用2-3句话描述今日整体市场环境，涵盖主要指数涨跌幅和市场氛围]

## 二、主要指数表现
| 指数 | 涨跌幅 | 当前点位 |
|------|--------|----------|
| Nasdaq Composite | +X.XX% | XX,XXX |
| Nasdaq 100 | +X.XX% | XX,XXX |
| S&P 500 | +X.XX% | X,XXX |
| Dow Jones | +X.XX% | XX,XXX |

[若无某指数数据则标注"无数据"，不要留空]

## 三、技术面分析
- **均线位置**：当前价格与 MA5/MA20/MA60 的关系（突破/跌破/粘合）
- **短期趋势**：5日内走势判断（上涨/下跌/震荡）
- **关键价位**：重要支撑位和压力位（基于近期高低点）
- **成交量**：今日量能对比近期平均（放量/缩量）

## 四、市场情绪判断
- **情绪评分**：X/9（1=极度恐慌，9=极度乐观）
- **情绪解读**：[基于新闻标题和评分给出简明判断]
- **核心议题**：列出市场最关注的3个主题

## 五、重大新闻事件
[列出3-5条影响市场的重大新闻，每条格式：- [股票代码] 新闻标题（影响：正面/负面/中性）]

## 六、投资思考
[给出2-3条简短的市场观察和思考，用数据支撑，不要预测具体点位]

---
注意：所有数据必须来自提供的市场数据，不要编造数字。报告用中文撰写。"""

    SENTIMENT_PROMPT = """你是一个市场情绪分析师，擅长从新闻标题判断市场情绪。
我会给你一组今日/近期的美股相关新闻标题，请分析：
1. 每条新闻对市场的影响（正面/负面/中性）
2. 综合情绪评分（1=极度恐慌，5=中性，9=极度乐观）
3. 市场关注的核心议题（最多3个）

新闻标题：
{news_titles}

请用中文回复，格式：
情绪评分：X/9
情绪解读：...
核心议题：1. ... 2. ... 3. ..."""

    def __init__(self):
        self.config = get_config()
        self.ns = MarketService()
        self._client: Anthropic | None = None
        self._cache = AnalysisCacheService()

    @property
    def client(self) -> Anthropic:
        if self._client is None:
            self._client = create_anthropic_client()
        return self._client

    def _fetch_news(self, symbols: list[str] = None, limit: int = 8) -> list[dict]:
        """Fetch recent market news via yfinance."""
        if symbols is None:
            symbols = ["QQQ", "NVDA", "MSFT", "AAPL"]
        all_news = []
        seen_titles = set()
        for sym in symbols:
            try:
                ticker = yf.Ticker(sym)
                news = ticker.news
                if news:
                    for item in news[:3]:
                        title = item.get("content", {}).get("title", "")
                        if title and title not in seen_titles:
                            seen_titles.add(title)
                            all_news.append({
                                "symbol": sym,
                                "title": title,
                                "time": item.get("content", {}).get("pubDate", ""),
                            })
            except Exception:
                pass
            time.sleep(0.3)
        # Sort by time, most recent first
        all_news.sort(key=lambda x: x.get("time", ""), reverse=True)
        return all_news[:limit]

    def _analyze_sentiment(self, news_items: list[dict], trace=None) -> dict[str, Any]:
        """Use LLM to analyze market sentiment from news titles."""
        if not news_items:
            if trace:
                trace("stage_end", "没有可用新闻，跳过情绪分析", "sentiment_analysis", {"news_count": 0})
            return {"score": None, "interpretation": "无新闻数据", "topics": [], "raw": "", "usage": _zero_usage()}

        titles = "\n".join(f"- [{item['symbol']}] {item['title']}" for item in news_items)
        prompt = self.SENTIMENT_PROMPT.format(news_titles=titles)

        try:
            llm_started = perf_counter()
            if trace:
                trace(
                    "llm_call_start",
                    "正在等待模型生成市场情绪分析",
                    "sentiment_analysis",
                    {
                        "model": self.config.llm.model,
                        "max_tokens": 3000,
                        "system": "你是一个客观理性的金融市场情绪分析师。",
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
            text, usage = complete_text(
                self.client,
                system="你是一个客观理性的金融市场情绪分析师。",
                prompt=prompt,
                max_tokens=3000,
            )
            # Parse score from response (handles both int like "5/9" and float like "4.5/9")
            score = None
            for line in text.split("\n"):
                if "评分" in line and "/" in line:
                    m = re.search(r'([0-9.]+)\s*/\s*9', line)
                    if m:
                        score = float(m.group(1))
            if trace:
                trace(
                    "llm_call_end",
                    "市场情绪分析完成",
                    "sentiment_analysis",
                    {"usage": usage, "response_text": text},
                    int((perf_counter() - llm_started) * 1000),
                )
            return {
                "score": score,
                "interpretation": text,
                "topics": [],
                "raw": text,
                "news_count": len(news_items),
                "usage": usage,
            }
        except Exception as e:
            if trace:
                trace("llm_call_error", "市场情绪分析失败", "sentiment_analysis", {"error": str(e)})
            return {"score": None, "interpretation": f"情绪分析失败: {e}", "topics": [], "raw": "", "usage": _zero_usage()}

    def generate_market_report(self, trace=None) -> dict[str, Any]:
        """Generate today's Nasdaq market report with news + sentiment."""
        cache_key = f"market:report:model:{get_config().llm.model}"
        cached = self._cache.get(cache_key)
        if cached:
            if trace:
                trace("cache_hit", "命中缓存，已复用现有市场报告", "cache_hit", {"cache_key": cache_key})
            return {"ok": True, "report": cached["report"], "data": cached["data"], "cached": True}
        if trace:
            trace("cache_miss", "缓存未命中，准备获取市场数据和新闻", "fetching_data", {"cache_key": cache_key})

        # 1. Market data
        fetch_started = perf_counter()
        overview = self.ns.get_market_overview()

        # 2. Fetch news
        news = self._fetch_news()
        if trace:
            trace(
                "stage_end",
                "市场指数和新闻获取完成",
                "fetching_data",
                {"overview_ok": overview.get("ok", False), "news_count": len(news)},
                int((perf_counter() - fetch_started) * 1000),
            )

        # 3. Sentiment analysis
        sentiment = self._analyze_sentiment(news, trace=trace)

        # 4. Build data summary for LLM
        context = {
            "market_overview": overview,
            "recent_news": [{"symbol": n["symbol"], "title": n["title"], "time": n["time"]} for n in news],
            "sentiment": sentiment,
        }

        news_section = "\n".join(
            f"- [{n['symbol']}] {n['title']}" for n in news
        ) if news else "（无可用新闻）"

        user_prompt = f"""请分析以下今日纳斯达克市场数据：

=== 市场指数 ===
{json.dumps(overview, indent=2, ensure_ascii=False, default=str)}

=== 近期新闻标题 ===
{news_section}

=== AI 情绪分析结果 ===
{sentiment.get('interpretation', '')}

请给出今日市场的综合分析报告，包括：
1. 今日行情概述
2. 关键技术指标
3. 市场情绪判断（结合新闻和情绪评分）
4. 关键新闻事件摘要
5. 简短的投资思考"""

        try:
            llm_started = perf_counter()
            if trace:
                trace(
                    "llm_call_start",
                    "正在等待模型生成市场分析报告",
                    "llm_generating",
                    {
                        "model": self.config.llm.model,
                        "max_tokens": 5000,
                        "system": self.SYSTEM_PROMPT,
                        "messages": [{"role": "user", "content": user_prompt}],
                    },
                )
            text, report_usage = complete_text(
                self.client, system=self.SYSTEM_PROMPT, prompt=user_prompt, max_tokens=5000
            )
            usage = _sum_usage(sentiment.get("usage"), report_usage)
            if trace:
                trace(
                    "llm_call_end",
                    "市场分析报告生成完成",
                    "llm_generating",
                    {"usage": report_usage, "response_text": text},
                    int((perf_counter() - llm_started) * 1000),
                )
            return {
                "ok": True,
                "report": text,
                "data": context,
                "usage": usage,
            }
        except Exception as e:
            if trace:
                trace("llm_call_error", "市场分析报告生成失败", "llm_generating", {"error": str(e)})
            return {
                "ok": False,
                "error": str(e),
                "data": context,
            }
        finally:
            if "text" in dir() and text:
                self._cache.set(cache_key, text, context)

    def generate_market_report_stream(self):
        """Stream today's Nasdaq market report from the LLM."""
        cache_key = f"market:report:model:{get_config().llm.model}"
        cached = self._cache.get(cache_key)
        if cached:
            yield {"ok": True, "chunk": cached["report"], "cached": True}
            yield {"ok": True, "done": True, "report": cached["report"], "data": cached["data"], "cached": True}
            return

        overview = self.ns.get_market_overview()
        news = self._fetch_news()
        sentiment = self._analyze_sentiment(news)

        context = {
            "market_overview": overview,
            "recent_news": [{"symbol": n["symbol"], "title": n["title"], "time": n["time"]} for n in news],
            "sentiment": sentiment,
        }

        news_section = "\n".join(
            f"- [{n['symbol']}] {n['title']}" for n in news
        ) if news else "（无可用新闻）"

        user_prompt = f"""请分析以下今日纳斯达克市场数据：

=== 市场指数 ===
{json.dumps(overview, indent=2, ensure_ascii=False, default=str)}

=== 近期新闻标题 ===
{news_section}

=== AI 情绪分析结果 ===
{sentiment.get('interpretation', '')}

请给出今日市场的综合分析报告，包括：
1. 今日行情概述
2. 关键技术指标
3. 市场情绪判断（结合新闻和情绪评分）
4. 关键新闻事件摘要
5. 简短的投资思考"""

        text = ""
        try:
            for chunk in stream_text(
                self.client, system=self.SYSTEM_PROMPT, prompt=user_prompt, max_tokens=5000
            ):
                text += chunk
                yield {"ok": True, "chunk": chunk}
            yield {"ok": True, "done": True, "report": text, "data": context}
        except Exception as e:
            yield {"ok": False, "error": str(e), "done": True, "data": context}
        finally:
            if text:
                self._cache.set(cache_key, text, context)
