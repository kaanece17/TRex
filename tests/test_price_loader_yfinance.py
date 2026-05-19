from bist_factor_backtest.data.price_loader_yfinance import normalize_yahoo_symbol, to_yahoo_symbol


def test_yahooSymbolHelpers_supportUsSymbolsWithoutSuffix():
    assert to_yahoo_symbol("HON", None) == "HON"
    assert normalize_yahoo_symbol("HON", None) == "HON"


def test_yahooSymbolHelpers_keepBistSuffixBehavior():
    assert to_yahoo_symbol("SISE", ".IS") == "SISE.IS"
    assert normalize_yahoo_symbol("SISE.IS", ".IS") == "SISE"
