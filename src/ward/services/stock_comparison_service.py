"""Leader/Worker style multi-stock comparison analysis."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import perf_counter
from typing import Any


from ward.core.config import get_config
from ward.core.llm import complete_text, create_anthropic_client
from ward.services.db.analysis_cache_service import AnalysisCacheService
from ward.services.stock_service import POPULAR_STOCKS, StockService
from ward.services.stock_symbols import normalize_stock_symbol


class StockComparisonService:
    """Compare multiple stocks using isolated workers and a leader synthesis step."""

    SYSTEM_PROMPT = """你是一个严谨的美股投研负责人。你会收到多个 Worker 产出的结构化股票摘要。
请只基于这些摘要做横向比较，不要补充未提供的数据，不要编造数字。

输出格式：

## 一、对比结论
[用2-3句话说明整体排序和适用投资者]

## 二、关键指标横向表
| 股票 | 当前价 | 今日涨跌幅 | 30日表现 | 趋势 | 估值 | 风险 |
|------|--------|------------|----------|------|------|------|

## 三、逐只股票判断
[每只股票 2-3 条，说明优势、短板、数据缺口]

## 四、相对机会与风险
[从估值、趋势、波动、基本面数据完整性角度比较]

## 五、观察清单
[列出后续需要跟踪的数据或事件]

