from __future__ import annotations

import io
import zipfile
from datetime import date

import pytest

from bist_factor_backtest.data.kap_loader import (
    KapFinancialLoader,
    _decode_zip_text_files,
    _extract_attachment_urls,
    _extract_financial_report_indexes,
    _looks_like_zip,
    _parse_export_excel_metadata,
)
from bist_factor_backtest.data.kap_xbrl import ParsedFinancialReport


class _FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200, headers: dict | None = None):
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}
        self.text = content.decode("utf-8", errors="ignore")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class _FakeCompany:
    company_id = "company-id-1"

    def get_historical_disclosure_list(self, **kwargs):
        raise RuntimeError("primary down")


class TestParseExportExcelMetadata:
    def test_parseExportExcelMetadata_validExportContent_returnsExpectedMetadata(self):
        export_html = """
        <div>Gönderim Tarihi:05.11.2024 20:41:37</div>
        <div>Bildirim Tipi:FR</div>
        <div>Yıl:2024</div>
        <div>Periyot:3</div>
        <table>
          <tr><td>Finansal Tablo Niteliği</td><td>Konsolide</td></tr>
        </table>
        <div>Cari Dönem<br>30.09.2024</div>
        """
        expected_announcement = "2024-11-05 20:41:37"
        expected_period_end = date(2024, 9, 30)

        result = _parse_export_excel_metadata(export_html)

        assert result["announcement_datetime"].strftime("%Y-%m-%d %H:%M:%S") == expected_announcement
        assert result["period_end"] == expected_period_end
        assert result["fiscal_year"] == 2024
        assert result["fiscal_period"] == "Q3"
        assert result["disclosure_type"] == "FR"
        assert result["statement_type"] == "Konsolide"


