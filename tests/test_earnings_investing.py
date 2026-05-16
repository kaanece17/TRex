from __future__ import annotations

import pandas as pd
import requests
from types import SimpleNamespace

from bist_factor_backtest.data.earnings_investing import (
    InvestingEarningsLoader,
    _http_get,
    _normalize_investing_quote_url,
    _read_html_tables,
    merge_announcements_into_statements,
)


class TestInvestingEarningsLoader:
    def test_fetchRecords_requestsPageAndParsesHtml(self, monkeypatch):
        loader = InvestingEarningsLoader(request_timeout_seconds=7)
        captured = {}

        def fake_resolve(symbol, earnings_url):
            captured["resolve"] = (symbol, earnings_url)
            return 101

        def fake_fetch_api(symbol, earnings_url, instrument_id):
            captured["api"] = (symbol, earnings_url, instrument_id)
            return [
                {
                    "symbol": symbol.upper(),
                    "period_end": pd.Timestamp("2024-03-31").date(),
                    "announcement_date": pd.Timestamp("2024-05-08").date(),
                    "announcement_source_url": earnings_url,
                }
            ]

        monkeypatch.setattr(loader, "_resolve_instrument_id", fake_resolve)
        monkeypatch.setattr(loader, "_fetch_api_records", fake_fetch_api)

        records = loader.fetch_records("aksa", "https://example.com/e")

        assert captured["resolve"] == ("aksa", "https://example.com/e")
        assert captured["api"] == ("aksa", "https://example.com/e", 101)
        assert len(records) == 1
        assert records[0]["announcement_source_url"] == "https://example.com/e"

    def test_fetchRecords_fallsBackToHtmlWhenInstrumentIdMissing(self, monkeypatch):
        loader = InvestingEarningsLoader()
        captured = {}

        def fake_resolve(symbol, earnings_url):
            captured["resolve"] = (symbol, earnings_url)
            return None

        def fake_fetch_html(symbol, earnings_url):
            captured["html"] = (symbol, earnings_url)
            return [{"symbol": "AKSA"}]

        monkeypatch.setattr(loader, "_resolve_instrument_id", fake_resolve)
        monkeypatch.setattr(loader, "_fetch_html_records", fake_fetch_html)

        assert loader.fetch_records("aksa", "https://example.com/e") == [{"symbol": "AKSA"}]
        assert captured["html"] == ("aksa", "https://example.com/e")

    def test_fetchRecords_fallsBackToHtmlWhenApiFetchFails(self, monkeypatch):
        loader = InvestingEarningsLoader()
        monkeypatch.setattr(loader, "_resolve_instrument_id", lambda *args, **kwargs: 123)
        monkeypatch.setattr(
            loader,
            "_fetch_api_records",
            lambda *args, **kwargs: (_ for _ in ()).throw(requests.HTTPError("boom")),
        )
        monkeypatch.setattr(loader, "_fetch_html_records", lambda *args, **kwargs: [{"symbol": "AKSA"}])

        assert loader.fetch_records("aksa", "https://example.com/e") == [{"symbol": "AKSA"}]

    def test_parseHtml_extractsAnnouncementRows(self):
        html = """
        <table>
          <tr><th>Yayın Tarihi</th><th>Dönem Sonu</th><th>EPS</th></tr>
          <tr><td>08.05.2024</td><td>31.03.2024</td><td>1,23</td></tr>
          <tr><td>12.08.2024</td><td>30.06.2024</td><td>1,50</td></tr>
        </table>
        """

        records = InvestingEarningsLoader().parse_html("aksa", html, "https://example.com/earnings")

        assert len(records) == 2
        assert records[0]["announcement_date"].isoformat() == "2024-05-08"
        assert records[1]["period_end"].isoformat() == "2024-06-30"

    def test_parseHtml_handlesEmptyAndNonMatchingTables(self):
        loader = InvestingEarningsLoader()

        assert loader.parse_html("aksa", "<div>no table</div>", "https://example.com") == []
        assert loader.parse_html(
            "aksa",
            """
            <table>
              <tr><th>Something</th><th>Else</th></tr>
              <tr><td>1</td><td>2</td></tr>
            </table>
            """,
            "https://example.com",
        ) == []

    def test_parseApiPayload_extractsAnnouncementRows(self):
        payload = {
            "earnings": [
                {"date": "2024-05-08", "report_year": 2024, "report_month": 3},
                {"date": "2024-08-12", "report_year": 2024, "report_month": 6},
            ]
        }

        records = InvestingEarningsLoader()._parse_api_payload("aksa", payload, "https://example.com/earnings")

        assert len(records) == 2
        assert records[0]["announcement_date"].isoformat() == "2024-05-08"
        assert records[1]["period_end"].isoformat() == "2024-06-01"

    def test_parseApiPayload_skipsInvalidRows(self):
        payload = {
            "earnings": [
                {"date": None, "report_year": 2024, "report_month": 3},
                {"date": "2024-05-08", "report_year": None, "report_month": 3},
                {"date": "2024-05-08", "report_year": 2024, "report_month": 13},
            ]
        }

        assert InvestingEarningsLoader()._parse_api_payload("aksa", payload, "https://example.com/earnings") == []

    def test_parseHtml_skipsRowsWithInvalidDates(self):
        html = """
        <table>
          <tr><th>Yayın Tarihi</th><th>Dönem Sonu</th></tr>
          <tr><td>invalid</td><td>31.03.2024</td></tr>
          <tr><td>08.05.2024</td><td>invalid</td></tr>
          <tr><td>08.05.2024</td><td>31.03.2024</td></tr>
        </table>
        """

        records = InvestingEarningsLoader().parse_html("aksa", html, "https://example.com/earnings")

        assert len(records) == 1
        assert records[0]["announcement_date"].isoformat() == "2024-05-08"

    def test_internalReadHtmlTables_handlesShortAndEmptyBodies(self):
        assert _read_html_tables("<table><tr><th>only</th></tr></table>") == []
        assert _read_html_tables("<table><tr><th>A</th></tr><tr></tr></table>") == []

    def test_buildFromRecords_completeRecord_returnsAnnouncements(self):
        result = InvestingEarningsLoader().build_from_records(
            "aksa",
            [
                {
                    "period_end": "2024-03-31",
                    "announcement_date": "2024-05-08",
                    "announcement_datetime": "2024-05-08T18:00:00+03:00",
                    "source_url": "https://example.com/aksa-earnings",
                }
            ],
        )

        assert result.failures.empty
        assert result.announcements.loc[0, "symbol"] == "AKSA"
        assert result.announcements.loc[0, "announcement_source_url"] == "https://example.com/aksa-earnings"

    def test_buildFromRecords_turkishAliasesAndFailures_workAsExpected(self):
        result = InvestingEarningsLoader().build_from_records(
            "tborg",
            [
                {"Dönem Sonu": "2024-06-30", "Yayın Tarihi": "2024-08-12"},
                {"Dönem Sonu": "2024-09-30"},
                {"Yayın Tarihi": "2024-11-10"},
            ],
        )

        assert result.announcements.loc[0, "announcement_date"].isoformat() == "2024-08-12"
        assert result.failures["reason"].tolist() == ["missing_announcement_date", "missing_period_end"]

    def test_buildFromRecords_invalidOptionalDateTimeAndBlankSource_areNormalized(self):
        result = InvestingEarningsLoader().build_from_records(
            "afyon",
            [
                {
                    "period_end": "2024-03-31",
                    "announcement_date": "2024-05-10",
                    "announcement_datetime": "invalid-datetime",
                    "announcement_source_url": "",
                    "source_url": "https://example.com/fallback",
                }
            ],
        )

        assert result.failures.empty
        assert pd.isna(result.announcements.loc[0, "announcement_datetime"])
        assert result.announcements.loc[0, "announcement_source_url"] == "https://example.com/fallback"

    def test_buildFromRecords_invalidDates_returnFailures(self):
        result = InvestingEarningsLoader().build_from_records(
            "aksa",
            [
                {"period_end": "invalid", "announcement_date": "2024-05-08"},
                {"period_end": "2024-03-31", "announcement_date": "invalid"},
            ],
        )

        assert result.announcements.empty
        assert result.failures["reason"].tolist() == ["missing_period_end", "missing_announcement_date"]

    def test_buildFromRecords_natOptionalValues_areTreatedAsMissing(self):
        result = InvestingEarningsLoader().build_from_records(
            "segmn",
            [
                {
                    "period_end": "2024-03-31",
                    "announcement_date": "2024-05-10",
                    "announcement_datetime": pd.NaT,
                    "announcement_source_url": pd.NA,
                    "source_url": "https://example.com/nat-fallback",
                }
            ],
        )

        assert result.failures.empty
        assert pd.isna(result.announcements.loc[0, "announcement_datetime"])
        assert result.announcements.loc[0, "announcement_source_url"] == "https://example.com/nat-fallback"

    def test_resolveInstrumentId_prefersRegistryUrlMatch(self, monkeypatch):
        loader = InvestingEarningsLoader()
        monkeypatch.setattr(loader, "_bootstrap_access_token", lambda _: "token")

        class DummyResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "quotes": [
                        {
                            "id": 1,
                            "symbol": "ADEL",
                            "type": "Stock - Istanbul",
                            "flag": "Turkey",
                            "exchange": "Istanbul",
                            "url": "/equities/other-company",
                        },
                        {
                            "id": 19255,
                            "symbol": "ADEL",
                            "type": "Stock - Istanbul",
                            "flag": "Turkey",
                            "exchange": "Istanbul",
                            "url": "/equities/adel-kalemcilik",
                        },
                    ]
                }

        monkeypatch.setattr(loader, "_request_with_retries", lambda *args, **kwargs: DummyResponse())

        instrument_id = loader._resolve_instrument_id("ADEL", "https://tr.investing.com/equities/adel-kalemcilik-earnings")

        assert instrument_id == 19255

    def test_fetchApiRecords_paginatesAndDeduplicates(self, monkeypatch):
        loader = InvestingEarningsLoader()
        monkeypatch.setattr(loader, "_bootstrap_access_token", lambda _: "token")
        payloads = iter(
            [
                {
                    "cursor": "next-page",
                    "earnings": [{"date": "2024-05-08", "report_year": 2024, "report_month": 3}],
                },
                {
                    "cursor": None,
                    "earnings": [
                        {"date": "2024-05-08", "report_year": 2024, "report_month": 3},
                        {"date": "2024-08-12", "report_year": 2024, "report_month": 6},
                    ],
                },
            ]
        )

        class DummyResponse:
            def __init__(self, payload):
                self._payload = payload

            def json(self):
                return self._payload

        monkeypatch.setattr(loader, "_request_with_retries", lambda *args, **kwargs: DummyResponse(next(payloads)))

        records = loader._fetch_api_records("AKSA", "https://example.com/aksa-earnings", 123)

        assert len(records) == 2
        assert {record["period_end"].isoformat() for record in records} == {"2024-03-01", "2024-06-01"}


