from datetime import date

import pandas as pd

from bist_factor_backtest.data.open_price_capture_yfinance import _select_first_regular_session_bar


def test_selectFirstRegularSessionBar_picksFirstBarAfterOpen_inIstanbulTimezone():
    frame = pd.DataFrame(
        [
            {"bar_timestamp": "2026-06-01T09:59:00+03:00", "open": 99.0},
            {"bar_timestamp": "2026-06-01T10:00:00+03:00", "open": 100.0},
            {"bar_timestamp": "2026-06-01T10:01:00+03:00", "open": 101.0},
        ]
    )

    result = _select_first_regular_session_bar(
        frame,
        trade_date=date(2026, 6, 1),
        market_open_time="10:00",
        timezone="Europe/Istanbul",
    )

    assert result is not None
    assert result["open"] == 100.0


def test_selectFirstRegularSessionBar_returnsNoneWhenNoBarAfterOpen():
    frame = pd.DataFrame(
        [
            {"bar_timestamp": "2026-06-01T09:55:00+03:00", "open": 98.0},
            {"bar_timestamp": "2026-06-01T09:59:00+03:00", "open": 99.0},
        ]
    )

    result = _select_first_regular_session_bar(
        frame,
        trade_date=date(2026, 6, 1),
        market_open_time="10:00",
        timezone="Europe/Istanbul",
    )

    assert result is None