class TestKapFinancialLoaderFallback:
    def test_fetchDisclosuresWithRetry_searchPageReturnsData_returnsSearchDisclosures(self, monkeypatch):
        loader = KapFinancialLoader(max_retries=1, backoff_seconds=0.0)
        search_disclosures = [{"disclosureIndex": 123, "publishDateTime": "2024-11-05T20:41:37"}]

        def fake_search(company_id, symbol, start_date, end_date):
            return search_disclosures

        monkeypatch.setattr(loader, "_fetch_disclosures_from_search_page", fake_search)
        monkeypatch.setattr(loader, "_fetch_disclosures_from_file_by_year", lambda company_id, symbol, start_date, end_date: [])

        result = loader._fetch_disclosures_with_retry(_FakeCompany(), "ACSEL", date(2024, 1, 1), date(2024, 12, 31))

        assert result == search_disclosures

    def test_fetchAndParseReportWithRetry_cachedReport_returnsCachedValue(self):
        loader = KapFinancialLoader(max_retries=1, backoff_seconds=0.0)
        expected = ParsedFinancialReport(
            net_income=1.0,
            operating_profit=2.0,
            equity=3.0,
            cash=4.0,
            total_debt=5.0,
            shares_outstanding=6.0,
        )
        loader._parsed_report_cache["999"] = expected

        result = loader._fetch_and_parse_report_with_retry(999)

        assert result == expected

    def test_fetchReportIdsForYear_validZipResponse_returnsUniqueIds(self, monkeypatch):
        loader = KapFinancialLoader(max_retries=1, backoff_seconds=0.0)
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as archive:
            archive.writestr(
                "sample.doc",
                '<div title="https://www.kap.org.tr/tr/Bildirim/111"></div>'
                '<div title="https://www.kap.org.tr/tr/Bildirim/222"></div>'
                '<div title="https://www.kap.org.tr/tr/Bildirim/111"></div>',
            )

        def fake_get(url, timeout):
            return _FakeResponse(content=zip_buffer.getvalue())

        monkeypatch.setattr("bist_factor_backtest.data.kap_loader.requests.get", fake_get)
        expected = ["111", "222"]

        result = loader._fetch_report_ids_for_year("company-id", 2024)

        assert result == expected

    def test_getWithRetry_rateLimitThenSuccess_waitsAndReturnsResponse(self, monkeypatch):
        loader = KapFinancialLoader(max_retries=3, backoff_seconds=0.0, rate_limit_sleep_seconds=1.0)
        responses = [
            _FakeResponse(content=b"limit", status_code=429, headers={"Retry-After": "2"}),
            _FakeResponse(content=b"ok", status_code=200),
        ]
        sleeps = []

        def fake_get(url, timeout):
            return responses.pop(0)

        monkeypatch.setattr("bist_factor_backtest.data.kap_loader.requests.get", fake_get)
        monkeypatch.setattr("bist_factor_backtest.data.kap_loader.time.sleep", lambda seconds: sleeps.append(seconds))
        expected = b"ok"

        result = loader._get_with_retry("https://example.com", "ctx")

        assert result.content == expected
        assert 2.0 in sleeps

    def test_fetchDisclosuresFromFileByYear_frDisclosureInRange_returnsPreparedDisclosure(self, monkeypatch):
        loader = KapFinancialLoader(max_retries=1, backoff_seconds=0.0)
        monkeypatch.setattr(loader, "_fetch_report_ids_for_year", lambda company_id, year: ["123"])
        monkeypatch.setattr(
            loader,
            "_fetch_export_excel_with_retry",
            lambda disclosure_id: """
            <div>Gönderim Tarihi:05.11.2024 20:41:37</div>
            <div>Bildirim Tipi:FR</div>
            <div>Yıl:2024</div>
            <div>Periyot:3</div>
            <table>
              <tr><td>Finansal Tablo Niteliği</td><td>Konsolide</td></tr>
            </table>
            <div>Cari Dönem<br>30.09.2024</div>
            <table>
              <tr class="data-input-row">
                <td>ifrs-full_IssuedCapital</td><td></td><td>Ödenmiş Sermaye</td><td></td><td>100</td>
              </tr>
            </table>
            """,
        )
        expected = 123

        result = loader._fetch_disclosures_from_file_by_year(
            company_id="company-id",
            symbol="ACSEL",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        )

        assert result[0]["disclosureIndex"] == expected
        assert result[0]["periodEndDate"] == "2024-09-30"
        assert result[0]["ruleType"] == "Q3"
        assert result[0]["statementType"] == "Konsolide"
        assert "123" in loader._parsed_report_cache

    def test_fetchDisclosuresFromFileByYear_oneDisclosureFails_continuesWithRemaining(self, monkeypatch):
        loader = KapFinancialLoader(max_retries=1, backoff_seconds=0.0)
        monkeypatch.setattr(loader, "_fetch_report_ids_for_year", lambda company_id, year: ["123", "456"])

        def fake_fetch_export(disclosure_id):
            if disclosure_id == "123":
                raise RuntimeError("429")
            return """
            <div>Gönderim Tarihi:05.11.2024 20:41:37</div>
            <div>Bildirim Tipi:FR</div>
            <div>Yıl:2024</div>
            <div>Periyot:3</div>
            <table>
              <tr><td>Finansal Tablo Niteliği</td><td>Konsolide</td></tr>
            </table>
            <div>Cari Dönem<br>30.09.2024</div>
            <table>
              <tr class="data-input-row">
                <td>ifrs-full_IssuedCapital</td><td></td><td>Ödenmiş Sermaye</td><td></td><td>100</td>
              </tr>
            </table>
            """

        monkeypatch.setattr(loader, "_fetch_export_excel_with_retry", fake_fetch_export)

        result = loader._fetch_disclosures_from_file_by_year(
            company_id="company-id",
            symbol="ACSEL",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        )

        assert len(result) == 1
        assert result[0]["disclosureIndex"] == 456


