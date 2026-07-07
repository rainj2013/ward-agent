from ward.services.stock_service import StockService


def service() -> StockService:
    return object.__new__(StockService)


def test_search_supports_known_symbol_and_name():
    assert service().search("MU")["results"][0]["symbol"] == "MU"
    assert service().search("Micron")["results"][0]["symbol"] == "MU"


def test_search_accepts_unknown_ticker_shape():
    assert service().search("nvts")["results"] == [{"symbol": "NVTS", "name": "NVTS"}]


def test_search_rejects_empty_query():
    assert service().search("   ")["results"] == []
