from __future__ import annotations

import pandas as pd
import requests

from bist_factor_backtest.data.financials_isyatirim import (
    IsYatirimFinancialLoader,
    _flatten_column_name,
    _iter_financial_table_values,
    _read_html_tables,
    _resolve_item_code,
)


class TestIsYatirimFinancialLoader:
    def test_fetchRecords_requestsCompanyPageAndParsesHtml(self, monkeypatch):
        html = """
        <select id="ddlMaliTabloExchange"><option selected="selected" value="TRY">TL</option></select>
        <select id="ddlMaliTabloGroup"><option selected="selected" value="XI_29">XI_29</option></select>
        <select id="ddlMaliTabloDonem1">
          <option selected="selected" value="2024/3">2024/3</option>
          <option value="2023/12">2023/12</option>
        </select>
        """
        payload = {
            "ok": True,
            "value": [
                {"itemDescTr": "Özkaynaklar", "value1": "2.000,00", "value2": "1.900,00"},
                {"itemDescTr": "Ödenmiş Sermaye", "value1": "50,00", "value2": "50,00"},
                {"itemDescTr": "Dönem Net Kar/Zararı", "value1": "10,50", "value2": "9,25"},
                {"itemDescTr": "Faaliyet Karı (Zararı)", "value1": "8,25", "value2": "7,00"},
            ],
        }

        class DummyResponse:
            def __init__(self, text="", json_payload=None):
                self.text = text
                self._json_payload = json_payload

            def raise_for_status(self):
                return None

            def json(self):
                return self._json_payload

        captured = {}

        def fake_get(url, headers, timeout, params=None):
            captured.setdefault("urls", []).append(url)
            captured["timeout"] = timeout
            if "Common/Data.aspx/MaliTablo" in url:
                captured["params"] = params
                return DummyResponse(json_payload=payload)
            return DummyResponse(text=html)

        monkeypatch.setattr(requests, "get", fake_get)

        records = IsYatirimFinancialLoader(request_timeout_seconds=9).fetch_records("aksa")

        assert captured["urls"][0].endswith("hisse=AKSA")
        assert captured["timeout"] == 9
        assert captured["params"]["companyCode"] == "AKSA"
        assert len(records) == 2
        assert records[0]["equity"] == 1900.0
        assert records[1]["operating_profit"] == 8.25

    def test_parseHtml_extractsPeriodRecords(self):
        html = """
        <table>
          <tr><th>Mali Tablo</th><th>31.03.2024</th><th>31.12.2023</th></tr>
          <tr><td>Özkaynaklar</td><td>2.000,00</td><td>1.900,00</td></tr>
          <tr><td>Ödenmiş Sermaye</td><td>50,00</td><td>50,00</td></tr>
          <tr><td>Net Kâr</td><td>10,50</td><td>9,25</td></tr>
          <tr><td>Esas Faaliyet Karı</td><td>8,25</td><td>7,00</td></tr>
          <tr><td>Nakit ve Nakit Benzerleri</td><td>3,50</td><td>2,00</td></tr>
          <tr><td>Finansal Borçlar</td><td>4,25</td><td>4,00</td></tr>
        </table>
        """

        records = IsYatirimFinancialLoader().parse_html("aksa", html, "https://example.com")

        assert len(records) == 2
        assert records[0]["period_end"].isoformat() == "2023-12-31"
        assert records[0]["shares_outstanding"] == 50.0
        assert records[1]["net_income"] == 10.5

    def test_parseHtml_handlesEmptyOrIrrelevantTables(self):
        loader = IsYatirimFinancialLoader()

        assert loader.parse_html("aksa", "<div>no table</div>", "https://example.com") == []
        assert loader.parse_html(
            "aksa",
            """
            <table>
              <tr><th>Label</th><th>Not a date</th></tr>
              <tr><td>Something Else</td><td>1,00</td></tr>
            </table>
            """,
            "https://example.com",
        ) == []
        assert loader.parse_html(
            "aksa",
            """
            <table>
              <tr><th>Mali Tablo</th><th>31.03.2024</th></tr>
              <tr><td>Unknown Metric</td><td>1,00</td></tr>
            </table>
            """,
            "https://example.com",
        ) == []

    def test_internalTableHelpers_coverMalformedInputs(self):
        assert list(_iter_financial_table_values(pd.DataFrame())) == []
        assert list(_iter_financial_table_values(pd.DataFrame({"only": ["x"]}))) == []
        assert _flatten_column_name(("A", "B")) == "A B"
        assert _resolve_item_code("Unknown Metric") is None
        assert _read_html_tables("<table><tr><th>only</th></tr></table>") == []
        assert _read_html_tables("<table><tr><th>A</th></tr><tr></tr></table>") == []

    def test_internalValueIterator_skipsUnknownRowsAndMissingValues(self):
        table = pd.DataFrame(
            [
                ["", "1,00", None],
                ["nan", "2,00", None],
                ["Unknown", None, None],
                ["Özkaynaklar", None, "3,00"],
            ],
            columns=["Mali Tablo", "31.03.2024", "31.12.2023"],
        )

        values = list(_iter_financial_table_values(table))

        assert values == [("Özkaynaklar", pd.Timestamp("2023-12-31").date(), 3.0)]

    def test_buildFromRecords_completeRecord_returnsStatementsAndItems(self):
        result = IsYatirimFinancialLoader().build_from_records(
            "aksa",
            [
                {
                    "period_end": "2024-03-31",
                    "announcement_date": "2024-05-08",
                    "announcement_datetime": "2024-05-08T18:00:00+03:00",
                    "currency": "TRY",
                    "is_consolidated": True,
                    "source_url": "https://example.com/aksa",
                    "net_income": "1.234,50",
                    "equity": "2.000,00",
                    "operating_profit": "250,75",
                    "cash": "400,00",
                    "total_debt": "125,00",
                    "shares_outstanding": "323.750.000",
                }
            ],
        )

        assert result.failures.empty
        assert result.statements.loc[0, "statement_id"] == "ISYATIRIM-AKSA-20240331"
        assert result.statements.loc[0, "shares_outstanding"] == 323750000.0
        assert str(result.statements.loc[0, "announcement_datetime"]) == "2024-05-08 15:00:00+00:00"
        assert result.items["item_code"].tolist() == [
            "net_income",
            "equity",
            "operating_profit",
            "cash",
            "total_debt",
        ]

    def test_buildFromRecords_turkishAliasesAndDefaults_normalizesValues(self):
        result = IsYatirimFinancialLoader().build_from_records(
            "tborg",
            [
                {
                    "Dönem Sonu": "2024-06-30",
                    "Net Kâr": "10,5",
                    "Özkaynaklar": "15,0",
                    "Esas Faaliyet Karı": "9,5",
                    "Nakit ve Nakit Benzerleri": "3,5",
                    "Finansal Borçlar": "7,5",
                    "Ödenmiş Sermaye": "50,0",
                }
            ],
        )

        assert result.failures.empty
        assert result.statements.loc[0, "fiscal_year"] == 2024
        assert result.statements.loc[0, "fiscal_period"] == "Q2"
        assert result.statements.loc[0, "shares_outstanding"] == 50.0
        assert sorted(result.items["value"].tolist()) == [3.5, 7.5, 9.5, 10.5, 15.0]

    def test_buildFromRecords_missingPeriodOrCoreItems_returnsFailures(self):
        result = IsYatirimFinancialLoader().build_from_records(
            "afyon",
            [
                {"net_income": 1, "equity": 2, "operating_profit": 3},
                {"period_end": "2024-09-30", "equity": 2, "operating_profit": 3},
            ],
        )

        assert result.statements.empty
        assert result.items.empty
        assert result.failures["reason"].tolist() == ["missing_period_end", "missing_core_items"]

    def test_buildFromRecords_coercionHelpers_coverOptionalBranches(self):
        result = IsYatirimFinancialLoader().build_from_records(
            "segmn",
            [
                {
                    "period_end": pd.Timestamp("2024-12-31"),
                    "fiscal_year": "2024",
                    "fiscal_period": "FY",
                    "created_at": "2025-01-15T10:30:00+03:00",
                    "announcement_date": pd.NaT,
                    "announcement_datetime": pd.NaT,
                    "is_consolidated": "yes",
                    "is_revised": "0",
                    "net_income": 11,
                    "equity": 22,
                    "operating_profit": 33,
                    "cash": pd.NA,
                    "total_debt": "invalid",
                    "shares_outstanding": 44,
                }
            ],
        )

        assert result.failures.empty
        assert result.statements.loc[0, "fiscal_period"] == "FY"
        assert result.statements.loc[0, "is_consolidated"] == True
        assert result.statements.loc[0, "is_revised"] == False
        assert str(result.statements.loc[0, "created_at"]) == "2025-01-15 07:30:00+00:00"
        assert result.items["item_code"].tolist() == ["net_income", "equity", "operating_profit"]

    def test_buildFromRecords_invalidDateTimeAndEmptyValues_skipOptionalFields(self):
        result = IsYatirimFinancialLoader().build_from_records(
            "ayes",
            [
                {
                    "period_end": "2024-03-31",
                    "announcement_date": "invalid-date",
                    "announcement_datetime": "invalid-datetime",
                    "shares_announcement_datetime": "invalid-datetime",
                    "statement_type": "",
                    "currency": "",
                    "is_consolidated": False,
                    "is_revised": False,
                    "net_income": "5,0",
                    "equity": "6,0",
                    "operating_profit": "7,0",
                    "cash": "",
                    "total_debt": float("nan"),
                    "shares_outstanding": "8,0",
                }
            ],
        )

        assert result.failures.empty
        assert pd.isna(result.statements.loc[0, "announcement_datetime"])
        assert pd.isna(result.statements.loc[0, "announcement_date"])
        assert pd.isna(result.statements.loc[0, "shares_announcement_datetime"])
        assert result.statements.loc[0, "statement_type"] == "financial_statement"
        assert result.statements.loc[0, "currency"] == "TRY"
        assert result.items["item_code"].tolist() == ["net_income", "equity", "operating_profit"]

    def test_buildFromRecords_nanAndBlankNumericValues_areIgnored(self):
        result = IsYatirimFinancialLoader().build_from_records(
            "sayas",
            [
                {
                    "period_end": "2024-03-31",
                    "net_income": float("nan"),
                    "equity": "6,0",
                    "operating_profit": "7,0",
                },
                {
                    "period_end": "2024-06-30",
                    "net_income": "5,0",
                    "equity": "6,0",
                    "operating_profit": "7,0",
                    "cash": " ",
                },
            ],
        )

        assert result.failures["reason"].tolist() == ["missing_core_items"]
        assert len(result.statements) == 1
        assert result.statements.loc[0, "period_end"].isoformat() == "2024-06-30"
        assert result.items["item_code"].tolist() == ["net_income", "equity", "operating_profit"]

    def test_buildFromRecords_stringNan_hitsParsedNanBranch(self):
        result = IsYatirimFinancialLoader().build_from_records(
            "tborg",
            [
                {
                    "period_end": "2024-03-31",
                    "net_income": "nan",
                    "equity": "6,0",
                    "operating_profit": "7,0",
                }
            ],
        )

        assert result.statements.empty
        assert result.failures["reason"].tolist() == ["missing_core_items"]

    def test_buildFromRecords_invalidFloatValue_hitsTypeErrorBranch(self):
        result = IsYatirimFinancialLoader().build_from_records(
            "aksa",
            [
                {
                    "period_end": "2024-03-31",
                    "net_income": object(),
                    "equity": "6,0",
                    "operating_profit": "7,0",
                }
            ],
        )

        assert result.statements.empty
        assert result.failures["reason"].tolist() == ["missing_core_items"]
