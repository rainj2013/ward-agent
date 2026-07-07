"""Pure prompt construction for stock analysis."""

from __future__ import annotations

import json
from typing import Any


def format_currency(value: Any) -> str:
    if value is None:
        return "无数据"
    if abs(value) >= 1e12:
        return f"${value / 1e12:.2f}万亿"
    if abs(value) >= 1e9:
        return f"${value / 1e9:.2f}亿"
    if abs(value) >= 1e6:
        return f"${value / 1e6:.2f}百万"
    return f"${value:.2f}"


def format_percent(value: Any) -> str:
    if value is None:
        return "无数据"
    return f"{value * 100:.2f}%" if isinstance(value, float) else str(value)


def build_stock_analysis_prompt(context: dict[str, Any]) -> str:
    symbol = context["symbol"]
    name = context["name"]
    quote = context.get("quote") or {}
    financials = context.get("financials") or {}
    news = context.get("news") or []
    money_flow = context.get("money_flow") or {}

    income = financials.get("income_stmt") or {}
    balance = financials.get("balance_sheet") or {}
    cashflow = financials.get("cashflow") or {}
    income_lines = [
        f"营收: {format_currency(income.get('Total Revenue'))}",
        f"毛利润: {format_currency(income.get('Gross Profit'))}",
        f"净利润: {format_currency(income.get('Net Income'))}",
        f"运营利润: {format_currency(income.get('Operating Income'))}",
        f"摊薄 EPS: {income.get('Diluted EPS', '无数据')}",
    ] if income else ["无数据"]
    balance_lines = [
        f"总资产: {format_currency(balance.get('Total Assets'))}",
        f"总负债: {format_currency(balance.get('Total Liabilities'))}",
        f"股东权益: {format_currency(balance.get('Total Equity'))}",
        f"流动资产: {format_currency(balance.get('Current Assets'))}",
    ] if balance else ["无数据"]
    cashflow_lines = [
        f"运营现金流: {format_currency(cashflow.get('Operating Cash Flow'))}",
        f"自由现金流: {format_currency(cashflow.get('Free Cash Flow'))}",
        f"资本支出: {format_currency(cashflow.get('Capital Expenditure'))}",
    ] if cashflow else ["无数据"]

    targets = quote.get("analyst_targets") or {}
    news_lines = [f"- [{item.get('time', '')[:10]}] {item.get('title', '')}（来源: {item.get('source', '')}）" for item in news]
    institution_lines = [
        f"- {row.get('holder', '')}: {float(row.get('pct', 0)):.2f}% 持股"
        for row in money_flow.get("institutions", [])[:5]
    ]
    insider_lines = [
        f"- {str(row.get('date', ''))[:10]} | {row.get('insider', '')} | {row.get('transaction', '')} | {row.get('shares', 0)}股"
        for row in money_flow.get("insider_transactions", [])[:5]
    ]
    short = money_flow.get("short_data") or {}
    inst_pct = money_flow.get("inst_pct")

    return f"""请分析以下股票数据，生成专业分析报告。

=== 股票基本信息 ===
代码: {symbol}
名称: {name}

=== 今日行情 ===
当前价: {quote.get('price', '无数据')}
昨收: {quote.get('previous_close', '无数据')}
今开: {quote.get('open', '无数据')}
日内高/低: {quote.get('high', '无数据')} / {quote.get('low', '无数据')}
涨跌幅: {quote.get('change_pct', '无数据')}%
成交量: {quote.get('volume', '无数据')}
市值: {format_currency(quote.get('market_cap'))}
Trailing / Forward P/E: {quote.get('pe_ratio', '无数据')} / {quote.get('forward_pe', '无数据')}
股息率: {format_percent(quote.get('dividend_yield'))}
营收增长: {format_percent(quote.get('revenue_growth'))}
利润率: {format_percent(quote.get('profit_margin'))}
52周高/低: {quote.get('fifty_two_week_high', '无数据')} / {quote.get('fifty_two_week_low', '无数据')}

=== 资金流向 ===
机构持股比例: {f'{inst_pct:.2f}%' if isinstance(inst_pct, (int, float)) else '无数据'}
机构股东:
{chr(10).join(institution_lines) or '无数据'}
内部人交易:
{chr(10).join(insider_lines) or '无数据'}
做空比例 / 做空天数: {short.get('short_percent_float', '无数据')}% / {short.get('short_ratio', '无数据')}天

=== 新闻舆情 ===
{chr(10).join(news_lines) or '无数据'}

=== 分析师评级 ===
综合评级: {quote.get('recommendation', '无数据')}
目标价低 / 均值 / 高: {targets.get('target_low', '无数据')} / {targets.get('target_mean', '无数据')} / {targets.get('target_high', '无数据')}
上涨空间: {format_percent(targets.get('target_upside'))}

=== 利润表 ===
{chr(10).join(income_lines)}

=== 资产负债表 ===
{chr(10).join(balance_lines)}

=== 现金流量表 ===
{chr(10).join(cashflow_lines)}

=== 近5日K线 ===
{json.dumps(context.get('history_5d') or [], indent=2, ensure_ascii=False, default=str)}

=== 近30日K线 ===
{json.dumps(context.get('history_30d') or [], indent=2, ensure_ascii=False, default=str)}"""
