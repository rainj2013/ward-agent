"""LLM-powered report generation service — market report + sentiment analysis."""

from __future__ import annotations

import json
import re
import time
from typing import Any

import yfinance as yf
from anthropic import Anthropic

from ward.core.config import get_config
from ward.services.nasdaq_service import MarketService


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

    @property
    def client(self) -> Anthropic:
        if self._client is None:
            self._client = Anthropic(
                api_key=self.config.llm.api_key,
                base_url=self.config.llm.base_url,
            )
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

    def _analyze_sentiment(self, news_items: list[dict]) -> dict[str, Any]:
        """Use LLM to analyze market sentiment from news titles."""
        if not news_items:
            return {"score": None, "interpretation": "无新闻数据", "topics": [], "raw": ""}

        titles = "\n".join(f"- [{item['symbol']}] {item['title']}" for item in news_items)
        prompt = self.SENTIMENT_PROMPT.format(news_titles=titles)

        try:
            response = self.client.messages.create(
                model=self.config.llm.model,
                max_tokens=800,
                system="你是一个客观理性的金融市场情绪分析师。",
                messages=[{"role": "user", "content": prompt}],
            )
            # Handle both TextBlock and ThinkingBlock (newer Claude models)
            text = "\n".join(
                block.text if type(block).__name__ == "TextBlock" else ""
                for block in response.content
            )
            # Parse score from response (handles both int like "5/9" and float like "4.5/9")
            score = None
            for line in text.split("\n"):
                if "评分" in line and "/" in line:
                    m = re.search(r'([0-9.]+)\s*/\s*9', line)
                    if m:
                        score = float(m.group(1))
            return {
                "score": score,
                "interpretation": text,
                "topics": [],
                "raw": text,
                "news_count": len(news_items),
            }
        except Exception as e:
            return {"score": None, "interpretation": f"情绪分析失败: {e}", "topics": [], "raw": ""}

    def generate_market_report(self) -> dict[str, Any]:
        """Generate today's Nasdaq market report with news + sentiment."""
        # 1. Market data
        overview = self.ns.get_market_overview()

        # 2. Fetch news
        news = self._fetch_news()

        # 3. Sentiment analysis
        sentiment = self._analyze_sentiment(news)

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
            response = self.client.messages.create(
                model=self.config.llm.model,
                max_tokens=1500,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text = "\n".join(
                block.text if hasattr(block, "text") else ""
                for block in response.content
            )
            return {
                "ok": True,
                "report": text,
                "data": context,
            }
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "data": context,
            }
