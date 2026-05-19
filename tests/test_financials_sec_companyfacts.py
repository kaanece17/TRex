from datetime import date

from bist_factor_backtest.data.financials_sec_companyfacts import (
    _pick_best_fact,
    _recent_supported_filings,
)


def test_recentSupportedFilings_filtersUnsupportedFormsAndDates():
    filings = _recent_supported_filings(
        {
            "filings": {
                "recent": {
                    "form": ["8-K", "10-Q", "10-K"],
                    "accessionNumber": ["1", "2", "3"],
                    "filingDate": ["2024-05-01", "2024-05-02", "2024-02-10"],
                    "reportDate": ["2024-04-30", "2024-03-31", "2023-12-31"],
                    "acceptanceDateTime": ["20240501120000", "20240502123000", "20240210113000"],
                    "fiscalYearEnd": ["1231", "1231", "1231"],
                }
            }
        },
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
    )

    assert [row["accession_number"] for row in filings] == ["2"]
    assert [row["fiscal_period"] for row in filings] == ["Q1"]


def test_pickBestFact_prefersMatchingAccessionAndFrameLessEntry():
    value = _pick_best_fact(
        [
            {"accn": "0001", "end": "2024-03-31", "filed": "2024-05-02", "val": 10, "frame": "CY2024Q1"},
            {"accn": "0001", "end": "2024-03-31", "filed": "2024-05-02", "val": 12, "frame": None},
        ],
        accession="0001",
        report_date=date(2024, 3, 31),
        filing_date=date(2024, 5, 2),
    )

    assert value == 12.0
