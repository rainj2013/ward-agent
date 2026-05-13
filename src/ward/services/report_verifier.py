"""Deterministic quality checks for generated analysis reports."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class VerificationResult:
    """Structured verifier output stored on analysis jobs."""

    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "errors": self.errors,
            "warnings": self.warnings,
            "checks": self.checks,
        }


class ReportVerifier:
    """Lightweight verifier for Ward's LLM-generated market reports.

    This is intentionally deterministic. It gives the job runtime a real
    quality gate without adding another LLM call or token cost.
    """

    _PLACEHOLDER_PATTERNS = [
        r"\bX{2,}(?:\.\d+)?\b",
        r"\bX\.XX\b",
        r"\{[a-zA-Z_][a-zA-Z0-9_]*\}",
        r"\[[^\]]*同上格式[^\]]*\]",
    ]

    _REQUIRED_SECTIONS = {
        "stock_analysis": [
            "公司概况",
            "今日行情",
            "估值分析",
            "财务数据",
            "资金流向",
            "新闻舆情",
            "分析师观点",
            "技术面分析",
            "投资亮点",
            "主要风险",
            "综合简评",
        ],
        "index_analysis": [
            "行情",
            "技术",
            "市场状态",
            "操作建议",
        ],
        "gold_analysis": [
            "黄金今日行情",
            "宏观经济背景",
            "技术面分析",
            "黄金专属指标",
            "综合判断",
        ],
        "market_report": [
            "今日行情概述",
            "主要指数表现",
            "技术面分析",
            "市场情绪判断",
            "重大新闻事件",
            "投资思考",
        ],
        "stock_comparison": [
            "对比结论",
            "关键指标横向表",
            "逐只股票判断",
            "相对机会与风险",
            "观察清单",
            "综合排序",
        ],
    }

    def verify(self, job_type: str, result: dict[str, Any]) -> VerificationResult:
        report = str(result.get("report") or "").strip()
        errors: list[str] = []
        warnings: list[str] = []
        checks: dict[str, Any] = {
            "job_type": job_type,
            "report_chars": len(report),
        }

        if not report:
            errors.append("报告为空")
            return VerificationResult(False, errors, warnings, checks)

        if len(report) < 300:
            errors.append("报告过短，可能不是完整分析报告")

        placeholder_hits = self._find_placeholders(report)
        checks["placeholder_hits"] = placeholder_hits
        if placeholder_hits:
            errors.append("报告包含未替换的模板占位符")

        required_key = self._required_key(job_type, result)
        required_sections = self._REQUIRED_SECTIONS.get(required_key, [])
        found_sections, missing_sections = self._check_sections(report, required_sections)
        checks["required_profile"] = required_key
        checks["sections_found"] = found_sections
        checks["sections_missing"] = missing_sections

        if required_sections:
            missing_ratio = len(missing_sections) / len(required_sections)
            if missing_ratio >= 0.5:
                errors.append("报告缺少过多必需章节")
            elif missing_sections:
                warnings.append("报告缺少部分建议章节：" + "、".join(missing_sections))

        self._check_data_alignment(result, report, warnings, checks)

        return VerificationResult(not errors, errors, warnings, checks)

    def _required_key(self, job_type: str, result: dict[str, Any]) -> str:
        if job_type == "index_analysis":
            prefix = str(result.get("prefix") or result.get("data", {}).get("prefix") or "").lower()
            if prefix == "gold":
                return "gold_analysis"
        return job_type

    def _find_placeholders(self, report: str) -> list[str]:
        hits: list[str] = []
        for pattern in self._PLACEHOLDER_PATTERNS:
            hits.extend(re.findall(pattern, report))
        return sorted(set(hits))[:10]

    def _check_sections(self, report: str, required_sections: list[str]) -> tuple[list[str], list[str]]:
        found = []
        missing = []
        for section in required_sections:
            if section in report:
                found.append(section)
            else:
                missing.append(section)
        return found, missing

    def _check_data_alignment(
        self,
        result: dict[str, Any],
        report: str,
        warnings: list[str],
        checks: dict[str, Any],
    ) -> None:
        data = result.get("data") or {}
        quote = data.get("quote") if isinstance(data, dict) else None
        if isinstance(quote, dict):
            price = quote.get("price") or quote.get("close")
            if price is not None:
                price_tokens = self._number_tokens(price)
                checks["quote_price_tokens"] = price_tokens
                if price_tokens and not any(token in report for token in price_tokens):
                    warnings.append("报告未明显引用当前价格字段")

        overview = data.get("market_overview") if isinstance(data, dict) else None
        if isinstance(overview, dict) and overview.get("ok") is False:
            warnings.append("市场概览数据获取失败，报告可信度受限")

        symbols = data.get("symbols") if isinstance(data, dict) else None
        if isinstance(symbols, list):
            missing_symbols = [str(symbol) for symbol in symbols if str(symbol) not in report]
            checks["symbols_checked"] = symbols
            checks["symbols_missing"] = missing_symbols
            if missing_symbols:
                warnings.append("报告未明显覆盖部分对比标的：" + "、".join(missing_symbols))

        if "不要编造" in report or "无法从提供的数据" in report:
            checks["explicit_data_caution"] = True

    def _number_tokens(self, value: Any) -> list[str]:
        try:
            num = float(value)
        except (TypeError, ValueError):
            return []
        tokens = {
            f"{num:.2f}",
            f"{num:,.2f}",
            str(round(num, 2)).rstrip("0").rstrip("."),
        }
        return [token for token in tokens if token]
