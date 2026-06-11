"""Context digesting and persistent summary helpers for Ward chat."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import tiktoken


SUMMARY_RECENT_MESSAGE_COUNT = 8
SUMMARY_MIN_DELTA_MESSAGES = 6
SUMMARY_MIN_DELTA_TOKENS = 2500


@dataclass
class ContextDigest:
    """Stable, compact representation of page context for the current turn."""

    text: str
    stats: dict[str, Any]


def estimate_tokens(text: str) -> int:
    """Estimate tokens with the same tokenizer family used by the agent."""
    if not text:
        return 0
    try:
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except Exception:
        return max(1, int(len(text) / 2.5))


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate tokens for persisted message rows."""
    total = 0
    for msg in messages:
        total += estimate_tokens(str(msg.get("content") or "")) + 4
    return total


def build_context_digest(ctx: Any | None) -> ContextDigest:
    """Build a stable digest from ChatContext without injecting raw arrays."""
    if ctx is None:
        return ContextDigest("", _empty_context_stats())

    lines: list[str] = ["[页面上下文摘要]", "说明：这是当前浏览器页面已加载数据的服务端摘要；实时行情以工具最新返回为准。"]
    stats = _empty_context_stats()

    indices = list(_iter_items(ctx, "indices"))
    if indices:
        lines.append("指数快照：")
        for item in sorted(indices, key=lambda x: str(_field(x, "name", ""))):
            lines.append(
                "- {name}: close={close}, change={change}({change_pct}%), open={open}, high={high}, low={low}, volume={volume}".format(
                    name=_field(item, "name"),
                    close=_num(_field(item, "close")),
                    change=_num(_field(item, "change")),
                    change_pct=_num(_field(item, "change_pct")),
                    open=_num(_field(item, "open")),
                    high=_num(_field(item, "high")),
                    low=_num(_field(item, "low")),
                    volume=_num(_field(item, "volume")),
                )
            )
        stats["indices"] = len(indices)

    stocks = list(_iter_items(ctx, "stocks"))
    if stocks:
        lines.append("个股快照：")
        for item in sorted(stocks, key=lambda x: str(_field(x, "symbol", "")).upper()):
            lines.append(
                "- {name}({symbol}): close={close}, change={change}({change_pct}%), open={open}, high={high}, low={low}, volume={volume}".format(
                    name=_field(item, "name"),
                    symbol=str(_field(item, "symbol", "")).upper(),
                    close=_num(_field(item, "close")),
                    change=_num(_field(item, "change")),
                    change_pct=_num(_field(item, "change_pct")),
                    open=_num(_field(item, "open")),
                    high=_num(_field(item, "high")),
                    low=_num(_field(item, "low")),
                    volume=_num(_field(item, "volume")),
                )
            )
        stats["stocks"] = len(stocks)

    for title, attr in (("指数K线摘要", "index_klines"), ("个股K线摘要", "stock_klines")):
        data = _dict_field(ctx, attr)
        if data:
            lines.append(f"{title}：")
            for symbol in sorted(data):
                bars = list(data.get(symbol) or [])
                summary = _summarize_bars(bars)
                if summary:
                    lines.append(f"- {str(symbol).upper()}: {summary}")
                    stats[attr] += 1

    for title, attr in (("指数AI分析摘要", "index_analyses"), ("个股AI分析摘要", "stock_analyses")):
        data = _dict_field(ctx, attr)
        if data:
            lines.append(f"{title}：")
            for symbol in sorted(data):
                report = str(data.get(symbol) or "").strip()
                if report:
                    lines.append(f"- {str(symbol).upper()}: {_compact_text(report, 240)}")
                    stats[attr] += 1

    extended = _dict_field(ctx, "extended_hours")
    if extended:
        lines.append("盘前/盘后摘要：")
        for symbol in sorted(extended):
            item = extended.get(symbol)
            lines.append(f"- {str(symbol).upper()}: {_compact_json(_to_plain(item), 220)}")
            stats["extended_hours"] += 1

    if len(lines) == 2:
        return ContextDigest("", stats)

    text = "\n".join(lines)
    stats["digest_chars"] = len(text)
    stats["digest_tokens_est"] = estimate_tokens(text)
    return ContextDigest(text, stats)


