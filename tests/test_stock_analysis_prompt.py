from ward.services.stock_analysis_prompt import build_stock_analysis_prompt


def test_stock_prompt_contains_required_context_sections():
    prompt = build_stock_analysis_prompt({
        "symbol": "MU",
        "name": "Micron Technology Inc.",
        "quote": {"price": 100, "change_pct": 1.5},
        "history_5d": [{"close": 100}],
        "history_30d": [{"close": 90}],
        "financials": {},
        "news": [],
        "money_flow": {},
    })

    assert "代码: MU" in prompt
    assert "=== 今日行情 ===" in prompt
    assert "=== 新闻舆情 ===" in prompt
    assert "=== 近5日K线 ===" in prompt
    assert "=== 近30日K线 ===" in prompt
