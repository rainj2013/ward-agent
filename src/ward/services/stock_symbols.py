"""Stock symbol normalization helpers."""

from __future__ import annotations


SYMBOL_ALIASES = {
    "APPL": "AAPL",
    "GOOG": "GOOGL",
}

_SYMBOL_STOPWORDS = {
    "AND",
    "OR",
    "VS",
    "THE",
    "A",
    "AN",
}


def normalize_stock_symbol(value: str, allow_unknown: bool = True) -> str | None:
    """Return a ticker-like symbol candidate, accepting common typos.

    This does not validate market existence. Data tools validate the symbol by
    fetching quote/K-line data, so Ward is not limited to a hard-coded universe.
    """
    raw = str(value or "").strip()
    symbol = raw.lstrip("$").upper()
    if not symbol:
        return None
    symbol = SYMBOL_ALIASES.get(symbol, symbol)
    if allow_unknown and symbol.isalpha() and 1 <= len(symbol) <= 5 and symbol not in _SYMBOL_STOPWORDS:
        return symbol
    return None