class TestKapSearchParsing:
    def test_extractFinancialReportIndexes_mixedRows_returnsOnlyTargetSymbolFinancialReports(self):
        search_html = (
            '{"publishDate":"2025-04-29T18:43:00","disclosureIndex":1431134,"stockCode":"FROTO","title":"Finansal Rapor","year":2025,"period":3,"donem":"3 Aylık"}'
            '{"publishDate":"2025-03-01T10:00:00","disclosureIndex":999999,"stockCode":"FROTO","title":"Özel Durum Açıklaması","year":2025,"period":3,"donem":"3 Aylık"}'
            '{"publishDate":"2025-04-29T18:43:00","disclosureIndex":1431134,"stockCode":"FROTO","title":"Finansal Rapor","year":2025,"period":3,"donem":"3 Aylık"}'
            '{"publishDate":"2025-04-29T18:43:00","disclosureIndex":777777,"stockCode":"TOASO","title":"Finansal Rapor","year":2025,"period":3,"donem":"3 Aylık"}'
        )

        result = _extract_financial_report_indexes(search_html, "FROTO")

        assert len(result) == 1
        assert result[0]["disclosure_index"] == 1431134
        assert result[0]["year"] == 2025
        assert result[0]["period"] == 1

    def test_fetchDisclosuresFromSearchPage_validRows_filtersByDateAndBuildsDisclosureShape(self, monkeypatch):
        loader = KapFinancialLoader(max_retries=1, backoff_seconds=0.0)
        html = (
            '{"publishDate":"2025-04-29T18:43:00","disclosureIndex":1431134,"stockCode":"FROTO","title":"Finansal Rapor","year":2025,"period":3,"donem":"3 Aylık"}'
            '{"publishDate":"2023-04-29T18:43:00","disclosureIndex":1212121,"stockCode":"FROTO","title":"Finansal Rapor","year":2023,"period":3,"donem":"3 Aylık"}'
        )

        monkeypatch.setattr(loader, "_get_with_retry", lambda url, context: _FakeResponse(content=html.encode("utf-8")))
        monkeypatch.setattr(loader, "_disclosure_has_financial_tables", lambda disclosure_index: True)

        result = loader._fetch_disclosures_from_search_page(
            company_id="company-id",
            symbol="FROTO",
            start_date=date(2024, 1, 1),
            end_date=date(2025, 12, 31),
        )

        assert len(result) == 1
        assert result[0]["disclosureIndex"] == 1431134
        assert result[0]["year"] == 2025
        assert result[0]["ruleType"] == "Q1"
        assert result[0]["periodEndDate"] == "2025-03-31"

    def test_extractFinancialReportIndexes_jsonPatternMissing_parsesNotificationTableRows(self):
        search_html = """
        <table>
          <tr id="notification14">
            <td><input id="1431134" type="checkbox"/></td>
            <td>29.04.2025</td>
            <td>18:43</td>
            <td>FROTO</td>
            <td>FORD OTOMOTİV SANAYİ A.Ş.</td>
            <td>FR</td>
            <td>Finansal Rapor</td>
            <td>2025</td>
            <td>3 Aylık</td>
          </tr>
          <tr id="notification15">
            <td><input id="1431135" type="checkbox"/></td>
            <td>29.04.2025</td>
            <td>18:45</td>
            <td>FROTO</td>
            <td>FORD OTOMOTİV SANAYİ A.Ş.</td>
            <td>ÖDA</td>
            <td>Özel Durum Açıklaması</td>
            <td>2025</td>
            <td>3 Aylık</td>
          </tr>
        </table>
        """

        result = _extract_financial_report_indexes(search_html, "FROTO")

        assert len(result) == 1
        assert result[0]["disclosure_index"] == 1431134
        assert result[0]["period"] == 1


class TestKapAttachmentFallback:
    def test_extractAttachmentUrls_attachmentLinks_returnsNormalizedUrls(self):
        html = """
        <a href="/tr/api/notification/attachment/123/file.xbrl">x</a>
        <a href="http://www.kap.org.tr/tr/api/notification/attachment/123/archive.zip">y</a>
        """

        result = _extract_attachment_urls(html, "123")

        assert result == [
            "https://www.kap.org.tr/tr/api/notification/attachment/123/archive.zip",
            "https://www.kap.org.tr/tr/api/notification/attachment/123/file.xbrl",
        ]

    def test_decodeZipTextFiles_validArchive_returnsTextFiles(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("a.xbrl", "<root>1</root>")
            archive.writestr("b.txt", "abc")
            archive.writestr("c.bin", b"\x00\x01")

        result = _decode_zip_text_files(buffer.getvalue())

        assert result == ["<root>1</root>", "abc"]
        assert _looks_like_zip(buffer.getvalue()) is True

    def test_fetchAndParseAttachmentReportsWithRetry_xbrlAttachment_returnsParsedCore(self, monkeypatch):
        loader = KapFinancialLoader(max_retries=1, backoff_seconds=0.0)
        html = '<a href="https://www.kap.org.tr/tr/api/notification/attachment/1/file.xbrl">x</a>'

        monkeypatch.setattr(
            loader,
            "_fetch_attachment_texts_with_retry",
            lambda url: [
                "<xbrl><ifrs-full:ProfitLossAttributableToOwnersOfParent>11</ifrs-full:ProfitLossAttributableToOwnersOfParent>"
                "<ifrs-full:ProfitLossFromOperatingActivities>22</ifrs-full:ProfitLossFromOperatingActivities>"
                "<ifrs-full:EquityAttributableToOwnersOfParent>33</ifrs-full:EquityAttributableToOwnersOfParent>"
                "<ifrs-full:IssuedCapital>44</ifrs-full:IssuedCapital></xbrl>"
            ],
        )

        result = loader._fetch_and_parse_attachment_reports_with_retry("123", html)

        assert result is not None
        assert result.net_income == 11.0
        assert result.operating_profit == 22.0
        assert result.equity == 33.0
        assert result.shares_outstanding == 44.0