def build_summary_prompt(
    previous_summary: str,
    delta_messages: list[dict[str, Any]],
    summarized_until_message_id: int | None,
) -> str:
    """Create a deterministic incremental summary prompt."""
    previous = previous_summary.strip() or "无"
    rows = []
    for msg in delta_messages:
        rows.append(
            "message_id={id} role={role} created_at={created_at}\n{content}".format(
                id=msg.get("id"),
                role=msg.get("role"),
                created_at=msg.get("created_at", ""),
                content=str(msg.get("content") or "").strip(),
            )
        )
    delta = "\n\n---\n\n".join(rows)
    return f"""你要维护 Ward 美股分析对话的持久增量摘要。

已有摘要覆盖到 message_id={summarized_until_message_id or 0}：
{previous}

下面是本次新增、且已经离开最近保护区的对话片段：
{delta}

请输出一份合并后的中文摘要，要求：
1. 保留用户关注的标的、市场、时间范围、风险偏好和明确约束。
2. 保留已经给出的关键判断、依据、数据日期；行情类事实必须带日期或说明可能过期。
3. 保留尚未完成的问题和下一步。
4. 删除寒暄、重复表达、过期的中间措辞。
5. 不要编造任何价格、涨跌幅、财务数据。

固定格式：
用户关注：
已确认事实：
历史判断：
待办/下一步：
注意事项：
"""


def should_update_summary(delta_messages: list[dict[str, Any]]) -> tuple[bool, dict[str, Any]]:
    """Decide whether the delta is large enough to summarize now."""
    delta_tokens = estimate_messages_tokens(delta_messages)
    should = (
        len(delta_messages) >= SUMMARY_MIN_DELTA_MESSAGES
        or delta_tokens >= SUMMARY_MIN_DELTA_TOKENS
    )
    return should, {
        "delta_messages": len(delta_messages),
        "delta_tokens_est": delta_tokens,
        "min_delta_messages": SUMMARY_MIN_DELTA_MESSAGES,
        "min_delta_tokens": SUMMARY_MIN_DELTA_TOKENS,
    }


def _empty_context_stats() -> dict[str, Any]:
    return {
        "indices": 0,
        "stocks": 0,
        "index_klines": 0,
        "stock_klines": 0,
        "index_analyses": 0,
        "stock_analyses": 0,
        "extended_hours": 0,
        "digest_chars": 0,
        "digest_tokens_est": 0,
    }


def _field(obj: Any, name: str, default: Any = "无") -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _dict_field(obj: Any, name: str) -> dict[str, Any]:
    value = _field(obj, name, {})
    return value if isinstance(value, dict) else {}


def _iter_items(obj: Any, name: str) -> list[Any]:
    value = _field(obj, name, [])
    return value if isinstance(value, list) else []


def _num(value: Any) -> str:
    if value is None:
        return "无"
    try:
        return f"{float(value):.4g}"
    except Exception:
        return str(value)


def _summarize_bars(bars: list[Any]) -> str:
    if not bars:
        return ""
    first = bars[0]
    last = bars[-1]
    first_close = _as_float(_field(first, "close", None))
    last_close = _as_float(_field(last, "close", None))
    closes = [_as_float(_field(bar, "close", None)) for bar in bars]
    volumes = [_as_float(_field(bar, "volume", None)) for bar in bars]
    closes = [v for v in closes if v is not None]
    volumes = [v for v in volumes if v is not None]
    pct = None
    if first_close and last_close is not None:
        pct = (last_close - first_close) / first_close * 100
    high = max(closes) if closes else None
    low = min(closes) if closes else None
    avg_volume = sum(volumes) / len(volumes) if volumes else None
    return (
        f"{len(bars)}根, { _field(first, 'date') }至{ _field(last, 'date') }, "
        f"最新收盘={_num(last_close)}, 区间涨跌={_num(pct)}%, "
        f"区间高低={_num(high)}/{_num(low)}, 均量={_num(avg_volume)}"
    )


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _compact_text(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + f"...[已截断，原始{len(text)}字]"


def _compact_json(value: Any, limit: int) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return _compact_text(text, limit)


def _to_plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return value
    return str(value)