## 六、综合排序
[给出排序，但必须说明这是基于已提供数据的相对排序，不是确定性投资建议]"""

    def __init__(self):
        self._client = create_anthropic_client()
        self._cache = AnalysisCacheService()

    def generate_comparison(
        self,
        symbols: list[str],
        objective: str | None = None,
        trace=None,
    ) -> dict[str, Any]:
        """Generate a multi-stock comparison report."""
        normalized = self._normalize_symbols(symbols)
        if len(normalized) < 2:
            return {"ok": False, "error": "至少需要 2 个股票代码"}
        if len(normalized) > 6:
            return {"ok": False, "error": "单次最多支持 6 个股票代码"}

        objective = (objective or "比较这些股票的相对机会与风险").strip()
        cache_key = f"stock_compare:{','.join(normalized)}:objective:{objective}:model:{get_config().llm.model}"
        cached = self._cache.get(cache_key)
        if cached:
            if trace:
                trace("cache_hit", "命中缓存，已复用现有对比分析", "cache_hit", {"cache_key": cache_key})
            return {"ok": True, "symbols": normalized, "report": cached["report"], "data": cached["data"], "cached": True}

        if trace:
            trace(
                "leader_plan",
                "Leader 已生成多股票对比计划",
                "leader_plan",
                {
                    "symbols": normalized,
                    "objective": objective,
                    "workers": [{"role": "stock_worker", "symbol": symbol} for symbol in normalized],
                    "verifier": "report_verifier",
                },
            )

        worker_started = perf_counter()
        workers = self._run_workers(normalized, trace=trace)
        if trace:
            trace(
                "stage_end",
                "所有股票 Worker 摘要已完成",
                "worker_fetch",
                {
                    "symbols": normalized,
                    "worker_count": len(workers),
                    "failed_workers": [w["symbol"] for w in workers if not w.get("ok")],
                },
                int((perf_counter() - worker_started) * 1000),
            )

        if sum(1 for worker in workers if worker.get("ok")) < 2:
            return {
                "ok": False,
                "symbols": normalized,
                "error": "可用股票数据不足，无法完成横向比较",
                "data": {"objective": objective, "workers": workers},
            }

        context = {
            "objective": objective,
            "symbols": normalized,
            "workers": workers,
        }
        prompt = self._build_prompt(context)
        report = ""
        try:
            llm_started = perf_counter()
            if trace:
                trace(
                    "llm_call_start",
                    "Leader 正在聚合 Worker 摘要并生成对比报告",
                    "leader_synthesis",
                    {
                        "model": get_config().llm.model,
                        "max_tokens": 5000,
                        "system": self.SYSTEM_PROMPT,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
            report, usage = complete_text(
                self._client, system=self.SYSTEM_PROMPT, prompt=prompt, max_tokens=5000
            )
            if trace:
                trace(
                    "llm_call_end",
                    "Leader 对比报告生成完成",
                    "leader_synthesis",
                    {"usage": usage, "response_text": report},
                    int((perf_counter() - llm_started) * 1000),
                )
            result = {
                "ok": True,
                "symbols": normalized,
                "report": report,
                "data": context,
                "usage": usage,
            }
            self._cache.set(cache_key, report, context)
            return result
        except Exception as exc:
            return {
                "ok": False,
                "symbols": normalized,
                "error": str(exc),
                "data": context,
            }

    def _run_workers(self, symbols: list[str], trace=None) -> list[dict[str, Any]]:
        workers: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=min(len(symbols), 4)) as pool:
            futures = {pool.submit(self._worker_summary, symbol): symbol for symbol in symbols}
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    summary = future.result()
                except Exception as exc:
                    summary = {"ok": False, "symbol": symbol, "error": str(exc)}
                workers.append(summary)
                if trace:
                    trace(
                        "worker_done",
                        f"{symbol} Worker 摘要完成" if summary.get("ok") else f"{symbol} Worker 摘要失败",
                        "worker_fetch",
                        summary,
                    )
        return sorted(workers, key=lambda item: symbols.index(item["symbol"]))

    def _worker_summary(self, symbol: str) -> dict[str, Any]:
        service = StockService()
        quote_result = service.get_quote(symbol)
        kline_result = service.get_kline(symbol, 30)
        if not quote_result.get("ok"):
            return {"ok": False, "symbol": symbol, "error": quote_result.get("error", "行情获取失败")}

        quote = quote_result.get("data") or {}
        klines = kline_result.get("data", []) if kline_result.get("ok") else []
        closes = [float(row["close"]) for row in klines if row.get("close") is not None]
        volumes = [float(row["volume"]) for row in klines if row.get("volume") is not None]
        trend = self._trend_summary(closes, volumes)
        return {
            "ok": True,
            "symbol": symbol,
            "name": quote.get("name") or POPULAR_STOCKS.get(symbol, symbol),
            "quote": {
                "price": quote.get("price"),
                "change": quote.get("change"),
                "change_pct": quote.get("change_pct"),
                "open": quote.get("open"),
                "high": quote.get("high"),
                "low": quote.get("low"),
                "volume": quote.get("volume"),
                "market_cap": quote.get("market_cap"),
                "pe_ratio": quote.get("pe_ratio"),
                "forward_pe": quote.get("forward_pe"),
                "profit_margin": quote.get("profit_margin"),
                "revenue_growth": quote.get("revenue_growth"),
                "fifty_two_week_high": quote.get("fifty_two_week_high"),
                "fifty_two_week_low": quote.get("fifty_two_week_low"),
                "recommendation": quote.get("recommendation"),
                "analyst_targets": quote.get("analyst_targets"),
                "data_source": quote.get("data_source"),
            },
            "trend": trend,
            "data_quality": {
                "quote_ok": quote_result.get("ok", False),
                "kline_ok": kline_result.get("ok", False),
                "kline_count": len(klines),
                "missing_quote_fields": [key for key in ("price", "pe_ratio", "forward_pe", "profit_margin") if quote.get(key) is None],
            },
        }

    def _trend_summary(self, closes: list[float], volumes: list[float]) -> dict[str, Any]:
        if not closes:
            return {"status": "无K线数据"}
        current = closes[-1]
        first = closes[0]
        change_30d_pct = round((current - first) / first * 100, 2) if first else None
        ma5 = round(sum(closes[-5:]) / min(len(closes), 5), 2)
        ma20 = round(sum(closes[-20:]) / min(len(closes), 20), 2)
        if current > ma5 > ma20:
            status = "偏强"
        elif current < ma5 < ma20:
            status = "偏弱"
        else:
            status = "震荡"
        avg_volume = round(sum(volumes[-20:]) / min(len(volumes), 20), 2) if volumes else None
        return {
            "status": status,
            "current": round(current, 2),
            "change_30d_pct": change_30d_pct,
            "ma5": ma5,
            "ma20": ma20,
            "avg_volume_20d": avg_volume,
        }

    def _build_prompt(self, context: dict[str, Any]) -> str:
        compact_workers = [
            {
                "symbol": worker.get("symbol"),
                "name": worker.get("name"),
                "ok": worker.get("ok"),
                "quote": worker.get("quote"),
                "trend": worker.get("trend"),
                "data_quality": worker.get("data_quality"),
                "error": worker.get("error"),
            }
            for worker in context["workers"]
        ]
        return (
            f"比较目标：{context['objective']}\n\n"
            "以下是各 Worker 独立产出的结构化摘要。请只基于这些摘要输出报告：\n"
            f"{json.dumps(compact_workers, ensure_ascii=False, indent=2, default=str)}"
        )

    def _normalize_symbols(self, symbols: list[str]) -> list[str]:
        normalized = []
        for symbol in symbols:
            item = normalize_stock_symbol(symbol)
            if item and item not in normalized:
                normalized.append(item)
        return normalized
