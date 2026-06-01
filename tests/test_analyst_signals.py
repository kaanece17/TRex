from datetime import date

import pandas as pd
import pytest

from bist_factor_backtest.factors.analyst_signals import attach_latest_analyst_snapshot


def test_attachLatestAnalystSnapshot_usesLatestSnapshotBeforeBuyDate():
    candidates = pd.DataFrame([{"symbol": "AAA"}])
    snapshots = pd.DataFrame(
        [
            {
                "symbol": "AAA",
                "as_of_date": "2024-04-01",
                "period": "0q",
                "up_last7days": 1,
                "up_last30days": 2,
                "down_last7days": 0,
                "down_last30days": 1,
                "strong_buy": 5,
                "buy": 4,
                "hold": 1,
                "sell": 0,
                "strong_sell": 0,
            },
            {
                "symbol": "AAA",
                "as_of_date": "2024-05-01",
                "period": "0q",
                "up_last7days": 2,
                "up_last30days": 3,
                "down_last7days": 1,
                "down_last30days": 0,
                "strong_buy": 6,
                "buy": 3,
                "hold": 1,
                "sell": 0,
                "strong_sell": 0,
            },
        ]
    )

    result = attach_latest_analyst_snapshot(candidates, snapshots, date(2024, 5, 15))

    assert result["analyst_revision_balance"].iloc[0] == pytest.approx(4.0)
    assert result["recommendation_score"].iloc[0] == pytest.approx(0.9)
