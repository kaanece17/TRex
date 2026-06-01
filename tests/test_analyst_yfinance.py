import pandas as pd

from bist_factor_backtest.data.analyst_yfinance import AnalystYFinanceLoader


class DummyTicker:
    def __init__(self):
        self.earnings_history = pd.DataFrame(
            [
                {
                    "epsActual": 1.2,
                    "epsEstimate": 1.0,
                    "epsDifference": 0.2,
                    "surprisePercent": 0.2,
                }
            ]
        ).set_index(pd.Index(pd.to_datetime(["2024-03-31"]), name="quarter"))
        self.earnings_estimate = pd.DataFrame(
            [{"avg": 1.5, "low": 1.4, "high": 1.6, "numberOfAnalysts": 10}],
            index=["0q"],
        )
        self.revenue_estimate = pd.DataFrame(
            [{"avg": 100.0, "low": 95.0, "high": 110.0, "numberOfAnalysts": 8}],
            index=["0q"],
        )
        self.eps_revisions = pd.DataFrame(
            [{"upLast7days": 1, "upLast30days": 2, "downLast7Days": 0, "downLast30days": 1}],
            index=["0q"],
        )
        self.recommendations = pd.DataFrame(
            [{"period": "0q", "strongBuy": 3, "buy": 4, "hold": 2, "sell": 1, "strongSell": 0}]
        )


def test_buildConsensusHistory_returnsPeriodRows():
    loader = AnalystYFinanceLoader()

    rows = loader._build_consensus_history("AAA", DummyTicker())

    assert rows[0]["symbol"] == "AAA"
    assert rows[0]["period_end"].isoformat() == "2024-03-31"
    assert rows[0]["eps_surprise_percent"] == 0.2


def test_buildSnapshotHistory_returnsMergedAnalystRows():
    loader = AnalystYFinanceLoader()

    rows = loader._build_snapshot_history(
        "AAA",
        DummyTicker(),
        pd.Timestamp("2024-05-10T12:00:00Z").to_pydatetime(),
        pd.Timestamp("2024-05-10").date(),
    )

    assert len(rows) == 1
    assert rows[0]["period"] == "0q"
    assert rows[0]["earnings_estimate_avg"] == 1.5
    assert rows[0]["up_last30days"] == 2.0
    assert rows[0]["strong_buy"] == 3.0
