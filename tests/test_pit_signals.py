from datetime import date

import pandas as pd
import pytest

from bist_factor_backtest.factors.pit_signals import (
    attach_announcement_age_days,
    attach_announcement_drift_return,
)


def test_attachAnnouncementAgeDays_returnsRebalanceRelativeAge():
    candidates = pd.DataFrame(
        [
            {"symbol": "AAA", "announcement_date": "2024-04-20"},
        ]
    )

    result = attach_announcement_age_days(candidates, date(2024, 5, 2))

    assert result["announcement_age_days"].iloc[0] == 12


def test_attachAnnouncementDriftReturn_usesPostAnnouncementWindowBeforeBuyDate():
    candidates = pd.DataFrame(
        [
            {"symbol": "AAA", "announcement_date": "2024-04-20"},
        ]
    )
    prices = pd.DataFrame(
        [
            {"symbol": "AAA", "date": "2024-04-19", "adjusted_close": 90},
            {"symbol": "AAA", "date": "2024-04-22", "adjusted_close": 100},
            {"symbol": "AAA", "date": "2024-04-23", "adjusted_close": 105},
            {"symbol": "AAA", "date": "2024-04-24", "adjusted_close": 110},
            {"symbol": "AAA", "date": "2024-05-02", "adjusted_close": 120},
        ]
    )

    result = attach_announcement_drift_return(candidates, prices, date(2024, 5, 2), lookback_days=20)

    assert result["announcement_drift_return"].iloc[0] == pytest.approx(0.10)