class TestMergeAnnouncementsIntoStatements:
    def test_mergeAnnouncementsIntoStatements_updatesByStatementIdAndPeriod(self):
        statements = pd.DataFrame(
            [
                {
                    "statement_id": "ISYATIRIM-AKSA-20240331",
                    "symbol": "AKSA",
                    "period_end": "2024-03-31",
                    "announcement_date": None,
                    "announcement_datetime": None,
                    "source_url": "https://example.com/financials",
                },
                {
                    "statement_id": "ISYATIRIM-TBORG-20240630",
                    "symbol": "TBORG",
                    "period_end": "2024-06-30",
                    "announcement_date": None,
                    "announcement_datetime": None,
                    "source_url": "https://example.com/financials2",
                },
            ]
        )
        announcements = pd.DataFrame(
            [
                {
                    "statement_id": "ISYATIRIM-AKSA-20240331",
                    "symbol": "AKSA",
                    "period_end": "2024-03-31",
                    "announcement_date": pd.Timestamp("2024-05-08").date(),
                    "announcement_datetime": pd.Timestamp("2024-05-08T15:00:00Z").to_pydatetime(),
                    "announcement_source_url": "https://example.com/earnings-1",
                },
                {
                    "statement_id": None,
                    "symbol": "TBORG",
                    "period_end": "2024-06-30",
                    "announcement_date": pd.Timestamp("2024-08-12").date(),
                    "announcement_datetime": None,
                    "announcement_source_url": "https://example.com/earnings-2",
                },
            ]
        )

        result = merge_announcements_into_statements(statements, announcements)

        assert result.loc[0, "announcement_date"].isoformat() == "2024-05-08"
        assert str(result.loc[0, "announcement_datetime"]) == "2024-05-08 15:00:00+00:00"
        assert result.loc[0, "announcement_source_url"] == "https://example.com/earnings-1"
        assert result.loc[1, "announcement_date"].isoformat() == "2024-08-12"
        assert pd.isna(result.loc[1, "announcement_datetime"])

    def test_mergeAnnouncementsIntoStatements_emptyInputs_returnsCopy(self):
        statements = pd.DataFrame([{"statement_id": "A"}])

        result = merge_announcements_into_statements(statements, pd.DataFrame())

        assert result.equals(statements)

    def test_mergeAnnouncementsIntoStatements_preservesExistingWhenOverwriteDisabled(self):
        statements = pd.DataFrame(
            [
                {
                    "statement_id": "ISYATIRIM-BLCYT-20230331",
                    "symbol": "BLCYT",
                    "period_end": "2023-03-31",
                    "announcement_date": pd.Timestamp("2023-05-09").date(),
                    "announcement_datetime": None,
                    "announcement_source_url": "https://existing.example.com",
                },
                {
                    "statement_id": "ISYATIRIM-BLCYT-20230630",
                    "symbol": "BLCYT",
                    "period_end": "2023-06-30",
                    "announcement_date": None,
                    "announcement_datetime": None,
                    "announcement_source_url": None,
                },
            ]
        )
        announcements = pd.DataFrame(
            [
                {
                    "statement_id": "ISYATIRIM-BLCYT-20230331",
                    "symbol": "BLCYT",
                    "period_end": "2023-03-31",
                    "announcement_date": pd.Timestamp("2022-06-16").date(),
                    "announcement_datetime": None,
                    "announcement_source_url": "https://fallback.example.com/old",
                },
                {
                    "statement_id": "ISYATIRIM-BLCYT-20230630",
                    "symbol": "BLCYT",
                    "period_end": "2023-06-30",
                    "announcement_date": pd.Timestamp("2023-08-10").date(),
                    "announcement_datetime": None,
                    "announcement_source_url": "https://fallback.example.com/new",
                },
            ]
        )

        result = merge_announcements_into_statements(statements, announcements, overwrite_existing=False)

        assert result.loc[0, "announcement_date"].isoformat() == "2023-05-09"
        assert result.loc[0, "announcement_source_url"] == "https://existing.example.com"
        assert result.loc[1, "announcement_date"].isoformat() == "2023-08-10"
        assert result.loc[1, "announcement_source_url"] == "https://fallback.example.com/new"

    def test_mergeAnnouncementsIntoStatements_overwritesImpossibleEarlyExistingDate(self):
        statements = pd.DataFrame(
            [
                {
                    "statement_id": "ISYATIRIM-SOKE-20230901",
                    "symbol": "SOKE",
                    "period_end": "2023-09-01",
                    "announcement_date": pd.Timestamp("2023-05-09").date(),
                    "announcement_datetime": None,
                    "announcement_source_url": "https://existing.example.com/wrong",
                }
            ]
        )
        announcements = pd.DataFrame(
            [
                {
                    "statement_id": "ISYATIRIM-SOKE-20230901",
                    "symbol": "SOKE",
                    "period_end": "2023-09-01",
                    "announcement_date": pd.Timestamp("2023-11-08").date(),
                    "announcement_datetime": None,
                    "announcement_source_url": "https://fallback.example.com/correct",
                }
            ]
        )

        result = merge_announcements_into_statements(statements, announcements, overwrite_existing=False)

        assert result.loc[0, "announcement_date"].isoformat() == "2023-11-08"
        assert result.loc[0, "announcement_source_url"] == "https://fallback.example.com/correct"


class TestInvestingUrlNormalization:
    def test_normalizeInvestingQuoteUrl_handlesEarningsAndCid(self):
        assert _normalize_investing_quote_url("https://tr.investing.com/equities/adel-kalemcilik-earnings") == "/equities/adel-kalemcilik"
        assert _normalize_investing_quote_url("/equities/adani-enterprises-earnings?cid=39350&foo=bar") == "/equities/adani-enterprises?cid=39350"
