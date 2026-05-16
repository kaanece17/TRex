from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from bs4 import BeautifulSoup

from bist_factor_backtest.data.issuer_ir_announcements import (
    FINANCIAL_KEYWORDS,
    IssuerIRAnnouncementsLoader,
    IssuerIRSourceConfig,
    ISSUER_IR_SOURCES,
    _extract_financialreports_published_date,
    _extract_kayse_period_end,
    _looks_like_financial_document,
    _extract_period_end,
    _normalize_document_url,
    _publication_date_within_lag,
    _query_timestamp_to_date,
)


def test_extractPeriodEnd_handlesTurkishMonthNames():
    assert _extract_period_end("2025 Mart Mali Tablolar ve Dipnotlar") == date(2025, 3, 1)
    assert _extract_period_end("2024 Eylül Mali Tablo ve Dipnotlar") == date(2024, 9, 1)
    assert _extract_period_end("31 MART 2023 FİNANSAL RAPORLAR") == date(2023, 3, 1)


def test_extractPeriodEnd_handlesDateFormatsAndYearMonthFormats():
    assert _extract_period_end("Bağımsız Denetim Raporu 31.12.2021") == date(2021, 12, 1)
    assert _extract_period_end("1.Europen SPK Rapor 06.2024") == date(2024, 6, 1)
    assert _extract_period_end("2023 09 Aylık Konsolide Mali Tablo ve Dipnotlar") == date(2023, 9, 1)
    assert _extract_period_end("31_03_2021_mali_tablo_ve_dipnotlar.pdf") == date(2021, 3, 1)
    assert _extract_period_end("2024 Yılı 3 Aylık Bağımsız Denetim Raporu") == date(2024, 3, 1)
    assert _extract_period_end("09 / 2024 Finansal Rapor") == date(2024, 9, 1)
    assert _extract_period_end("Frigopak-Finansal_Rapor-20230930.pdf") == date(2023, 9, 1)
    assert _extract_period_end("FINANSALRAPORLAR-31032021.pdf") == date(2021, 3, 1)
    assert _extract_period_end("2023 Yılı Finansal Tablolar ve Dipnotlar") == date(2023, 12, 1)
    assert _extract_period_end("Brisa_2023_2_Donem_Finansal_Dipnotlar.pdf") == date(2023, 6, 1)
    assert _extract_period_end("2023 1.3 Aylık döneme ilişkin sorumluluk beyanı") == date(2023, 3, 1)
    assert _extract_period_end("2023 Yılı 3.3 Aylık Döneme İlişkin Faaliyet Raporu") == date(2023, 9, 1)


def test_extractPeriodEnd_returnsNoneForNonPeriodText():
    assert _extract_period_end("Kurumsal Yönetim Politikası") is None


def test_publicationDateWithinLag_filtersBulkReuploads():
    assert _publication_date_within_lag(date(2026, 3, 1), date(2026, 5, 8), 120) is True
    assert _publication_date_within_lag(date(2024, 9, 1), date(2025, 4, 3), 120) is False


def test_extractKaysePeriodEnd_handlesSpecialFiscalPeriods():
    assert _extract_kayse_period_end("01.05.2024-31.07.2024 Özel Hesap Dönemi 1. Çeyrek Finansal Tablolar") == date(2024, 3, 1)
    assert _extract_kayse_period_end("01.05.2024-31.10.2024 Özel Hesap Dönemi 2. Çeyrek Finansal Tablolar") == date(2024, 6, 1)
    assert _extract_kayse_period_end("01.05.2024-31.01.2025 Özel Hesap Dönemi 3. Çeyrek Finansal Tablolar") == date(2024, 9, 1)
    assert _extract_kayse_period_end("2024 Yılı Kayseri Şeker Bağımsız Denetim Raporu") == date(2024, 12, 1)


def test_normalizeDocumentUrl_normalizesNfc():
    normalized = _normalize_document_url(
        "https://www.pm.com.tr/Storage/Documents/bağimsiz-denetim-raporu-31-12-2012--014c2.pdf"
    )
    assert "bağimsiz-denetim-raporu" in normalized


def test_normalizeDocumentUrl_stripsSayfaSegmentForAssetLinks():
    normalized = _normalize_document_url(
        "https://rainbowpc.com.tr/sayfa/images/yatirimci/pdfler/yatirimci-iliskileri/finansal-tablolar-30092023.pdf"
    )
    assert normalized == (
        "https://rainbowpc.com.tr/images/yatirimci/pdfler/yatirimci-iliskileri/finansal-tablolar-30092023.pdf"
    )


def test_queryTimestampToDate_readsShopifyTimestamp():
    assert _query_timestamp_to_date("https://cdn.example.com/a.pdf?v=1736958329") == date(2025, 1, 15)


def test_looksLikeFinancialDocument_supportsCustomKeywords():
    assert _looks_like_financial_document("2024 - 3 Aylık Faaliyet Raporu", "https://example.com/a.pdf", FINANCIAL_KEYWORDS + ("faaliyet raporu",))


def test_parseHtml_extractsRecordsAndUsesPublicationDate(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    monkeypatch.setattr(loader, "_resolve_publication_date", lambda *_, **__: date(2024, 8, 15))
    html = """
    <html><body>
      <a href="/documents/2024-haziran-mali-tablo-ve-dipnotlar.pdf">2024 Haziran Mali Tablo ve Dipnotlar</a>
      <a href="/documents/politika.pdf">Kurumsal Politika</a>
    </body></html>
    """

    records = loader.parse_html("BESLR", html, "https://www.besler.com.tr/tr/yatirimci-iliskileri/mali-tablolar")

    assert records == [
        {
            "symbol": "BESLR",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 8, 15),
            "announcement_source_url": "https://www.besler.com.tr/documents/2024-haziran-mali-tablo-ve-dipnotlar.pdf",
        }
    ]


def test_parseHtml_usesParentContextWhenAnchorTextIsOnlyPdf(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    monkeypatch.setattr(loader, "_resolve_publication_date", lambda *_, **__: date(2024, 11, 12))
    html = """
    <html><body>
      <div>2024 09 Aylık Konsolide Mali Tablo ve Dipnotlar <a href="/cms/uploads/files/mali_tablo_1234.pdf">PDF</a></div>
    </body></html>
    """

    records = loader.parse_html("CEMAS", html, "https://cemas.com.tr/yatirimci.php?lang=tr&p=mali-tablolar")

    assert records == [
        {
            "symbol": "CEMAS",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 12),
            "announcement_source_url": "https://cemas.com.tr/cms/uploads/files/mali_tablo_1234.pdf",
        }
    ]


def test_parseHtml_usesAncestorContextWhenAnchorTextIsDownload(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    monkeypatch.setattr(loader, "_resolve_publication_date", lambda *_, **__: date(2024, 11, 21))
    html = """
    <html><body>
      <section>
        <div><p>09 / 2024 Finansal Rapor</p></div>
        <div><a href="https://example.com/report.pdf">Download</a></div>
      </section>
    </body></html>
    """

    records = loader.parse_html("IZINV", html, "https://www.izyatirimholding.com/financialdata?lang=tr")

    assert records == [
        {
            "symbol": "IZINV",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 21),
            "announcement_source_url": "https://example.com/report.pdf",
        }
    ]


def test_parseHtml_prefersSameParentContextWhenSpecific(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    monkeypatch.setattr(loader, "_resolve_publication_date", lambda *_, **__: date(2024, 8, 15))
    html = """
    <html><body>
      <div>2024 06 Aylık Konsolide Mali Tablo ve Dipnotlar <a href="/broken.pdf">PDF</a></div>
      <div>2024 03 Aylık Konsolide Mali Tablo ve Dipnotlar <a href="/good.pdf">PDF</a></div>
    </body></html>
    """

    records = loader.parse_html("CEMAS", html, "https://cemas.com.tr/yatirimci.php?lang=tr&p=mali-tablolar")

    assert records[1]["period_end"] == date(2024, 3, 1)


def test_fetchRecords_prefersEarliestAnnouncementDateForDuplicatePeriods(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    monkeypatch.setattr(loader, "_request_text", lambda *_, **__: "<html></html>")

    def fake_parse_html(symbol: str, html: str, source_url: str, verify_ssl: bool = True):
        return [
            {
                "symbol": symbol,
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 24),
                "announcement_source_url": "https://example.com/faaliyet.pdf",
            },
            {
                "symbol": symbol,
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 11, 19),
                "announcement_source_url": "https://example.com/finansal.pdf",
            },
        ]

    monkeypatch.setattr(loader, "parse_html", fake_parse_html)

    records = loader.fetch_records("RNPOL")

    assert records == [
        {
            "symbol": "RNPOL",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 24),
            "announcement_source_url": "https://example.com/faaliyet.pdf",
        }
    ]


def test_fetchRecords_handlesTmpolOfficialPdfFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("TMPOL")

    assert records == [
        {
            "symbol": "TMPOL",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 5, 10),
            "announcement_source_url": "https://www.temapol.com.tr/images//ContentFiles/Temapol%2031.03.2023%20Konsolide.pdf",
        },
        {
            "symbol": "TMPOL",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 9),
            "announcement_source_url": "https://www.temapol.com.tr/images//ContentFiles/Temapol%2030.09.2023%20Konsolide%20SPK%209.11.pdf",
        },
        {
            "symbol": "TMPOL",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 21),
            "announcement_source_url": "https://www.temapol.com.tr/images//ContentFiles/Temapol%20Konsolide%2031.03.2024.pdf",
        },
        {
            "symbol": "TMPOL",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 30),
            "announcement_source_url": "https://www.temapol.com.tr/images//ContentFiles/Temapol%2030%20Haziran%202024%20Ba%C4%9F%C4%B1ms%C4%B1z%20Denetim%20Raporu.pdf",
        },
    ]


def test_fetchRecords_handlesNibasOfficialPdfFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("NIBAS")

    assert records == [
        {
            "symbol": "NIBAS",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 4, 28),
            "announcement_source_url": "https://www.nigbas.com.tr/cms/uploads/files/mali_tablo_1220.pdf",
        },
        {
            "symbol": "NIBAS",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 8),
            "announcement_source_url": "https://www.nigbas.com.tr/cms/uploads/files/mali_tablo_2647.pdf",
        },
        {
            "symbol": "NIBAS",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 26),
            "announcement_source_url": "https://www.nigbas.com.tr/cms/uploads/files/mali_tablo_2942.pdf",
        },
    ]


def test_fetchRecords_handlesTezolFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()
    records = loader.fetch_records("TEZOL")

    assert records == [
        {
            "symbol": "TEZOL",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 5, 10),
            "announcement_source_url": "https://financialreports.eu/filings/europap-tezol-kagit-sanayi-ve-ticaret-as/report-publication-announcement/2023/6736489/",
        },
        {
            "symbol": "TEZOL",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 21),
            "announcement_source_url": "https://financialreports.eu/filings/europap-tezol-kagit-sanayi-ve-ticaret-as/report-publication-announcement/2023/6715156/",
        },
        {
            "symbol": "TEZOL",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 8),
            "announcement_source_url": "https://financialreports.eu/filings/europap-tezol-kagit-sanayi-ve-ticaret-as/report-publication-announcement/2023/6701763/",
        },
        {
            "symbol": "TEZOL",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 9),
            "announcement_source_url": "https://financialreports.eu/filings/europap-tezol-kagit-sanayi-ve-ticaret-as/report-publication-announcement/2024/6663990/",
        },
        {
            "symbol": "TEZOL",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 21),
            "announcement_source_url": "https://financialreports.eu/filings/europap-tezol-kagit-sanayi-ve-ticaret-as/report-publication-announcement/2024/6647614/",
        },
        {
            "symbol": "TEZOL",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 6),
            "announcement_source_url": "https://financialreports.eu/filings/europap-tezol-kagit-sanayi-ve-ticaret-as/report-publication-announcement/2024/6629686/",
        },
        {
            "symbol": "TEZOL",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 11),
            "announcement_source_url": "https://financialreports.eu/filings/europap-tezol-kagit-sanayi-ve-ticaret-as/report-publication-announcement/2024/6614783/",
        },
        {
            "symbol": "TEZOL",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 5, 11),
            "announcement_source_url": "https://www.tezol.com.tr/wp-content/uploads/2026/05/EUROPAP-TEZOL-31.03.2026-SPK.pdf",
        },
    ]


def test_fetchRecords_handlesOzysrFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("OZYSR")

    assert records == [
        {
            "symbol": "OZYSR",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 20),
            "announcement_source_url": "https://financialreports.eu/filings/ozyasar-tel/report-publication-announcement/2024/6625377/",
        },
        {
            "symbol": "OZYSR",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 9),
            "announcement_source_url": "https://financialreports.eu/filings/ozyasar-tel/report-publication-announcement/2024/6614996/",
        },
        {
            "symbol": "OZYSR",
            "period_end": date(2024, 12, 1),
            "announcement_date": date(2025, 3, 8),
            "announcement_source_url": "https://financialreports.eu/filings/ozyasar-tel/report-publication-announcement/2025/6588403/",
        },
        {
            "symbol": "OZYSR",
            "period_end": date(2025, 3, 1),
            "announcement_date": date(2025, 5, 9),
            "announcement_source_url": "https://financialreports.eu/filings/ozyasar-tel/report-publication-announcement/2025/6565244/",
        },
    ]


def test_fetchRecords_handlesVangdFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()
    records = loader.fetch_records("VANGD")

    assert records == [
        {
            "symbol": "VANGD",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 9),
            "announcement_source_url": "https://financialreports.eu/filings/vanet-gida-sanayi-ic-ve-dis-ticaret-as/regulatory-filings/2023/6718729/",
        },
        {
            "symbol": "VANGD",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 28),
            "announcement_source_url": "https://financialreports.eu/filings/vanet-gida-sanayi-ic-ve-dis-ticaret-as/regulatory-filings/2023/6704684/",
        },
        {
            "symbol": "VANGD",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 4),
            "announcement_source_url": "https://financialreports.eu/filings/vanet-gida-sanayi-ic-ve-dis-ticaret-as/report-publication-announcement/2024/6616743/",
        },
        {
            "symbol": "VANGD",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 3, 2),
            "announcement_source_url": "https://financialreports.eu/filings/vanet-gida-sanayi-ic-ve-dis-ticaret-as/report-publication-announcement/2026/32865598/",
        },
    ]


def test_fetchRecords_handlesDurdoCandidateFiles(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    pages = {
        "6736358": '<html><head><meta property="article:published_time" content="2023-05-10T17:00:00+03:00"></head><body>2023 1.Dönem Faaliyet Raporu</body></html>',
        "6715801": '<html><head><meta property="article:published_time" content="2023-08-18T17:00:00+03:00"></head><body>2023 2.Dönem Faaliyet Raporu</body></html>',
        "6700937": '<html><head><meta property="article:published_time" content="2023-11-09T17:00:00+03:00"></head><body>2023 3.Dönem Faaliyet Raporu</body></html>',
        "6660090": '<html><head><meta property="article:published_time" content="2024-05-20T17:00:00+03:00"></head><body>2023 4.Dönem Faaliyet Raporu</body></html>',
        "6647738": '<html><head><meta property="article:published_time" content="2024-06-21T17:00:00+03:00"></head><body>2024 1.Dönem Faaliyet Raporu</body></html>',
        "6623625": '<html><head><meta property="article:published_time" content="2024-09-30T17:00:00+03:00"></head><body>2024 2.Dönem Faaliyet Raporu</body></html>',
    }
    publication_dates = {
        "https://www.durukan.com.tr/wp-content/uploads/2024/10/DURUKAN_Faaliyet-Raporu_2024_3.pdf": date(2024, 10, 30),
        "https://www.durukan.com.tr/wp-content/uploads/2026/05/2026-Yili-1.-Ceyrek-Faaliyet-Raporu.pdf": date(2026, 5, 7),
    }

    def fake_request_text(url: str, **_kwargs):
        for key, html in pages.items():
            if key in url:
                return html
        raise AssertionError(url)

    def fake_resolve(url: str, verify_ssl: bool = True):
        if url not in publication_dates:
            raise ValueError(url)
        return publication_dates[url]

    monkeypatch.setattr(loader, "_request_text", fake_request_text)
    monkeypatch.setattr(loader, "_resolve_publication_date", fake_resolve)

    records = sorted(loader.fetch_records("DURDO"), key=lambda item: item["period_end"])

    assert records == [
        {
            "symbol": "DURDO",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 5, 10),
            "announcement_source_url": "https://financialreports.eu/filings/duran-dogan-basim-ve-ambalaj-sanayi-as/report-publication-announcement/2023/6736358/",
        },
        {
            "symbol": "DURDO",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 18),
            "announcement_source_url": "https://financialreports.eu/filings/duran-dogan-basim-ve-ambalaj-sanayi-as/report-publication-announcement/2023/6715801/",
        },
        {
            "symbol": "DURDO",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 9),
            "announcement_source_url": "https://financialreports.eu/filings/duran-dogan-basim-ve-ambalaj-sanayi-as/report-publication-announcement/2023/6700937/",
        },
        {
            "symbol": "DURDO",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 20),
            "announcement_source_url": "https://financialreports.eu/filings/duran-dogan-basim-ve-ambalaj-sanayi-as/report-publication-announcement/2024/6660090/",
        },
        {
            "symbol": "DURDO",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 21),
            "announcement_source_url": "https://financialreports.eu/filings/duran-dogan-basim-ve-ambalaj-sanayi-as/report-publication-announcement/2024/6647738/",
        },
        {
            "symbol": "DURDO",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 30),
            "announcement_source_url": "https://financialreports.eu/filings/duran-dogan-basim-ve-ambalaj-sanayi-as/report-publication-announcement/2024/6623625/",
        },
        {
            "symbol": "DURDO",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 10, 30),
            "announcement_source_url": "https://www.durukan.com.tr/wp-content/uploads/2024/10/DURUKAN_Faaliyet-Raporu_2024_3.pdf",
        },
        {
            "symbol": "DURDO",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 5, 7),
            "announcement_source_url": "https://www.durukan.com.tr/wp-content/uploads/2026/05/2026-Yili-1.-Ceyrek-Faaliyet-Raporu.pdf",
        },
    ]


def test_parseHtml_appliesPublicationLagFilter(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    dates = iter([date(2023, 10, 19), date(2024, 6, 24)])
    monkeypatch.setattr(loader, "_resolve_publication_date", lambda *_, **__: next(dates))
    html = """
    <html><body>
      <a href="/finansal-tablolar-31032023.pdf">Finansal Tablolar 31.03.2023</a>
      <a href="/faaliyet-raporu-31032024.pdf">Faaliyet Raporu 31.03.2024</a>
    </body></html>
    """

    records = loader.parse_html("RNPOL", html, "https://rainbowpc.com.tr/sayfa/raporlar")

    assert records == [
        {
            "symbol": "RNPOL",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 24),
            "announcement_source_url": "https://rainbowpc.com.tr/faaliyet-raporu-31032024.pdf",
        }
    ]


def test_parseHtml_handlesMarblTableRows():
    loader = IssuerIRAnnouncementsLoader()
    html = """
    <table>
      <tr>
        <td>Finansal Rapor Konsolide 2024 - 2. 3 Aylık Bildirim</td>
        <td>23.09.2024</td>
        <td><a href="https://www.marblesystemstureks.com.tr/wp-content/uploads/2024/09/1337024.pdf">İndir</a></td>
      </tr>
      <tr>
        <td>31.12.2024 Finansal Tablolar Ve Bağımsız Denetçi Raporu</td>
        <td>10.03.2025</td>
        <td><a href="https://www.marblesystemstureks.com.tr/wp-content/uploads/2025/03/Tureks-A.S-31.12.2024-Bagimsiz-Denetim-Raporu.pdf">İndir</a></td>
      </tr>
    </table>
    """

    records = loader.parse_html(
        "MARBL",
        html,
        "https://www.marblesystemstureks.com.tr/yatirimci-iliskileri/finansal-tablolar/",
    )

    assert records == [
        {
            "symbol": "MARBL",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 23),
            "announcement_source_url": "https://www.marblesystemstureks.com.tr/wp-content/uploads/2024/09/1337024.pdf",
        },
        {
            "symbol": "MARBL",
            "period_end": date(2024, 12, 1),
            "announcement_date": date(2025, 3, 10),
            "announcement_source_url": "https://www.marblesystemstureks.com.tr/wp-content/uploads/2025/03/Tureks-A.S-31.12.2024-Bagimsiz-Denetim-Raporu.pdf",
        },
    ]


def test_parseHtml_handlesSekurFinancialLinks(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    publication_dates = iter(
        [
            date(2024, 6, 20),
            date(2024, 10, 1),
        ]
    )
    monkeypatch.setattr(loader, "_resolve_publication_date", lambda *_, **__: next(publication_dates))
    html = """
    <html><body>
      <a href="/uploads/31.03.2024-finansal-dipnotlari.pdf">31.03.2024 finansal dipnotlari</a>
      <a href="/uploads/30.06.2024-finansal-dipnotlari.pdf">30.06.2024 finansal dipnotlari</a>
    </body></html>
    """

    records = loader.parse_html("SEKUR", html, "https://www.sekuro.com.tr/tr/yatirimci-iliskileri")

    assert records == [
        {
            "symbol": "SEKUR",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 20),
            "announcement_source_url": "https://www.sekuro.com.tr/uploads/31.03.2024-finansal-dipnotlari.pdf",
        },
        {
            "symbol": "SEKUR",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 10, 1),
            "announcement_source_url": "https://www.sekuro.com.tr/uploads/30.06.2024-finansal-dipnotlari.pdf",
        },
    ]


def test_parseHtml_handlesSekurRawHtmlAnchors(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    publication_dates = iter(
        [
            date(2024, 11, 12),
            date(2025, 2, 28),
        ]
    )
    monkeypatch.setattr(loader, "_resolve_publication_date", lambda *_, **__: next(publication_dates))
    html = """
    <div class="col-sm-6 in-item">
      <a href="/uploads/30.09.2024-finansal-dipnotlari.pdf" target="_blank">
        <img src="/tema/img/file-ikon.png" />
        <span>30.09.2024 Finansal Dipnotları</span>
      </a>
    </div>
    <div class="col-sm-6 in-item">
      <a href="/uploads/31.12.2024-bagimsiz-denetim-raporu.pdf" target="_blank">
        <img src="/tema/img/file-ikon.png" />
        <span>31.12.2024 Bağımsız Denetim Raporu</span>
      </a>
    </div>
    """

    records = loader.parse_html("SEKUR", html, "https://www.sekuro.com.tr/tr/yatirimci-iliskileri")

    assert records == [
        {
            "symbol": "SEKUR",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 12),
            "announcement_source_url": "https://www.sekuro.com.tr/uploads/30.09.2024-finansal-dipnotlari.pdf",
        },
        {
            "symbol": "SEKUR",
            "period_end": date(2024, 12, 1),
            "announcement_date": date(2025, 2, 28),
            "announcement_source_url": "https://www.sekuro.com.tr/uploads/31.12.2024-bagimsiz-denetim-raporu.pdf",
        },
    ]


def test_parseHtml_handlesSanfmInvestorPageLinks(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    publication_dates = iter(
        [
            date(2024, 8, 16),
            date(2024, 11, 11),
        ]
    )
    monkeypatch.setattr(loader, "_resolve_publication_date", lambda *_, **__: next(publication_dates))
    html = """
    <li><a href="/yatirimci-iliskileri-ek/2024-sanifoam_kons_30-06-2024.pdf"><strong>01.01.2024 – 30.06.2024 Bağımsız Denetim Raporu</strong></a></li>
    <li><a href="/yatirimci-iliskileri-ek/2024-sanifoam-2024-3-donem-faaliyet-raporu.pdf"><strong>01.01.2024 – 30.09.2024 Faaliyet Raporu</strong></a></li>
    """

    records = loader.parse_html("SANFM", html, "https://www.sanifoam.com.tr/yatirimci-iliskileri")

    assert records == [
        {
            "symbol": "SANFM",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 8, 16),
            "announcement_source_url": "https://www.sanifoam.com.tr/yatirimci-iliskileri-ek/2024-sanifoam_kons_30-06-2024.pdf",
        },
        {
            "symbol": "SANFM",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 11),
            "announcement_source_url": "https://www.sanifoam.com.tr/yatirimci-iliskileri-ek/2024-sanifoam-2024-3-donem-faaliyet-raporu.pdf",
        },
    ]


def test_fetchRecords_handlesSafkrDisclosureApi(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    payload = {
        "data": {
            "investorRelations": [
                {
                    "title": "Özel Durum Açıklamaları",
                    "items": [
                        {
                            "title": "30.06.2024 Faaliyet Raporu",
                            "url": "https://www.kap.org.tr/tr/Bildirim/1331662",
                            "date": "2024-09-06T00:00:00.000Z",
                        },
                        {
                            "title": "Safkar Ege Soğutmacılık 30.06.2024 Konsolide Mali Tablo",
                            "url": "https://www.kap.org.tr/tr/Bildirim/1331661",
                            "date": "2024-09-06T00:00:00.000Z",
                        },
                        {
                            "title": "Finansal Rapor",
                            "url": "https://www.kap.org.tr/tr/Bildirim/1114481",
                            "date": "2023-02-16T00:00:00.000Z",
                        },
                        {
                            "title": "Faaliyet Raporu",
                            "url": "https://www.kap.org.tr/tr/Bildirim/1114482",
                            "date": "2023-02-16T00:00:00.000Z",
                        },
                        {
                            "title": "Safkar Ege Soğutmacılık 31.12.2022 Konsolide Mali Tablo",
                            "url": "https://www.kap.org.tr/tr/Bildirim/1114480",
                            "date": "2023-02-16T00:00:00.000Z",
                        },
                    ],
                }
            ]
        }
    }

    class Response:
        def json(self):
            return payload

    monkeypatch.setattr(loader, "_request", lambda *args, **kwargs: Response())

    records = sorted(loader.fetch_records("SAFKR"), key=lambda item: item["period_end"])

    assert records == [
        {
            "symbol": "SAFKR",
            "period_end": date(2022, 12, 1),
            "announcement_date": date(2023, 2, 16),
            "announcement_source_url": "https://www.kap.org.tr/tr/Bildirim/1114480",
        },
        {
            "symbol": "SAFKR",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 6),
            "announcement_source_url": "https://www.kap.org.tr/tr/Bildirim/1331662",
        },
    ]


def test_fetchRecords_handlesOzrdnFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = sorted(loader.fetch_records("OZRDN"), key=lambda item: item["period_end"])

    assert records == [
        {
            "symbol": "OZRDN",
            "period_end": date(2020, 3, 1),
            "announcement_date": date(2020, 5, 27),
            "announcement_source_url": "https://financialreports.eu/filings/ozerden-ambalaj-sanayi-as/regulatory-filings/2020/6938454/",
        },
        {
            "symbol": "OZRDN",
            "period_end": date(2020, 9, 1),
            "announcement_date": date(2020, 11, 4),
            "announcement_source_url": "https://financialreports.eu/filings/ozerden-ambalaj-sanayi-as/report-publication-announcement/2020/6915323/",
        },
    ]


def test_fetchRecords_handlesHatekCandidateFiles(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    publication_dates = {
        "https://www.hateks.com.tr/pdf/31-03-2023-BAGIMSIZ-DENETIM-RAPORU.pdf": date(2023, 5, 22),
        "https://www.hateks.com.tr/pdf/30-06-2023-BAGIMSIZ-DENETIM-RAPORU.pdf": date(2024, 5, 9),
        "https://www.hateks.com.tr/pdf/31-12-2023-BAGIMSIZ-DENETIM-RAPORU.pdf": date(2024, 5, 9),
    }

    def fake_resolve(url: str, verify_ssl: bool = True):
        if url not in publication_dates:
            raise ValueError(url)
        return publication_dates[url]

    def fake_request_text(url: str, **_kwargs):
        raise AssertionError(url)

    monkeypatch.setattr(loader, "_resolve_publication_date", fake_resolve)
    monkeypatch.setattr(loader, "_request_text", fake_request_text)

    records = sorted(loader.fetch_records("HATEK"), key=lambda item: item["period_end"])

    assert records == [
        {
            "symbol": "HATEK",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 5, 22),
            "announcement_source_url": "https://www.hateks.com.tr/pdf/31-03-2023-BAGIMSIZ-DENETIM-RAPORU.pdf",
        },
        {
            "symbol": "HATEK",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 9),
            "announcement_source_url": "https://www.hateks.com.tr/pdf/31-12-2023-BAGIMSIZ-DENETIM-RAPORU.pdf",
        },
    ]


def test_parseHtml_handlesRtalbDisclosureCards():
    loader = IssuerIRAnnouncementsLoader()
    html = """
    <div>
      <h6>29.04.2024 - 31.03.2024 Finansal Rapor</h6>
      <a href="https://www.kap.org.tr/tr/Bildirim/123">Detay</a>
    </div>
    <div>
      <h6>08.08.2025 - 30.06.2025 Finansal Rapor</h6>
      <a href="https://www.kap.org.tr/tr/Bildirim/456">Detay</a>
    </div>
    """

    records = loader.parse_html(
        "RTALB",
        html,
        "https://www.rtalabs.com.tr/yatirimci-iliskileri/ozel-durum-aciklamalari",
    )

    assert records == [
        {
            "symbol": "RTALB",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 4, 29),
            "announcement_source_url": "https://www.kap.org.tr/tr/Bildirim/123",
        },
        {
            "symbol": "RTALB",
            "period_end": date(2025, 6, 1),
            "announcement_date": date(2025, 8, 8),
            "announcement_source_url": "https://www.kap.org.tr/tr/Bildirim/456",
        },
    ]


def test_parseHtml_handlesIzinvSequentialDownloadBlocks(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    monkeypatch.setattr(loader, "_resolve_publication_date", lambda *_, **__: date(2024, 11, 21))
    html = """
    <div>09 / 2024 Finansal Rapor</div>
    <div><a href="https://www.izyatirimholding.com/_files/ugd/a.pdf">Download</a></div>
    <div>06 / 2024 Finansal Rapor</div>
    <div><a href="https://www.izyatirimholding.com/_files/ugd/b.pdf">Download</a></div>
    """

    records = loader.parse_html("IZINV", html, "https://www.izyatirimholding.com/financialdata?lang=tr")

    assert records == [
        {
            "symbol": "IZINV",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 21),
            "announcement_source_url": "https://www.izyatirimholding.com/_files/ugd/a.pdf",
        },
        {
            "symbol": "IZINV",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 11, 21),
            "announcement_source_url": "https://www.izyatirimholding.com/_files/ugd/b.pdf",
        },
    ]


def test_parseHtml_handlesFadeFinancialTablesSection(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    monkeypatch.setattr(loader, "_resolve_publication_date", lambda *_, **__: date(2024, 11, 12))
    html = """
    <div>
      <span>Finansal Tablolar</span>
      <ul>
        <li><a href="https://drive.google.com/file/d/a/view?usp=sharing">30.09.2024</a></li>
        <li><a href="https://drive.google.com/file/d/b/view?usp=sharing">30.06.2024</a></li>
      </ul>
      <span>Faaliyet Raporları</span>
      <ul>
        <li><a href="https://drive.google.com/file/d/c/view?usp=sharing">30.09.2024</a></li>
      </ul>
    </div>
    """

    records = loader.parse_html("FADE", html, "https://www.fadegida.com.tr/yatirimci.html")

    assert records == [
        {
            "symbol": "FADE",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 12),
            "announcement_source_url": "https://drive.google.com/file/d/a/view?usp=sharing",
        },
        {
            "symbol": "FADE",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 11, 12),
            "announcement_source_url": "https://drive.google.com/file/d/b/view?usp=sharing",
        },
    ]


def test_parseHtml_skipsBrokenDocumentUrls(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()

    def fake_resolve(url: str, *_args, **_kwargs):
        if "broken" in url:
            raise RuntimeError("boom")
        return date(2024, 8, 15)

    monkeypatch.setattr(loader, "_resolve_publication_date", fake_resolve)
    html = """
    <html><body>
      <div>2024 06 Aylık Konsolide Mali Tablo ve Dipnotlar <a href="/broken.pdf">PDF</a></div>
      <div>2024 03 Aylık Konsolide Mali Tablo ve Dipnotlar <a href="/good.pdf">PDF</a></div>
    </body></html>
    """

    records = loader.parse_html("CEMAS", html, "https://cemas.com.tr/yatirimci.php?lang=tr&p=mali-tablolar")

    assert records == [
        {
            "symbol": "CEMAS",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 8, 15),
            "announcement_source_url": "https://cemas.com.tr/good.pdf",
        }
    ]


def test_parseHtml_handlesDitasQuarterRangeLabels(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    monkeypatch.setattr(loader, "_resolve_publication_date", lambda *_, **__: date(2025, 5, 13))
    html = """
    <html><body>
      <a href="/uploads/ditas-31-03-2025-faaliyet-raporu.pdf">01 Ocak - 31 Mart 1. Çeyrek</a>
    </body></html>
    """

    records = loader.parse_html("DITAS", html, "https://www.ditas.com.tr/yatirimci-iliskileri-raporlar-ve-sunumlar")

    assert records == [
        {
            "symbol": "DITAS",
            "period_end": date(2025, 3, 1),
            "announcement_date": date(2025, 5, 13),
            "announcement_source_url": "https://www.ditas.com.tr/uploads/ditas-31-03-2025-faaliyet-raporu.pdf",
        },
    ]


def test_parseHtml_handlesBmschQuarterlyFinancialReports(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    monkeypatch.setattr(loader, "_resolve_publication_date", lambda *_, **__: date(2024, 6, 14))
    html = """
    <html><body>
      <a href="https://www.bmstel.com.tr/wp-content/uploads/2023/06/BMS_Birlesik-Metal-31.03.2023-YK-Faaliyet-Raporu.pdf">
        BMS Tel SPK Raporu 31.03.2023
      </a>
    </body></html>
    """

    records = loader.parse_html("BMSCH", html, "https://www.bmstel.com.tr/mali-tablolar/")

    assert records == [
        {
            "symbol": "BMSCH",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2024, 6, 14),
            "announcement_source_url": "https://www.bmstel.com.tr/wp-content/uploads/2023/06/BMS_Birlesik-Metal-31.03.2023-YK-Faaliyet-Raporu.pdf",
        },
    ]


def test_fetchRecords_handlesBmschFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("BMSCH")

    assert records == [
        {
            "symbol": "BMSCH",
            "period_end": date(2022, 3, 1),
            "announcement_date": date(2022, 5, 16),
            "announcement_source_url": "https://financialreports.eu/filings/bms-birlesik-metal-sanayi-ve-ticaret-as/interim-quarterly-report/2022/6808211/",
        },
        {
            "symbol": "BMSCH",
            "period_end": date(2022, 6, 1),
            "announcement_date": date(2022, 8, 8),
            "announcement_source_url": "https://financialreports.eu/filings/bms-birlesik-metal-sanayi-ve-ticaret-as/interim-quarterly-report/2022/6795474/",
        },
        {
            "symbol": "BMSCH",
            "period_end": date(2022, 9, 1),
            "announcement_date": date(2022, 10, 28),
            "announcement_source_url": "https://financialreports.eu/filings/bms-birlesik-metal-sanayi-ve-ticaret-as/interim-quarterly-report/2022/6783017/",
        },
    ]


def test_fetchRecords_handlesKayseVisiblePublicationDates(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    html = """
    <div class="item">
      <a href="/Site/YiBelge/a.pdf">
        <div class="title">01.05.2024-31.07.2024 Özel Hesap Dönemi 1. Çeyrek Finansal Tablolar</div>
        <div class="date">18.10.2024</div>
      </a>
    </div>
    <div class="item">
      <a href="/Site/YiBelge/b.pdf">
        <div class="title">2024 Yılı Kayseri Şeker Bağımsız Denetim Raporu</div>
        <div class="date">01.08.2025</div>
      </a>
    </div>
    """
    monkeypatch.setattr(loader, "_request_text", lambda *_args, **_kwargs: html)

    records = loader.fetch_records("KAYSE")

    assert records == [
        {
            "symbol": "KAYSE",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 10, 18),
            "announcement_source_url": "https://www.kayseriseker.com.tr/Site/YiBelge/a.pdf",
        },
        {
            "symbol": "KAYSE",
            "period_end": date(2024, 12, 1),
            "announcement_date": date(2025, 8, 1),
            "announcement_source_url": "https://www.kayseriseker.com.tr/Site/YiBelge/b.pdf",
        },
    ]


def test_fetchRecords_handlesIzinvFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("IZINV")

    assert records == [
        {
            "symbol": "IZINV",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 2),
            "announcement_source_url": "https://financialreports.eu/filings/iz-yatirim-holding-as/report-publication-announcement/2023/6721312/",
        },
        {
            "symbol": "IZINV",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/iz-yatirim-holding-as/report-publication-announcement/2023/6704175/",
        },
        {
            "symbol": "IZINV",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 16),
            "announcement_source_url": "https://financialreports.eu/filings/iz-yatirim-holding-as/report-publication-announcement/2024/6661309/",
        },
        {
            "symbol": "IZINV",
            "period_end": date(2025, 3, 1),
            "announcement_date": date(2025, 6, 11),
            "announcement_source_url": "https://financialreports.eu/filings/iz-yatirim-holding-as/report-publication-announcement/2025/6556852/",
        },
        {
            "symbol": "IZINV",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 5, 12),
            "announcement_source_url": "https://financialreports.eu/filings/iz-yatirim-holding-as/report-publication-announcement/2026/45333805/",
        },
    ]


def test_fetchRecords_handlesMarblHybridFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("MARBL")

    assert records == [
        {
            "symbol": "MARBL",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 23),
            "announcement_source_url": "https://www.marblesystemstureks.com.tr/wp-content/uploads/2023/11/TUREKS-KONSOL_DE-30.09.2023-DIPNOT.pdf",
        },
        {
            "symbol": "MARBL",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 4, 9),
            "announcement_source_url": "https://www.marblesystemstureks.com.tr/wp-content/uploads/2024/04/TUREKS-A._.-31.12.2023-Ba__ms_z-Denetim-Raporu.pdf",
        },
        {
            "symbol": "MARBL",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 12),
            "announcement_source_url": "https://www.marblesystemstureks.com.tr/wp-content/uploads/2024/07/1298683.pdf",
        },
        {
            "symbol": "MARBL",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 23),
            "announcement_source_url": "https://www.marblesystemstureks.com.tr/wp-content/uploads/2024/09/1337024.pdf",
        },
        {
            "symbol": "MARBL",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 9),
            "announcement_source_url": "https://www.marblesystemstureks.com.tr/wp-content/uploads/2024/11/1356148.pdf",
        },
        {
            "symbol": "MARBL",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 5, 15),
            "announcement_source_url": "https://financialreports.eu/filings/tureks-turunc-madencilik-ic-ve-dis-ticaret-as/interim-quarterly-report/2026/46358097/",
        },
    ]


def test_fetchRecords_handlesGerelFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("GEREL")

    assert records == [
        {
            "symbol": "GEREL",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 16),
            "announcement_source_url": "https://financialreports.eu/filings/6716635/content/",
        },
        {
            "symbol": "GEREL",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 9),
            "announcement_source_url": "https://financialreports.eu/filings/gersan-elektrik-ticaret-ve-sanayi-as/interim-quarterly-report/2023/6700805/",
        },
        {
            "symbol": "GEREL",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 4, 4),
            "announcement_source_url": "https://financialreports.eu/filings/6673235/content/",
        },
        {
            "symbol": "GEREL",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 5, 22),
            "announcement_source_url": "https://financialreports.eu/filings/6657725/content/",
        },
        {
            "symbol": "GEREL",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 30),
            "announcement_source_url": "https://financialreports.eu/filings/gersan-elektrik-ticaret-ve-sanayi-as/interim-quarterly-report/2024/6623378/",
        },
        {
            "symbol": "GEREL",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 11),
            "announcement_source_url": "https://financialreports.eu/filings/6614786/content/",
        },
    ]


def test_fetchRecords_handlesGundgFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("GUNDG")

    assert records == [
        {
            "symbol": "GUNDG",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/gundogdu-gida-sut-urunleri-sanayi-ve-dis-ticaret-as/report-publication-announcement/2024/6617920/",
        },
        {
            "symbol": "GUNDG",
            "period_end": date(2024, 12, 1),
            "announcement_date": date(2025, 3, 13),
            "announcement_source_url": "https://financialreports.eu/filings/gundogdu-gida-sut-urunleri-sanayi-ve-dis-ticaret-as/report-publication-announcement/2025/6584826/",
        },
        {
            "symbol": "GUNDG",
            "period_end": date(2025, 3, 1),
            "announcement_date": date(2025, 4, 30),
            "announcement_source_url": "https://financialreports.eu/filings/gundogdu-gida-sut-urunleri-sanayi-ve-dis-ticaret-as/report-publication-announcement/2025/6569025/",
        },
        {
            "symbol": "GUNDG",
            "period_end": date(2025, 6, 1),
            "announcement_date": date(2025, 8, 11),
            "announcement_source_url": "https://financialreports.eu/filings/gundogdu-gida-sut-urunleri-sanayi-ve-dis-ticaret-as/report-publication-announcement/2025/7709601/",
        },
    ]


def test_fetchRecords_handlesSnicaFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("SNICA")

    assert records == [
        {
            "symbol": "SNICA",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 9),
            "announcement_source_url": "https://financialreports.eu/filings/sanica-isi-sanayi-as/report-publication-announcement/2023/6718096/",
        },
        {
            "symbol": "SNICA",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/sanica-isi-sanayi-as/report-publication-announcement/2023/6704663/",
        },
        {
            "symbol": "SNICA",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 4, 15),
            "announcement_source_url": "https://financialreports.eu/filings/sanica-isi-sanayi-as/report-publication-announcement/2024/6671987/",
        },
        {
            "symbol": "SNICA",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 3, 2),
            "announcement_source_url": "https://financialreports.eu/filings/sanica-isi-sanayi-as/report-publication-announcement/2026/32865891/",
        },
    ]


def test_parseHtml_handlesMndrsQuarterlyFinancialReports(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    monkeypatch.setattr(loader, "_resolve_publication_date", lambda *_, **__: date(2023, 5, 12))
    html = """
    <html><body>
      <a href="/download/files/1666132296_2023-03-ara-donem-finansal-tablo-ve-dipnotlar.pdf">
        2023 03 Ara Dönem Finansal Tablolar ve Dipnotlar
      </a>
    </body></html>
    """

    records = loader.parse_html(
        "MNDRS",
        html,
        "https://www.menderes.com/tr/yatirimci-iliskileri/finansal-raporlar/ara-donem-finansal-raporlar",
    )

    assert records == [
        {
            "symbol": "MNDRS",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 5, 12),
            "announcement_source_url": "https://www.menderes.com/download/files/1666132296_2023-03-ara-donem-finansal-tablo-ve-dipnotlar.pdf",
        },
    ]


def test_parseHtml_handlesFrigoOnlyForPreBulkUploadDocuments(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()

    def fake_resolve(url: str, *_args, **_kwargs):
        if "2023/08" in url:
            return date(2023, 8, 29)
        return date(2024, 12, 24)

    monkeypatch.setattr(loader, "_resolve_publication_date", fake_resolve)
    html = """
    <html><body>
      <a href="https://www.frigo-pak.com.tr/wp-content/uploads/2023/08/31-MART-2023-FINANSAL-RAPORLAR.pdf">31 MART 2023 FİNANSAL RAPORLAR</a>
      <a href="https://www.frigo-pak.com.tr/wp-content/uploads/2024/12/Frigopak-Finansal_Rapor-20230930.pdf">30 EYLÜL 2023 FİNANSAL RAPORLAR</a>
    </body></html>
    """

    records = loader.parse_html("FRIGO", html, "https://www.frigo-pak.com.tr/finansal-raporlar/", verify_ssl=False)

    assert records == [
        {
            "symbol": "FRIGO",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 8, 29),
            "announcement_source_url": "https://www.frigo-pak.com.tr/wp-content/uploads/2023/08/31-MART-2023-FINANSAL-RAPORLAR.pdf",
        }
    ]


def test_parseHtml_handlesRuzyeOnlyForReasonablePublicationLag(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()

    def fake_resolve(url: str, *_args, **_kwargs):
        if "2026/05" in url:
            return date(2026, 5, 8)
        return date(2025, 4, 3)

    monkeypatch.setattr(loader, "_resolve_publication_date", fake_resolve)
    html = """
    <html><body>
      <a href="https://ruzymadencilik.com.tr/wp-content/uploads/2026/05/Ruzy-31.03.26-SPK.pdf">Finansal Tablolar 2026/03</a>
      <a href="https://ruzymadencilik.com.tr/wp-content/uploads/2025/04/finansal-tablolar-2024-09.pdf">Finansal Tablolar 2024/09</a>
    </body></html>
    """

    records = loader.parse_html(
        "RUZYE",
        html,
        "https://ruzymadencilik.com.tr/yatirimci-iliskileri/finansal-tablolar-ve-bagimsiz-denetim-raporlari/",
        verify_ssl=False,
    )

    assert records == [
        {
            "symbol": "RUZYE",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 5, 8),
            "announcement_source_url": "https://ruzymadencilik.com.tr/wp-content/uploads/2026/05/Ruzy-31.03.26-SPK.pdf",
        }
    ]


def test_extractFinancialreportsPublishedDate_readsArticleMeta():
    soup = BeautifulSoup(
        '<html><head><meta property="article:published_time" content="2024-09-25T17:54:48+02:00"></head></html>',
        "html.parser",
    )
    assert _extract_financialreports_published_date(soup) == date(2024, 9, 25)


def test_fetchRecords_handlesBvsanFinancialreportsPages(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    pages = {
        "6736472": '<html><head><meta property="article:published_time" content="2023-05-10T17:00:00+03:00"></head><body>2023 1.3 Aylık döneme ilişkin sorumluluk beyanı</body></html>',
        "6716212": '<html><head><meta property="article:published_time" content="2023-08-17T18:31:51+02:00"></head><body>01.01.2023-30.06.2023 dönemine ilişkin</body></html>',
        "6701130": '<html><head><meta property="article:published_time" content="2023-11-09T17:00:00+03:00"></head><body>2023 Yılı 3.3 Aylık Döneme İlişkin Faaliyet Raporu</body></html>',
        "6661390": '<html><head><meta property="article:published_time" content="2024-05-16T18:00:00+03:00"></head><body>01.01.2023-31.12.2023 dönemine ait</body></html>',
        "6647255": '<html><head><meta property="article:published_time" content="2024-06-22T17:05:11+02:00"></head><body>1 OCAK – 31 MART 2024 HESAP DÖNEMİNE AİT</body></html>',
        "6624692": '<html><head><meta property="article:published_time" content="2024-09-25T17:54:48+02:00"></head><body>1 OCAK – 30 HAZİRAN 2024 HESAP DÖNEMİNE AİT</body></html>',
        "6613364": '<html><head><meta property="article:published_time" content="2024-11-13T18:00:00+03:00"></head><body>1 OCAK – 30 EYLÜL 2024 HESAP DÖNEMİNE AİT</body></html>',
        "46106082": '<html><head><meta property="article:published_time" content="2026-05-14T17:00:00+03:00"></head><body>Current Period 31.03.2026 vs Previous Period 31.12.2025</body></html>',
    }

    def fake_request_text(url: str, **_kwargs):
        for key, html in pages.items():
            if key in url:
                return html
        raise AssertionError(url)

    monkeypatch.setattr(loader, "_request_text", fake_request_text)

    records = sorted(loader.fetch_records("BVSAN"), key=lambda row: row["period_end"])

    assert records == [
        {
            "symbol": "BVSAN",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 5, 10),
            "announcement_source_url": "https://financialreports.eu/filings/bulbuloglu-vinc-sanayi-ve-ticaret-as/report-publication-announcement/2023/6736472/",
        },
        {
            "symbol": "BVSAN",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 17),
            "announcement_source_url": "https://financialreports.eu/filings/bulbuloglu-vinc-sanayi-ve-ticaret-as/audit-report-information/2023/6716212/",
        },
        {
            "symbol": "BVSAN",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 9),
            "announcement_source_url": "https://financialreports.eu/filings/bulbuloglu-vinc-sanayi-ve-ticaret-as/report-publication-announcement/2023/6701130/",
        },
        {
            "symbol": "BVSAN",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 16),
            "announcement_source_url": "https://financialreports.eu/filings/6661390/content/",
        },
        {
            "symbol": "BVSAN",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 22),
            "announcement_source_url": "https://financialreports.eu/filings/bulbuloglu-vinc-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6647255/",
        },
        {
            "symbol": "BVSAN",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 25),
            "announcement_source_url": "https://financialreports.eu/filings/6624692/content/",
        },
        {
            "symbol": "BVSAN",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 13),
            "announcement_source_url": "https://financialreports.eu/filings/bulbuloglu-vinc-sanayi-ve-ticaret-as/annual-quarterly-financial-statement/2024/6613364/",
        },
        {
            "symbol": "BVSAN",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 5, 14),
            "announcement_source_url": "https://financialreports.eu/filings/bulbuloglu-vinc-sanayi-ve-ticaret-as/interim-quarterly-report/2026/46106082/",
        },
    ]


def test_fetchRecords_handlesPrkmeFinancialreportsPages(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    pages = {
        "6737052": '<html><head><meta property="article:published_time" content="2023-05-09T17:41:55+02:00"></head><body>2023 1.3 Aylık döneme ilişkin finansal tablo</body></html>',
        "6716852": '<html><head><meta property="article:published_time" content="2023-08-16T20:19:51+02:00"></head><body>1 OCAK - 30 HAZİRAN 2023 ARA HESAP DÖNEMİNE AİT</body></html>',
        "6669363": '<html><head><meta property="article:published_time" content="2023-11-08T17:09:29+01:00"></head><body>1 OCAK - 30 EYLÜL 2023 HESAP DÖNEMİNE AİT</body></html>',
        "6669365": '<html><head><meta property="article:published_time" content="2024-04-25T21:05:55+02:00"></head><body>1 OCAK - 31 ARALIK 2023 HESAP DÖNEMİNE AİT</body></html>',
        "6657867": '<html><head><meta property="article:published_time" content="2024-05-22T14:56:02+02:00"></head><body>1 OCAK - 31 MART 2024 HESAP DÖNEMİNE AİT</body></html>',
        "6628440": '<html><head><meta property="article:published_time" content="2024-09-12T22:57:10+02:00"></head><body>1 OCAK - 30 HAZİRAN 2024 HESAP DÖNEMİNE AİT</body></html>',
        "6615464": '<html><head><meta property="article:published_time" content="2024-11-08T17:09:29+01:00"></head><body>1 OCAK - 30 EYLÜL 2024 ARA HESAP DÖNEMİNE AİT</body></html>',
    }

    def fake_request_text(url: str, **_kwargs):
        for key, html in pages.items():
            if key in url:
                return html
        raise AssertionError(url)

    monkeypatch.setattr(loader, "_request_text", fake_request_text)

    records = sorted(loader.fetch_records("PRKME"), key=lambda row: row["period_end"])

    assert records == [
        {
            "symbol": "PRKME",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 5, 9),
            "announcement_source_url": "https://financialreports.eu/filings/park-elektrik-uretim-madencilik-sanayi-ve-ticaret-as/interim-report/2023/6737052/",
        },
        {
            "symbol": "PRKME",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 16),
            "announcement_source_url": "https://financialreports.eu/filings/park-elektrik-uretim-madencilik-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6716852/",
        },
        {
            "symbol": "PRKME",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 8),
            "announcement_source_url": "https://financialreports.eu/filings/6669363/content/",
        },
        {
            "symbol": "PRKME",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 4, 25),
            "announcement_source_url": "https://financialreports.eu/filings/6669365/content/",
        },
        {
            "symbol": "PRKME",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 5, 22),
            "announcement_source_url": "https://financialreports.eu/filings/6657867/content/",
        },
        {
            "symbol": "PRKME",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 12),
            "announcement_source_url": "https://financialreports.eu/filings/6628440/content/",
        },
        {
            "symbol": "PRKME",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 8),
            "announcement_source_url": "https://financialreports.eu/filings/6615464/content/",
        },
    ]


def test_fetchRecords_combinesRnpolOfficialAndFinancialreportsPages(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    official_html = """
    <html><body>
      <a href="/images/yatirimci/pdfler/yatirimci-iliskileri/30062023-Yonetim-Kurulu-Faaliyet-Raporu.pdf">
        30.06.2023 Yönetim Kurulu Faaliyet Raporu
      </a>
      <a href="/images/yatirimci/pdfler/yatirimci-iliskileri/30092023-yonetim-Kurulu-Faaliyet-Raporu.pdf">
        30.09.2023 Yönetim Kurulu Faaliyet Raporu
      </a>
    </body></html>
    """
    pages = {
        "6755806": '<html><head><meta property="article:published_time" content="2023-03-08T17:00:00+03:00"></head><body>a) 01/01/2022 - 31/12/2022 dönemine ilişkin mali tablolar tarafımızca incelenmiştir.</body></html>',
        "6810965": '<html><head><meta property="article:published_time" content="2022-05-06T17:29:29+02:00"></head><body>Cari Dönem 31.03.2022 Current Period 31.03.2022 Önceki Dönem 31.12.2021</body></html>',
        "6790300": '<html><head><meta property="article:published_time" content="2022-08-31T17:13:02+02:00"></head><body>Financial Statement Year / Period 2022 / 6 Months</body></html>',
        "6782047": '<html><head><meta property="article:published_time" content="2022-11-01T16:30:38+01:00"></head><body>a) 01/01/2022 - 30/09/2022 dönemine ilişkin mali tablolar tarafımızca incelenmiştir.</body></html>',
        "6673138": '<html><head><meta property="article:published_time" content="2024-04-04T17:33:58+02:00"></head><body>Financial Statement Year / Period 2023 / Annual</body></html>',
        "6673766": '<html><head><meta property="article:published_time" content="2024-04-02T15:23:22+02:00"></head><body>31.12.2022-31.12.2023 GELİR TABLOSU</body></html>',
    }

    def fake_request_text(url: str, **_kwargs):
        if "rainbowpc.com.tr" in url:
            return official_html
        for key, html in pages.items():
            if key in url:
                return html
        raise AssertionError(url)

    def fake_resolve_publication_date(url: str, **_kwargs):
        if "30062023" in url:
            return date(2023, 10, 19)
        if "30092023" in url:
            return date(2023, 11, 3)
        raise AssertionError(url)

    monkeypatch.setattr(loader, "_request_text", fake_request_text)
    monkeypatch.setattr(loader, "_resolve_publication_date", fake_resolve_publication_date)

    records = sorted(loader.fetch_records("RNPOL"), key=lambda row: row["period_end"])

    assert records == [
        {
            "symbol": "RNPOL",
            "period_end": date(2022, 3, 1),
            "announcement_date": date(2022, 5, 6),
            "announcement_source_url": "https://financialreports.eu/filings/rainbow-polikarbonat-sanayi-ticaret-as/annual-quarterly-financial-statement/2022/6810965/",
        },
        {
            "symbol": "RNPOL",
            "period_end": date(2022, 6, 1),
            "announcement_date": date(2022, 8, 31),
            "announcement_source_url": "https://financialreports.eu/filings/rainbow-polikarbonat-sanayi-ticaret-as/interim-quarterly-report/2022/6790300/",
        },
        {
            "symbol": "RNPOL",
            "period_end": date(2022, 9, 1),
            "announcement_date": date(2022, 11, 1),
            "announcement_source_url": "https://financialreports.eu/filings/rainbow-polikarbonat-sanayi-ticaret-as/annual-quarterly-financial-statement/2022/6782047/",
        },
        {
            "symbol": "RNPOL",
            "period_end": date(2022, 12, 1),
            "announcement_date": date(2023, 3, 8),
            "announcement_source_url": "https://financialreports.eu/filings/rainbow-polikarbonat-sanayi-ticaret-as/report-publication-announcement/2023/6755806/",
        },
        {
            "symbol": "RNPOL",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 10, 19),
            "announcement_source_url": "https://rainbowpc.com.tr/images/yatirimci/pdfler/yatirimci-iliskileri/30062023-Yonetim-Kurulu-Faaliyet-Raporu.pdf",
        },
        {
            "symbol": "RNPOL",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 3),
            "announcement_source_url": "https://rainbowpc.com.tr/images/yatirimci/pdfler/yatirimci-iliskileri/30092023-yonetim-Kurulu-Faaliyet-Raporu.pdf",
        },
        {
            "symbol": "RNPOL",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 4, 2),
            "announcement_source_url": "https://financialreports.eu/filings/rainbow-polikarbonat-sanayi-ticaret-as/annual-quarterly-financial-statement/2024/6673766/",
        },
    ]


def test_fetchRecords_combinesRuzyeOfficialAndFinancialreportsPages(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    official_html = """
    <html><body>
      <a href="/wp-content/uploads/2025/04/Ruzy_2024_Faaliyet_Raporu.pdf">2024 Faaliyet Raporu</a>
      <a href="/wp-content/uploads/2026/05/Ruzy-31.03.26-SPK.pdf">31.03.2026 Finansal Rapor</a>
    </body></html>
    """
    pages = {
        "6733981": '<html><head><meta property="article:published_time" content="2023-05-18T17:00:00+03:00"></head><body>31.03.2023 Faaliyet Raporu</body></html>',
        "6718283": '<html><head><meta property="article:published_time" content="2023-08-10T17:00:00+03:00"></head><body>01.01.2023-30.06.2023 Hesap Dönemine İlişkin Faaliyet Raporu</body></html>',
        "6703215": '<html><head><meta property="article:published_time" content="2023-11-01T17:00:00+03:00"></head><body>30.09.2023 Faaliyet Raporu</body></html>',
        "6660224": '<html><head><meta property="article:published_time" content="2024-05-19T17:00:00+03:00"></head><body>31.12.2023 Faaliyet Raporu</body></html>',
        "6647891": '<html><head><meta property="article:published_time" content="2024-06-21T17:00:00+03:00"></head><body>Altınyağ 31.03.2024 Faaliyet Raporu</body></html>',
        "6624946": '<html><head><meta property="article:published_time" content="2024-09-24T17:00:00+03:00"></head><body>30.06.2024 Faaliyet Raporu</body></html>',
        "6616196": '<html><head><meta property="article:published_time" content="2024-11-06T17:00:00+03:00"></head><body>30.09.2024 Faaliyet Raporu</body></html>',
    }

    def fake_request_text(url: str, **_kwargs):
        if "ruzymadencilik.com.tr" in url:
            return official_html
        for key, html in pages.items():
            if key in url:
                return html
        raise AssertionError(url)

    def fake_resolve_publication_date(url: str, **_kwargs):
        if "Ruzy_2024_Faaliyet_Raporu.pdf" in url:
            return date(2025, 4, 3)
        if "Ruzy-31.03.26-SPK.pdf" in url:
            return date(2026, 5, 8)
        raise AssertionError(url)

    monkeypatch.setattr(loader, "_request_text", fake_request_text)
    monkeypatch.setattr(loader, "_resolve_publication_date", fake_resolve_publication_date)

    records = sorted(loader.fetch_records("RUZYE"), key=lambda row: row["period_end"])

    assert records == [
        {
            "symbol": "RUZYE",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 5, 18),
            "announcement_source_url": "https://financialreports.eu/filings/ruzy-madencilik-ve-enerji-yatirimlari-sanayi-ve-ticaret-as/report-publication-announcement/2023/6733981/",
        },
        {
            "symbol": "RUZYE",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 10),
            "announcement_source_url": "https://financialreports.eu/filings/ruzy-madencilik-ve-enerji-yatirimlari-sanayi-ve-ticaret-as/report-publication-announcement/2023/6718283/",
        },
        {
            "symbol": "RUZYE",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 1),
            "announcement_source_url": "https://financialreports.eu/filings/ruzy-madencilik-ve-enerji-yatirimlari-sanayi-ve-ticaret-as/report-publication-announcement/2023/6703215/",
        },
        {
            "symbol": "RUZYE",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 19),
            "announcement_source_url": "https://financialreports.eu/filings/6660224/content/",
        },
        {
            "symbol": "RUZYE",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 21),
            "announcement_source_url": "https://financialreports.eu/filings/ruzy-madencilik-ve-enerji-yatirimlari-sanayi-ve-ticaret-as/report-publication-announcement/2024/6647891/",
        },
        {
            "symbol": "RUZYE",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 24),
            "announcement_source_url": "https://financialreports.eu/filings/ruzy-madencilik-ve-enerji-yatirimlari-sanayi-ve-ticaret-as/report-publication-announcement/2024/6624946/",
        },
        {
            "symbol": "RUZYE",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 6),
            "announcement_source_url": "https://financialreports.eu/filings/ruzy-madencilik-ve-enerji-yatirimlari-sanayi-ve-ticaret-as/report-publication-announcement/2024/6616196/",
        },
        {
            "symbol": "RUZYE",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 5, 8),
            "announcement_source_url": "https://ruzymadencilik.com.tr/wp-content/uploads/2026/05/Ruzy-31.03.26-SPK.pdf",
        },
    ]


def test_fetchRecords_combinesHatekOfficialAndFinancialreportsPages(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    pages = {
        "6700875": '<html><head><meta property="article:published_time" content="2023-11-09T17:00:00+03:00"></head><body>01.01.2023 - 30.09.2023 ARA DÖNEM FAALİYET RAPORU</body></html>',
        "6648801": '<html><head><meta property="article:published_time" content="2024-06-14T17:00:00+03:00"></head><body>01.01.2024 - 31.03.2024 ARA DÖNEM FAALİYET RAPORU</body></html>',
        "6623064": '<html><head><meta property="article:published_time" content="2024-09-30T17:00:00+03:00"></head><body>01.01.2024-30.06.2024 tarihleri arasında Finansal Raporlarda dahil olmak üzere toplam 1 adet özel durum açıklaması yapmıştır.</body></html>',
        "6615426": '<html><head><meta property="article:published_time" content="2024-11-08T17:00:00+03:00"></head><body>01.01.09 - 30.09.2024 ARA DÖNEM FAALİYET RAPORU</body></html>',
    }

    def fake_request_text(url: str, **_kwargs):
        for key, html in pages.items():
            if key in url:
                return html
        raise AssertionError(url)

    def fake_resolve_publication_date(url: str, **_kwargs):
        if "31-03-2023-BAGIMSIZ-DENETIM-RAPORU.pdf" in url:
            return date(2023, 5, 22)
        if "31-12-2023-BAGIMSIZ-DENETIM-RAPORU.pdf" in url:
            return date(2024, 5, 9)
        raise AssertionError(url)

    monkeypatch.setattr(loader, "_request_text", fake_request_text)
    monkeypatch.setattr(loader, "_resolve_publication_date", fake_resolve_publication_date)

    records = sorted(loader.fetch_records("HATEK"), key=lambda row: row["period_end"])

    assert records == [
        {
            "symbol": "HATEK",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 5, 22),
            "announcement_source_url": "https://www.hateks.com.tr/pdf/31-03-2023-BAGIMSIZ-DENETIM-RAPORU.pdf",
        },
        {
            "symbol": "HATEK",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 9),
            "announcement_source_url": "https://financialreports.eu/filings/hateks-hatay-tekstil-isletmeleri-as/report-publication-announcement/2023/6700875/",
        },
        {
            "symbol": "HATEK",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 9),
            "announcement_source_url": "https://www.hateks.com.tr/pdf/31-12-2023-BAGIMSIZ-DENETIM-RAPORU.pdf",
        },
        {
            "symbol": "HATEK",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 14),
            "announcement_source_url": "https://financialreports.eu/filings/hateks-hatay-tekstil-isletmeleri-as/report-publication-announcement/2024/6648801/",
        },
        {
            "symbol": "HATEK",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 30),
            "announcement_source_url": "https://financialreports.eu/filings/hateks-hatay-tekstil-isletmeleri-as/interim-quarterly-report/2024/6623064/",
        },
        {
            "symbol": "HATEK",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 8),
            "announcement_source_url": "https://financialreports.eu/filings/hateks-hatay-tekstil-isletmeleri-as/report-publication-announcement/2024/6615426/",
        },
    ]


def test_fetchRecords_usesRodrgFinancialreportsFallback(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    pages = {
        "6737731": '<html><head><meta property="article:published_time" content="2023-05-08T17:00:00+03:00"></head><body>Faaliyet raporu 31.03.2023</body></html>',
        "6717589": '<html><head><meta property="article:published_time" content="2023-08-14T17:00:00+03:00"></head><body>01.01.2023-30.06.2023 tarihli konsolide faaliyet raporu ektedir.</body></html>',
        "6702901": '<html><head><meta property="article:published_time" content="2023-11-03T17:00:00+03:00"></head><body>30.09.2023 tarihli faaliyet raporu ektedir.</body></html>',
        "6686105": '<html><head><meta property="article:published_time" content="2024-02-06T17:00:00+03:00"></head><body>31 12 2023 Tarihli faaliyet raporu</body></html>',
        "6654426": '<html><head><meta property="article:published_time" content="2024-06-01T17:00:00+03:00"></head><body>01.01.2024-31.03.2024 tarihli konsolide faaliyet raporu ektedir.</body></html>',
        "6636473": '<html><head><meta property="article:published_time" content="2024-08-07T17:00:00+03:00"></head><body>Mali Tablonun Hesap Dönemi 01.01.2024-30.06.2024</body></html>',
        "6614951": '<html><head><meta property="article:published_time" content="2024-11-10T17:00:00+03:00"></head><body>30.09.2024 tarihli Faaliyet Raporu ektedir.</body></html>',
        "32918984": '<html><head><meta property="article:published_time" content="2026-03-09T17:00:00+03:00"></head><body>31.03.2026 Faaliyet Raporu</body></html>',
    }

    def fake_request_text(url: str, **_kwargs):
        for key, html in pages.items():
            if key in url:
                return html
        raise AssertionError(url)

    monkeypatch.setattr(loader, "_request_text", fake_request_text)

    records = sorted(loader.fetch_records("RODRG"), key=lambda row: row["period_end"])

    assert records == [
        {
            "symbol": "RODRG",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 5, 8),
            "announcement_source_url": "https://financialreports.eu/filings/rodrigo-tekstil-sanayi-ve-ticaret-as/report-publication-announcement/2023/6737731/",
        },
        {
            "symbol": "RODRG",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 14),
            "announcement_source_url": "https://financialreports.eu/filings/rodrigo-tekstil-sanayi-ve-ticaret-as/report-publication-announcement/2023/6717589/",
        },
        {
            "symbol": "RODRG",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 3),
            "announcement_source_url": "https://financialreports.eu/filings/rodrigo-tekstil-sanayi-ve-ticaret-as/report-publication-announcement/2023/6702901/",
        },
        {
            "symbol": "RODRG",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 2, 6),
            "announcement_source_url": "https://financialreports.eu/filings/rodrigo-tekstil-sanayi-ve-ticaret-as/report-publication-announcement/2024/6686105/",
        },
        {
            "symbol": "RODRG",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 1),
            "announcement_source_url": "https://financialreports.eu/filings/rodrigo-tekstil-sanayi-ve-ticaret-as/report-publication-announcement/2024/6654426/",
        },
        {
            "symbol": "RODRG",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 8, 7),
            "announcement_source_url": "https://financialreports.eu/filings/rodrigo-tekstil-sanayi-ve-ticaret-as/regulatory-filings/2024/6636473/",
        },
        {
            "symbol": "RODRG",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 10),
            "announcement_source_url": "https://financialreports.eu/filings/rodrigo-tekstil-sanayi-ve-ticaret-as/report-publication-announcement/2024/6614951/",
        },
        {
            "symbol": "RODRG",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 3, 9),
            "announcement_source_url": "https://financialreports.eu/filings/rodrigo-tekstil-sanayi-ve-ticaret-as/report-publication-announcement/2026/32918984/",
        },
    ]


def test_fetchRecords_usesFadeFinancialreportsFallback(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    pages = {
        "6736782": '<html><head><meta property="article:published_time" content="2023-05-08T17:00:00+03:00"></head><body>31.03.2023 Tarihli Faaliyet Raporu</body></html>',
        "6715340": '<html><head><meta property="article:published_time" content="2023-08-07T17:00:00+03:00"></head><body>30.06.2023 Tarihli Faaliyet Raporu</body></html>',
        "6701456": '<html><head><meta property="article:published_time" content="2023-11-09T17:00:00+03:00"></head><body>30.09.2023 Tarihli Faaliyet Raporu</body></html>',
        "6680523": '<html><head><meta property="article:published_time" content="2024-02-06T17:00:00+03:00"></head><body>31.12.2023 Tarihli Faaliyet Raporu Yayınlanması</body></html>',
        "6648859": '<html><head><meta property="article:published_time" content="2024-06-14T17:00:00+03:00"></head><body>31.03.2024 Tarihli Faaliyet Raporu</body></html>',
        "6623863": '<html><head><meta property="article:published_time" content="2024-09-30T17:00:00+03:00"></head><body>30.06.2024 Tarihli Faaliyet Raporu</body></html>',
        "6615199": '<html><head><meta property="article:published_time" content="2024-11-08T17:00:00+03:00"></head><body>30.09.2024 Tarihli Faaliyet Raporu</body></html>',
        "44302130": '<html><head><meta property="article:published_time" content="2026-05-08T17:00:00+03:00"></head><body>31.03.2026 Tarihli Faaliyet Raporu</body></html>',
    }

    def fake_request_text(url: str, **_kwargs):
        for key, html in pages.items():
            if key in url:
                return html
        raise AssertionError(url)

    monkeypatch.setattr(loader, "_request_text", fake_request_text)

    records = sorted(loader.fetch_records("FADE"), key=lambda row: row["period_end"])

    assert records == [
        {
            "symbol": "FADE",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 5, 8),
            "announcement_source_url": "https://financialreports.eu/filings/fade-gida-yatirim-sanayi-ticaret-as/report-publication-announcement/2023/6736782/",
        },
        {
            "symbol": "FADE",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 7),
            "announcement_source_url": "https://financialreports.eu/filings/fade-gida-yatirim-sanayi-ticaret-as/report-publication-announcement/2023/6715340/",
        },
        {
            "symbol": "FADE",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 9),
            "announcement_source_url": "https://financialreports.eu/filings/fade-gida-yatirim-sanayi-ticaret-as/report-publication-announcement/2023/6701456/",
        },
        {
            "symbol": "FADE",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 2, 6),
            "announcement_source_url": "https://financialreports.eu/filings/fade-gida-yatirim-sanayi-ticaret-as/report-publication-announcement/2024/6680523/",
        },
        {
            "symbol": "FADE",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 14),
            "announcement_source_url": "https://financialreports.eu/filings/fade-gida-yatirim-sanayi-ticaret-as/report-publication-announcement/2024/6648859/",
        },
        {
            "symbol": "FADE",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 30),
            "announcement_source_url": "https://financialreports.eu/filings/fade-gida-yatirim-sanayi-ticaret-as/report-publication-announcement/2024/6623863/",
        },
        {
            "symbol": "FADE",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 8),
            "announcement_source_url": "https://financialreports.eu/filings/fade-gida-yatirim-sanayi-ticaret-as/report-publication-announcement/2024/6615199/",
        },
        {
            "symbol": "FADE",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 5, 8),
            "announcement_source_url": "https://financialreports.eu/filings/fade-gida-yatirim-sanayi-ticaret-as/regulatory-filings/2026/44302130/",
        },
    ]


def test_fetchRecords_usesEliteFinancialreportsFallback(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    pages = {
        "6714990": '<html><head><meta property="article:published_time" content="2023-08-21T17:49:10+02:00"></head><body>2023 Q2 Konsolide Faaliyet Raporu</body></html>',
        "6700888": '<html><head><meta property="article:published_time" content="2023-11-09T16:34:39+01:00"></head><body>2023 Q3 Konsolide Faaliyet Raporu</body></html>',
        "6660156": '<html><head><meta property="article:published_time" content="2024-05-20T22:41:02+02:00"></head><body>ELİTE 2023Q4 Konsolide Faaliyet Raporu</body></html>',
        "6647222": '<html><head><meta property="article:published_time" content="2024-06-21T23:47:37+02:00"></head><body>2024 Q1 Konsolide Faaliyet Raporu</body></html>',
        "6622299": '<html><head><meta property="article:published_time" content="2024-10-01T01:21:54+02:00"></head><body>Faaliyet Raporu</body></html>',
        "6614944": '<html><head><meta property="article:published_time" content="2024-11-11T21:59:27+01:00"></head><body>Faaliyet Raporu</body></html>',
    }

    def fake_request_text(url: str, **_kwargs):
        for key, html in pages.items():
            if key in url:
                return html
        raise AssertionError(url)

    monkeypatch.setattr(loader, "_request_text", fake_request_text)

    records = sorted(loader.fetch_records("ELITE"), key=lambda row: row["period_end"])

    assert records == [
        {
            "symbol": "ELITE",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 21),
            "announcement_source_url": "https://financialreports.eu/filings/elite-naturel-organik-gida-sanayi-ve-ticaret-as/report-publication-announcement/2023/6714990/",
        },
        {
            "symbol": "ELITE",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 9),
            "announcement_source_url": "https://financialreports.eu/filings/elite-naturel-organik-gida-sanayi-ve-ticaret-as/report-publication-announcement/2023/6700888/",
        },
        {
            "symbol": "ELITE",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 20),
            "announcement_source_url": "https://financialreports.eu/filings/elite-naturel-organik-gida-sanayi-ve-ticaret-as/report-publication-announcement/2024/6660156/",
        },
        {
            "symbol": "ELITE",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 21),
            "announcement_source_url": "https://financialreports.eu/filings/elite-naturel-organik-gida-sanayi-ve-ticaret-as/report-publication-announcement/2024/6647222/",
        },
        {
            "symbol": "ELITE",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 30),
            "announcement_source_url": "https://financialreports.eu/filings/elite-naturel-organik-gida-sanayi-ve-ticaret-as/report-publication-announcement/2024/6622299/",
        },
        {
            "symbol": "ELITE",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 11),
            "announcement_source_url": "https://financialreports.eu/filings/elite-naturel-organik-gida-sanayi-ve-ticaret-as/report-publication-announcement/2024/6614944/",
        },
    ]


def test_fetchRecords_usesErcbFinancialreportsFallback(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    pages = {
        "6716447": '<html><head><meta property="article:published_time" content="2023-08-11T11:10:31+02:00"></head><body>30.06.2023 Faaliyet Raporu</body></html>',
        "6701257": '<html><head><meta property="article:published_time" content="2023-11-09T14:24:43+01:00"></head><body>01.01.2023 - 30.09.2023 Dönemi Faaliyet Raporu</body></html>',
        "6679201": '<html><head><meta property="article:published_time" content="2024-05-15T14:34:31+02:00"></head><body>01.01.2023-31.12.2023 Dönemi Faaliyet Raporu</body></html>',
        "6663363": '<html><head><meta property="article:published_time" content="2024-06-23T22:40:39+02:00"></head><body>31.03.2024 Faaliyet Raporu</body></html>',
        "6633823": '<html><head><meta property="article:published_time" content="2024-09-25T17:55:34+02:00"></head><body>01.01.2024-30.06.2024 faaliyet raporu</body></html>',
        "6614367": '<html><head><meta property="article:published_time" content="2024-11-13T12:35:23+01:00"></head><body>01.01.2024-30.09.2024 Dönemi Faaliyet Raporu</body></html>',
    }

    def fake_request_text(url: str, **_kwargs):
        for key, html in pages.items():
            if key in url:
                return html
        raise AssertionError(url)

    monkeypatch.setattr(loader, "_request_text", fake_request_text)

    records = sorted(loader.fetch_records("ERCB"), key=lambda row: row["period_end"])

    assert records == [
        {
            "symbol": "ERCB",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 11),
            "announcement_source_url": "https://financialreports.eu/filings/erciyas-celik-boru-sanayi-as/report-publication-announcement/2023/6716447/",
        },
        {
            "symbol": "ERCB",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 9),
            "announcement_source_url": "https://financialreports.eu/filings/erciyas-celik-boru-sanayi-as/report-publication-announcement/2023/6701257/",
        },
        {
            "symbol": "ERCB",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 15),
            "announcement_source_url": "https://financialreports.eu/filings/erciyas-celik-boru-sanayi-as/report-publication-announcement/2024/6679201/",
        },
        {
            "symbol": "ERCB",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 23),
            "announcement_source_url": "https://financialreports.eu/filings/erciyas-celik-boru-sanayi-as/report-publication-announcement/2024/6663363/",
        },
        {
            "symbol": "ERCB",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 25),
            "announcement_source_url": "https://financialreports.eu/filings/erciyas-celik-boru-sanayi-as/report-publication-announcement/2024/6633823/",
        },
        {
            "symbol": "ERCB",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 13),
            "announcement_source_url": "https://financialreports.eu/filings/erciyas-celik-boru-sanayi-as/report-publication-announcement/2024/6614367/",
        },
    ]


def test_fetchRecords_usesIssenFinancialreportsFallback(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    pages = {
        "6717044": '<html><head><meta property="article:published_time" content="2023-08-15T17:11:10+02:00"></head><body>01.01.2023 - 30.06.2023 dönemini kapsayan faaliyet raporu açıklama ekindedir.</body></html>',
        "6702021": '<html><head><meta property="article:published_time" content="2023-11-07T16:26:05+01:00"></head><body>01.01.2023 - 30.09.2023 dönemini kapsayan yönetim kurulu faaliyet raporu açıklamamız ekindedir.</body></html>',
        "6675368": '<html><head><meta property="article:published_time" content="2024-03-28T19:27:36+01:00"></head><body>01.01.2023 - 31.12.2023 dönemini kapsayan yönetim kurulu faaliyet raporu açıklamamız ekindedir.</body></html>',
        "6650313": '<html><head><meta property="article:published_time" content="2024-06-12T17:26:12+02:00"></head><body>01.01.2024 - 31.03.2024 dönemini kapsayan yönetim kurulu faaliyet raporu açıklamamız ekindedir.</body></html>',
        "6628633": '<html><head><meta property="article:published_time" content="2024-09-11T17:13:43+02:00"></head><body>01.01.2024 - 30.06.2024 dönemini kapsayan yönetim kurulu faaliyet raporu açıklamamız ekindedir.</body></html>',
        "6614115": '<html><head><meta property="article:published_time" content="2024-11-11T16:20:04+01:00"></head><body>01.01.2024 - 30.09.2024 dönemini kapsayan faaliyet raporu açıklamamız ekinde yer almaktadır.</body></html>',
    }

    def fake_request_text(url: str, **_kwargs):
        for key, html in pages.items():
            if key in url:
                return html
        raise AssertionError(url)

    monkeypatch.setattr(loader, "_request_text", fake_request_text)

    records = sorted(loader.fetch_records("ISSEN"), key=lambda row: row["period_end"])

    assert records == [
        {
            "symbol": "ISSEN",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 15),
            "announcement_source_url": "https://financialreports.eu/filings/isbir-sentetik-dokuma-sanayi-as/report-publication-announcement/2023/6717044/",
        },
        {
            "symbol": "ISSEN",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 7),
            "announcement_source_url": "https://financialreports.eu/filings/isbir-sentetik-dokuma-sanayi-as/report-publication-announcement/2023/6702021/",
        },
        {
            "symbol": "ISSEN",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 3, 28),
            "announcement_source_url": "https://financialreports.eu/filings/isbir-sentetik-dokuma-sanayi-as/report-publication-announcement/2024/6675368/",
        },
        {
            "symbol": "ISSEN",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 12),
            "announcement_source_url": "https://financialreports.eu/filings/isbir-sentetik-dokuma-sanayi-as/report-publication-announcement/2024/6650313/",
        },
        {
            "symbol": "ISSEN",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 11),
            "announcement_source_url": "https://financialreports.eu/filings/isbir-sentetik-dokuma-sanayi-as/report-publication-announcement/2024/6628633/",
        },
        {
            "symbol": "ISSEN",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 11),
            "announcement_source_url": "https://financialreports.eu/filings/isbir-sentetik-dokuma-sanayi-as/report-publication-announcement/2024/6614115/",
        },
    ]


def test_fetchRecords_usesPnlsnFinancialreportsFallback(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    pages = {
        "6721796": '<html><head><meta property="article:published_time" content="2023-07-31T17:14:02+02:00"></head><body>Panelsan 2023-2.Çeyrek YK Faaliyet Raporu</body></html>',
        "6704832": '<html><head><meta property="article:published_time" content="2023-10-27T17:12:03+02:00"></head><body>Panelsan 2023-3.Çeyrek YK Faaliyet Raporu</body></html>',
        "6673821": '<html><head><meta property="article:published_time" content="2024-04-02T17:11:16+02:00"></head><body>Panelsan Faaliyet Raporu hk.</body></html>',
        "6650834": '<html><head><meta property="article:published_time" content="2024-06-11T17:12:17+02:00"></head><body>Panelsan Faaliyet Raporu hk.</body></html>',
        "6626542": '<html><head><meta property="article:published_time" content="2024-09-18T17:11:37+02:00"></head><body>Panelsan Faaliyet Raporu hk.</body></html>',
        "6617578": '<html><head><meta property="article:published_time" content="2024-10-30T16:10:47+01:00"></head><body>Panelsan Faaliyet Raporu hk.</body></html>',
    }

    def fake_request_text(url: str, **_kwargs):
        for key, html in pages.items():
            if key in url:
                return html
        raise AssertionError(url)

    monkeypatch.setattr(loader, "_request_text", fake_request_text)

    records = loader.fetch_records("PNLSN")

    assert records == [
        {
            "symbol": "PNLSN",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 7, 31),
            "announcement_source_url": "https://financialreports.eu/filings/panelsan-cati-cephe-sistemleri-sanayi-ve-ticaret-as/report-publication-announcement/2023/6721796/",
        },
        {
            "symbol": "PNLSN",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 27),
            "announcement_source_url": "https://financialreports.eu/filings/panelsan-cati-cephe-sistemleri-sanayi-ve-ticaret-as/report-publication-announcement/2023/6704832/",
        },
        {
            "symbol": "PNLSN",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 4, 2),
            "announcement_source_url": "https://financialreports.eu/filings/panelsan-cati-cephe-sistemleri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6673821/",
        },
        {
            "symbol": "PNLSN",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 11),
            "announcement_source_url": "https://financialreports.eu/filings/panelsan-cati-cephe-sistemleri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6650834/",
        },
        {
            "symbol": "PNLSN",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 18),
            "announcement_source_url": "https://financialreports.eu/filings/panelsan-cati-cephe-sistemleri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6626542/",
        },
        {
            "symbol": "PNLSN",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/panelsan-cati-cephe-sistemleri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6617578/",
        },
    ]


def test_fetchRecords_usesBienyFinancialreportsFallback(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    pages = {
        "6728459": '<html><head><meta property="article:published_time" content="2023-06-19T18:43:45+02:00"></head><body>01.01.2023-31.03.2023 Yönetim Kurulu Faaliyet Raporu</body></html>',
        "6715000": '<html><head><meta property="article:published_time" content="2023-08-21T17:50:38+02:00"></head><body>01.01.2023 - 30.06.2023 Yönetim Kurulu Faaliyet Raporu</body></html>',
        "6700939": '<html><head><meta property="article:published_time" content="2023-11-09T16:42:57+01:00"></head><body>01.01.2023 - 30.09.2023 Yönetim Kurulu Faaliyet Raporu</body></html>',
        "6660739": '<html><head><meta property="article:published_time" content="2024-05-17T18:03:50+02:00"></head><body>01.01.2023 - 31.12.2023 Yönetim Kurulu Faaliyet Raporu</body></html>',
        "6647696": '<html><head><meta property="article:published_time" content="2024-06-21T18:56:47+02:00"></head><body>01.01.2024 - 31.03.2024 Yönetim Kurulu Faaliyet Raporu</body></html>',
        "6623222": '<html><head><meta property="article:published_time" content="2024-09-30T17:55:58+02:00"></head><body>01.01.2024 - 30.06.2024 Yönetim Kurulu Faaliyet Raporu</body></html>',
        "6614285": '<html><head><meta property="article:published_time" content="2024-11-11T16:35:41+01:00"></head><body>01.01.2024 - 30.09.2024 Yönetim Kurulu Faaliyet Raporu</body></html>',
    }

    def fake_request_text(url: str, **_kwargs):
        for key, html in pages.items():
            if key in url:
                return html
        raise AssertionError(url)

    monkeypatch.setattr(loader, "_request_text", fake_request_text)

    records = loader.fetch_records("BIENY")

    assert records == [
        {
            "symbol": "BIENY",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 6, 19),
            "announcement_source_url": "https://financialreports.eu/filings/bien-yapi-urunleri-sanayi-turizm-ve-ticaret-as/report-publication-announcement/2023/6728459/",
        },
        {
            "symbol": "BIENY",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 21),
            "announcement_source_url": "https://financialreports.eu/filings/bien-yapi-urunleri-sanayi-turizm-ve-ticaret-as/report-publication-announcement/2023/6715000/",
        },
        {
            "symbol": "BIENY",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 9),
            "announcement_source_url": "https://financialreports.eu/filings/bien-yapi-urunleri-sanayi-turizm-ve-ticaret-as/report-publication-announcement/2023/6700939/",
        },
        {
            "symbol": "BIENY",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 17),
            "announcement_source_url": "https://financialreports.eu/filings/bien-yapi-urunleri-sanayi-turizm-ve-ticaret-as/report-publication-announcement/2024/6660739/",
        },
        {
            "symbol": "BIENY",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 21),
            "announcement_source_url": "https://financialreports.eu/filings/bien-yapi-urunleri-sanayi-turizm-ve-ticaret-as/report-publication-announcement/2024/6647696/",
        },
        {
            "symbol": "BIENY",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 30),
            "announcement_source_url": "https://financialreports.eu/filings/bien-yapi-urunleri-sanayi-turizm-ve-ticaret-as/report-publication-announcement/2024/6623222/",
        },
        {
            "symbol": "BIENY",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 11),
            "announcement_source_url": "https://financialreports.eu/filings/bien-yapi-urunleri-sanayi-turizm-ve-ticaret-as/report-publication-announcement/2024/6614285/",
        },
    ]


def test_fetchRecords_usesRubnsFinancialreportsFallback(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    pages = {
        "6719612": '<html><head><meta property="article:published_time" content="2023-08-08T17:15:47+02:00"></head><body>Rubenis Tekstil 30.06.2023 Faaliyet Raporu</body></html>',
        "6703889": '<html><head><meta property="article:published_time" content="2023-10-30T16:11:38+01:00"></head><body>Rubenis Tekstil 30.09.2023 Faaliyet Raporu</body></html>',
        "6670855": '<html><head><meta property="article:published_time" content="2024-04-18T22:33:45+02:00"></head><body>Rubenis Tekstil 31.12.2023 Faaliyet Raporu</body></html>',
        "6655697": '<html><head><meta property="article:published_time" content="2024-05-29T17:15:59+02:00"></head><body>Rubenis 31.03.2024 Faaliyet Raporu</body></html>',
        "6626593": '<html><head><meta property="article:published_time" content="2024-09-18T17:20:37+02:00"></head><body>Rubenis Tekstil 30.06.2024 Faaliyet Raporu</body></html>',
        "6617753": '<html><head><meta property="article:published_time" content="2024-10-30T16:21:46+01:00"></head><body>Rubenis Tekstil 30.09.2024 Faaliyet Raporu</body></html>',
    }

    def fake_request_text(url: str, **_kwargs):
        for key, html in pages.items():
            if key in url:
                return html
        raise AssertionError(url)

    monkeypatch.setattr(loader, "_request_text", fake_request_text)

    records = loader.fetch_records("RUBNS")

    assert records == [
        {
            "symbol": "RUBNS",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 8),
            "announcement_source_url": "https://financialreports.eu/filings/rubenis-tekstil-sanayi-ticaret-as/report-publication-announcement/2023/6719612/",
        },
        {
            "symbol": "RUBNS",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/rubenis-tekstil-sanayi-ticaret-as/report-publication-announcement/2023/6703889/",
        },
        {
            "symbol": "RUBNS",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 4, 18),
            "announcement_source_url": "https://financialreports.eu/filings/rubenis-tekstil-sanayi-ticaret-as/report-publication-announcement/2024/6670855/",
        },
        {
            "symbol": "RUBNS",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 5, 29),
            "announcement_source_url": "https://financialreports.eu/filings/rubenis-tekstil-sanayi-ticaret-as/report-publication-announcement/2024/6655697/",
        },
        {
            "symbol": "RUBNS",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 18),
            "announcement_source_url": "https://financialreports.eu/filings/rubenis-tekstil-sanayi-ticaret-as/report-publication-announcement/2024/6626593/",
        },
        {
            "symbol": "RUBNS",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/rubenis-tekstil-sanayi-ticaret-as/report-publication-announcement/2024/6617753/",
        },
    ]


def test_fetchRecords_usesKlsynFinancialreportsFallback(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    pages = {
        "6736316": '<html><head><meta property="article:published_time" content="2023-05-10T19:21:03+02:00"></head><body>01.01.2023-31.03.2023 Dönemine Ait Faaliyet Raporu Hk</body></html>',
        "6715640": '<html><head><meta property="article:published_time" content="2023-08-18T17:33:54+02:00"></head><body>01.01.2023 -30.06.2023 Dönemine Ait Faaliyet Raporu Hk</body></html>',
        "6702127": '<html><head><meta property="article:published_time" content="2023-11-07T17:21:45+01:00"></head><body>01.01.2023 -30.09.2023 Dönemine Ait Faaliyet Raporu Hk</body></html>',
        "6659919": '<html><head><meta property="article:published_time" content="2024-05-20T20:56:07+02:00"></head><body>2023 Faaliyet Raporu</body></html>',
        "6650259": '<html><head><meta property="article:published_time" content="2024-06-12T17:12:05+02:00"></head><body>2024 1.Dönem Faaliyet Raporu</body></html>',
        "6624322": '<html><head><meta property="article:published_time" content="2024-09-26T17:12:50+02:00"></head><body>Koleksiyon Mobilya 30.06.2024 Yönetim Kurulu Faaliyet Raporu</body></html>',
        "6616108": '<html><head><meta property="article:published_time" content="2024-11-06T16:13:50+01:00"></head><body>Koleksiyon Mobilya 30.09.2024 Yönetim Kurulu Faaliyet Raporu</body></html>',
    }

    def fake_request_text(url: str, **_kwargs):
        for key, html in pages.items():
            if key in url:
                return html
        raise AssertionError(url)

    monkeypatch.setattr(loader, "_request_text", fake_request_text)

    records = loader.fetch_records("KLSYN")

    assert records == [
        {
            "symbol": "KLSYN",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 5, 10),
            "announcement_source_url": "https://financialreports.eu/filings/koleksiyon-mobilya-sanayi-as/report-publication-announcement/2023/6736316/",
        },
        {
            "symbol": "KLSYN",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 18),
            "announcement_source_url": "https://financialreports.eu/filings/koleksiyon-mobilya-sanayi-as/report-publication-announcement/2023/6715640/",
        },
        {
            "symbol": "KLSYN",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 7),
            "announcement_source_url": "https://financialreports.eu/filings/koleksiyon-mobilya-sanayi-as/report-publication-announcement/2023/6702127/",
        },
        {
            "symbol": "KLSYN",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 20),
            "announcement_source_url": "https://financialreports.eu/filings/koleksiyon-mobilya-sanayi-as/report-publication-announcement/2024/6659919/",
        },
        {
            "symbol": "KLSYN",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 12),
            "announcement_source_url": "https://financialreports.eu/filings/koleksiyon-mobilya-sanayi-as/report-publication-announcement/2024/6650259/",
        },
        {
            "symbol": "KLSYN",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 26),
            "announcement_source_url": "https://financialreports.eu/filings/koleksiyon-mobilya-sanayi-as/interim-quarterly-report/2024/6624322/",
        },
        {
            "symbol": "KLSYN",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 6),
            "announcement_source_url": "https://financialreports.eu/filings/koleksiyon-mobilya-sanayi-as/report-publication-announcement/2024/6616108/",
        },
    ]


def test_fetchRecords_usesAstorFinancialreportsFallback(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    pages = {
        "6719327": '<html><head><meta property="article:published_time" content="2023-08-09T21:23:31+02:00"></head><body>2023 2.Dönem Yönetim Kurulu Faaliyet Raporu</body></html>',
        "6703549": '<html><head><meta property="article:published_time" content="2023-10-31T16:45:48+01:00"></head><body>2023 3.Çeyrek Faaliyet Raporu</body></html>',
        "6682368": '<html><head><meta property="article:published_time" content="2024-02-27T04:22:18+01:00"></head><body>Yönetim Kurulu Faaliyet Raporu</body></html>',
        "6657125": '<html><head><meta property="article:published_time" content="2024-05-23T00:49:42+02:00"></head><body>Yönetim Kurulu Faaliyet Raporu</body></html>',
        "6632006": '<html><head><meta property="article:published_time" content="2024-08-26T17:28:02+02:00"></head><body>01.01.2024-30.06.2024 Faaliyet Raporu</body></html>',
        "6617944": '<html><head><meta property="article:published_time" content="2024-10-30T16:50:42+01:00"></head><body>Yönetim Kurulu Faaliyet Raporu</body></html>',
    }

    def fake_request_text(url: str, **_kwargs):
        for key, html in pages.items():
            if key in url:
                return html
        raise AssertionError(url)

    monkeypatch.setattr(loader, "_request_text", fake_request_text)

    records = loader.fetch_records("ASTOR")

    assert records == [
        {
            "symbol": "ASTOR",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 9),
            "announcement_source_url": "https://financialreports.eu/filings/astor-enerji-as/report-publication-announcement/2023/6719327/",
        },
        {
            "symbol": "ASTOR",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 31),
            "announcement_source_url": "https://financialreports.eu/filings/astor-enerji-as/report-publication-announcement/2023/6703549/",
        },
        {
            "symbol": "ASTOR",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 2, 27),
            "announcement_source_url": "https://financialreports.eu/filings/astor-enerji-as/report-publication-announcement/2024/6682368/",
        },
        {
            "symbol": "ASTOR",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 5, 22),
            "announcement_source_url": "https://financialreports.eu/filings/astor-enerji-as/report-publication-announcement/2024/6657125/",
        },
        {
            "symbol": "ASTOR",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 8, 26),
            "announcement_source_url": "https://financialreports.eu/filings/astor-enerji-as/report-publication-announcement/2024/6632006/",
        },
        {
            "symbol": "ASTOR",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/astor-enerji-as/report-publication-announcement/2024/6617944/",
        },
    ]


def test_fetchRecords_usesSokeFinancialreportsFallback(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    pages = {
        "6716316": '<html><head><meta property="article:published_time" content="2023-08-17T19:58:24+02:00"></head><body>Faaliyet Raporu</body></html>',
        "6701739": '<html><head><meta property="article:published_time" content="2023-11-08T19:19:56+01:00"></head><body>Faaliyet Raporu</body></html>',
        "6660945": '<html><head><meta property="article:published_time" content="2024-05-17T20:48:07+02:00"></head><body>Faaliyet Raporu</body></html>',
        "6649362": '<html><head><meta property="article:published_time" content="2024-06-14T19:56:12+02:00"></head><body>Faaliyet Raporu</body></html>',
        "6624161": '<html><head><meta property="article:published_time" content="2024-09-27T20:19:54+02:00"></head><body>Faaliyet Raporu</body></html>',
        "6615337": '<html><head><meta property="article:published_time" content="2024-11-08T16:28:54+01:00"></head><body>Faaliyet Raporu</body></html>',
    }

    def fake_request_text(url: str, **_kwargs):
        for key, html in pages.items():
            if key in url:
                return html
        raise AssertionError(url)

    monkeypatch.setattr(loader, "_request_text", fake_request_text)

    records = loader.fetch_records("SOKE")

    assert records == [
        {
            "symbol": "SOKE",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 17),
            "announcement_source_url": "https://financialreports.eu/filings/soke-degirmencilik-sanayi-ve-ticaret-as/report-publication-announcement/2023/6716316/",
        },
        {
            "symbol": "SOKE",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 8),
            "announcement_source_url": "https://financialreports.eu/filings/soke-degirmencilik-sanayi-ve-ticaret-as/report-publication-announcement/2023/6701739/",
        },
        {
            "symbol": "SOKE",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 17),
            "announcement_source_url": "https://financialreports.eu/filings/soke-degirmencilik-sanayi-ve-ticaret-as/report-publication-announcement/2024/6660945/",
        },
        {
            "symbol": "SOKE",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 14),
            "announcement_source_url": "https://financialreports.eu/filings/soke-degirmencilik-sanayi-ve-ticaret-as/report-publication-announcement/2024/6649362/",
        },
        {
            "symbol": "SOKE",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 27),
            "announcement_source_url": "https://financialreports.eu/filings/soke-degirmencilik-sanayi-ve-ticaret-as/report-publication-announcement/2024/6624161/",
        },
        {
            "symbol": "SOKE",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 8),
            "announcement_source_url": "https://financialreports.eu/filings/soke-degirmencilik-sanayi-ve-ticaret-as/report-publication-announcement/2024/6615337/",
        },
    ]


def test_fetchRecords_usesOrcayFinancialreportsFallback(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    pages = {
        "6738122": '<html><head><meta property="article:published_time" content="2023-05-05T17:12:54+02:00"></head><body>2023 Yılı 1.3 Aylık Faaliyet Raporu Hk.</body></html>',
        "6718383": '<html><head><meta property="article:published_time" content="2023-08-10T17:51:59+02:00"></head><body>2023 Yılı 2.3 Aylık Faaliyet Raporu Hk</body></html>',
        "6701516": '<html><head><meta property="article:published_time" content="2023-11-08T16:20:48+01:00"></head><body>2023 Yılı 3.3 Aylık Faaliyet Raporu Hk</body></html>',
        "6668629": '<html><head><meta property="article:published_time" content="2024-04-26T17:45:02+02:00"></head><body>2023 Yılı Faaliyet Raporu</body></html>',
        "6651974": '<html><head><meta property="article:published_time" content="2024-06-10T18:51:05+02:00"></head><body>2024 Yılı 1.3 Aylık Faaliyet Raporu</body></html>',
        "6631022": '<html><head><meta property="article:published_time" content="2024-08-29T17:10:25+02:00"></head><body>2024 Yılı 2.3 Aylık Faaliyet Raporu</body></html>',
        "6618585": '<html><head><meta property="article:published_time" content="2024-10-25T17:10:30+02:00"></head><body>2024 Yılı 3.3 Aylık Faaliyet Raporu</body></html>',
    }

    def fake_request_text(url: str, **_kwargs):
        for key, html in pages.items():
            if key in url:
                return html
        raise AssertionError(url)

    monkeypatch.setattr(loader, "_request_text", fake_request_text)

    records = loader.fetch_records("ORCAY")

    assert records == [
        {
            "symbol": "ORCAY",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 5, 5),
            "announcement_source_url": "https://financialreports.eu/filings/orcay-ortakoy-cay-sanayi-ve-ticaret-as/report-publication-announcement/2023/6738122/",
        },
        {
            "symbol": "ORCAY",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 10),
            "announcement_source_url": "https://financialreports.eu/filings/orcay-ortakoy-cay-sanayi-ve-ticaret-as/report-publication-announcement/2023/6718383/",
        },
        {
            "symbol": "ORCAY",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 8),
            "announcement_source_url": "https://financialreports.eu/filings/orcay-ortakoy-cay-sanayi-ve-ticaret-as/report-publication-announcement/2023/6701516/",
        },
        {
            "symbol": "ORCAY",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 4, 26),
            "announcement_source_url": "https://financialreports.eu/filings/orcay-ortakoy-cay-sanayi-ve-ticaret-as/report-publication-announcement/2024/6668629/",
        },
        {
            "symbol": "ORCAY",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 10),
            "announcement_source_url": "https://financialreports.eu/filings/orcay-ortakoy-cay-sanayi-ve-ticaret-as/report-publication-announcement/2024/6651974/",
        },
        {
            "symbol": "ORCAY",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 8, 29),
            "announcement_source_url": "https://financialreports.eu/filings/orcay-ortakoy-cay-sanayi-ve-ticaret-as/report-publication-announcement/2024/6631022/",
        },
        {
            "symbol": "ORCAY",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 10, 25),
            "announcement_source_url": "https://financialreports.eu/filings/orcay-ortakoy-cay-sanayi-ve-ticaret-as/report-publication-announcement/2024/6618585/",
        },
    ]


def test_fetchRecords_usesBarmaFinancialreportsFallback(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    pages = {
        "6740089": '<html><head><meta property="article:published_time" content="2023-05-10T16:30:00+03:00"></head><body>2023 1.3 Aylık Faaliyet Raporu</body></html>',
        "6719904": '<html><head><meta property="article:published_time" content="2023-08-14T17:25:00+03:00"></head><body>2023 2.3 Aylık Faaliyet Raporu</body></html>',
        "6705060": '<html><head><meta property="article:published_time" content="2023-11-09T18:05:00+03:00"></head><body>2023 3.3 Aylık Faaliyet Raporu</body></html>',
        "6757948": '<html><head><meta property="article:published_time" content="2024-04-18T16:00:00+03:00"></head><body>2023 Yılı Faaliyet Raporu</body></html>',
        "6651443": '<html><head><meta property="article:published_time" content="2024-06-12T16:40:00+03:00"></head><body>2024 1.3 Aylık Faaliyet Raporu</body></html>',
        "6625397": '<html><head><meta property="article:published_time" content="2024-09-20T18:10:00+03:00"></head><body>2024 2.3 Aylık Faaliyet Raporu</body></html>',
        "6615554": '<html><head><meta property="article:published_time" content="2024-11-08T17:00:00+03:00"></head><body>2024 3.3 Aylık Faaliyet Raporu</body></html>',
    }

    def fake_request_text(url: str, **_kwargs):
        for key, html in pages.items():
            if key in url:
                return html
        raise AssertionError(url)

    monkeypatch.setattr(loader, "_request_text", fake_request_text)

    records = loader.fetch_records("BARMA")

    assert records == [
        {
            "symbol": "BARMA",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 5, 10),
            "announcement_source_url": "https://financialreports.eu/filings/barem-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2023/6740089/",
        },
        {
            "symbol": "BARMA",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 14),
            "announcement_source_url": "https://financialreports.eu/filings/barem-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2023/6719904/",
        },
        {
            "symbol": "BARMA",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 9),
            "announcement_source_url": "https://financialreports.eu/filings/barem-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2023/6705060/",
        },
        {
            "symbol": "BARMA",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 4, 18),
            "announcement_source_url": "https://financialreports.eu/filings/barem-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2024/6757948/",
        },
        {
            "symbol": "BARMA",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 12),
            "announcement_source_url": "https://financialreports.eu/filings/barem-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2024/6651443/",
        },
        {
            "symbol": "BARMA",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 20),
            "announcement_source_url": "https://financialreports.eu/filings/barem-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2024/6625397/",
        },
        {
            "symbol": "BARMA",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 8),
            "announcement_source_url": "https://financialreports.eu/filings/barem-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2024/6615554/",
        },
    ]


def test_fetchRecords_usesBayrkFinancialreportsFallback(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    pages = {
        "6733814": '<html><head><meta property="article:published_time" content="2023-05-18T17:00:00+03:00"></head><body>Annual / Quarterly Financial Statement</body></html>',
        "6720153": '<html><head><meta property="article:published_time" content="2023-08-07T17:00:00+03:00"></head><body>Interim / Quarterly Report</body></html>',
        "6706360": '<html><head><meta property="article:published_time" content="2023-10-19T17:00:00+03:00"></head><body>Report Publication Announcement</body></html>',
        "6671514": '<html><head><meta property="article:published_time" content="2024-04-16T17:00:00+03:00"></head><body>Audit Report / Information</body></html>',
        "6650996": '<html><head><meta property="article:published_time" content="2024-06-11T17:00:00+03:00"></head><body>Interim / Quarterly Report</body></html>',
        "6627967": '<html><head><meta property="article:published_time" content="2024-09-13T17:00:00+03:00"></head><body>Interim / Quarterly Report</body></html>',
        "6611393": '<html><head><meta property="article:published_time" content="2024-11-26T17:00:00+03:00"></head><body>Report Publication Announcement</body></html>',
    }

    def fake_request_text(url: str, **_kwargs):
        for key, html in pages.items():
            if key in url:
                return html
        raise AssertionError(url)

    monkeypatch.setattr(loader, "_request_text", fake_request_text)

    records = loader.fetch_records("BAYRK")

    assert records == [
        {
            "symbol": "BAYRK",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 5, 18),
            "announcement_source_url": "https://financialreports.eu/filings/bayrak-ebt-taban-sanayi-ve-ticaret-as/annual-quarterly-financial-statement/2023/6733814/",
        },
        {
            "symbol": "BAYRK",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 7),
            "announcement_source_url": "https://financialreports.eu/filings/bayrak-ebt-taban-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6720153/",
        },
        {
            "symbol": "BAYRK",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 19),
            "announcement_source_url": "https://financialreports.eu/filings/bayrak-ebt-taban-sanayi-ve-ticaret-as/report-publication-announcement/2023/6706360/",
        },
        {
            "symbol": "BAYRK",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 4, 16),
            "announcement_source_url": "https://financialreports.eu/filings/bayrak-ebt-taban-sanayi-ve-ticaret-as/audit-report-information/2024/6671514/",
        },
        {
            "symbol": "BAYRK",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 11),
            "announcement_source_url": "https://financialreports.eu/filings/bayrak-ebt-taban-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6650996/",
        },
        {
            "symbol": "BAYRK",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 13),
            "announcement_source_url": "https://financialreports.eu/filings/6627967/content/",
        },
        {
            "symbol": "BAYRK",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 26),
            "announcement_source_url": "https://financialreports.eu/filings/bayrak-ebt-taban-sanayi-ve-ticaret-as/report-publication-announcement/2024/6611393/",
        },
    ]


def test_fetchRecords_usesAngenFinancialreportsFallback(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    pages = {
        "6717458": '<html><head><meta property="article:published_time" content="2023-08-14T17:00:00+03:00"></head><body>Financial Statement Year / Period | 2023 / 6 Months</body></html>',
        "6702846": '<html><head><meta property="article:published_time" content="2023-11-03T17:00:00+03:00"></head><body>Interim / Quarterly Report</body></html>',
        "6663320": '<html><head><meta property="article:published_time" content="2024-05-10T17:00:00+03:00"></head><body>Report Publication Announcement</body></html>',
        "6649346": '<html><head><meta property="article:published_time" content="2024-06-14T17:00:00+03:00"></head><body>Report Publication Announcement</body></html>',
        "6625212": '<html><head><meta property="article:published_time" content="2024-09-23T17:00:00+03:00"></head><body>Report Publication Announcement</body></html>',
        "6615182": '<html><head><meta property="article:published_time" content="2024-11-08T17:00:00+03:00"></head><body>Annual / Quarterly Financial Statement</body></html>',
    }

    def fake_request_text(url: str, **_kwargs):
        for key, html in pages.items():
            if key in url:
                return html
        raise AssertionError(url)

    monkeypatch.setattr(loader, "_request_text", fake_request_text)

    records = loader.fetch_records("ANGEN")

    assert records == [
        {
            "symbol": "ANGEN",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 14),
            "announcement_source_url": "https://financialreports.eu/filings/anatolia-tani-ve-biyoteknoloji-urunleri-arastirma-gelistirme-sanayi-ve-ticaret-as/environmental-social-information/2023/6717458/",
        },
        {
            "symbol": "ANGEN",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 3),
            "announcement_source_url": "https://financialreports.eu/filings/anatolia-tani-ve-biyoteknoloji-urunleri-arastirma-gelistirme-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6702846/",
        },
        {
            "symbol": "ANGEN",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 10),
            "announcement_source_url": "https://financialreports.eu/filings/6663320/content/",
        },
        {
            "symbol": "ANGEN",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 14),
            "announcement_source_url": "https://financialreports.eu/filings/6649346/content/",
        },
        {
            "symbol": "ANGEN",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 23),
            "announcement_source_url": "https://financialreports.eu/filings/6625212/content/",
        },
        {
            "symbol": "ANGEN",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 8),
            "announcement_source_url": "https://financialreports.eu/filings/anatolia-tani-ve-biyoteknoloji-urunleri-arastirma-gelistirme-sanayi-ve-ticaret-as/annual-quarterly-financial-statement/2024/6615182/",
        },
    ]


def test_fetchRecords_usesBmstlFinancialreportsFallback(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    pages = {
        "6720248": '<html><head><meta property="article:published_time" content="2023-08-07T17:00:00+03:00"></head><body>Interim / Quarterly Report</body></html>',
        "6698120": '<html><head><meta property="article:published_time" content="2023-11-27T17:00:00+03:00"></head><body>Interim / Quarterly Report</body></html>',
        "6674891": '<html><head><meta property="article:published_time" content="2024-03-28T17:00:00+03:00"></head><body>Report Publication Announcement</body></html>',
        "6655248": '<html><head><meta property="article:published_time" content="2024-05-30T17:00:00+03:00"></head><body>Annual / Quarterly Financial Statement</body></html>',
        "6624971": '<html><head><meta property="article:published_time" content="2024-09-24T17:00:00+03:00"></head><body>Interim / Quarterly Report</body></html>',
        "6615416": '<html><head><meta property="article:published_time" content="2024-10-30T17:00:00+03:00"></head><body>Earnings Release</body></html>',
    }

    def fake_request_text(url: str, **_kwargs):
        for key, html in pages.items():
            if key in url:
                return html
        raise AssertionError(url)

    monkeypatch.setattr(loader, "_request_text", fake_request_text)

    records = loader.fetch_records("BMSTL")

    assert records == [
        {
            "symbol": "BMSTL",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 7),
            "announcement_source_url": "https://financialreports.eu/filings/bms-birlesik-metal-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6720248/",
        },
        {
            "symbol": "BMSTL",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 27),
            "announcement_source_url": "https://financialreports.eu/filings/bms-birlesik-metal-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6698120/",
        },
        {
            "symbol": "BMSTL",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 3, 28),
            "announcement_source_url": "https://financialreports.eu/filings/bms-birlesik-metal-sanayi-ve-ticaret-as/report-publication-announcement/2024/6674891/",
        },
        {
            "symbol": "BMSTL",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 5, 30),
            "announcement_source_url": "https://financialreports.eu/filings/bms-birlesik-metal-sanayi-ve-ticaret-as/annual-quarterly-financial-statement/2024/6655248/",
        },
        {
            "symbol": "BMSTL",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 24),
            "announcement_source_url": "https://financialreports.eu/filings/bms-birlesik-metal-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6624971/",
        },
        {
            "symbol": "BMSTL",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/bms-birlesik-metal-sanayi-ve-ticaret-as/earnings-release/2024/6615416/",
        },
    ]


def test_fetchRecords_usesGedzaFinancialreportsFallback(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    pages = {
        "6717121": '<html><head><meta property="article:published_time" content="2023-08-15T17:00:00+03:00"></head><body>Şirketimiz 01.01.2023 - 30.06.2023 Ara Dönem Faaliyet Raporu Ek\'te PDF olarak sunulmuştur.</body></html>',
        "6737574": '<html><head><meta property="article:published_time" content="2023-05-08T17:00:00+03:00"></head><body>2023-1 Dönem Faaliyet Raporları</body></html>',
        "6701568": '<html><head><meta property="article:published_time" content="2023-11-08T17:00:00+03:00"></head><body>Şirketimiz 01.01.2023 - 30.09.2023 Ara Dönem Faaliyet Raporu Ek\'te PDF olarak sunulmuştur.</body></html>',
        "6661866": '<html><head><meta property="article:published_time" content="2024-05-14T11:20:13+02:00"></head><body>Audit Report / Information 2023</body></html>',
        "6648134": '<html><head><meta property="article:published_time" content="2024-06-20T17:00:00+03:00"></head><body>Şirketimiz 01.01.2024 - 31.03.2024 ara hesap dönemi Faaliyet Raporu Ek\'te PDF olarak sunulmuştur.</body></html>',
        "6625263": '<html><head><meta property="article:published_time" content="2024-09-23T17:00:00+03:00"></head><body>Şirketimiz 01.01.2024 - 30.06.2024 ara hesap dönemi Faaliyet Raporu Ek\'te PDF olarak sunulmuştur.</body></html>',
        "6614473": '<html><head><meta property="article:published_time" content="2024-11-11T17:00:00+03:00"></head><body>Şirketimiz 01.01.2024 - 30.09.2024 ara hesap dönemi Faaliyet Raporu Ek\'te PDF olarak sunulmuştur.</body></html>',
        "32909469": '<html><head><meta property="article:published_time" content="2026-03-06T16:23:48+01:00"></head><body>31.03.2026 Faaliyet Raporu</body></html>',
    }

    def fake_request_text(url: str, **_kwargs):
        for key, html in pages.items():
            if key in url:
                return html
        raise AssertionError(url)

    monkeypatch.setattr(loader, "_request_text", fake_request_text)

    records = sorted(loader.fetch_records("GEDZA"), key=lambda row: row["period_end"])

    assert records == [
        {
            "symbol": "GEDZA",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 5, 8),
            "announcement_source_url": "https://financialreports.eu/filings/gediz-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2023/6737574/",
        },
        {
            "symbol": "GEDZA",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 15),
            "announcement_source_url": "https://financialreports.eu/filings/gediz-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2023/6717121/",
        },
        {
            "symbol": "GEDZA",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 8),
            "announcement_source_url": "https://financialreports.eu/filings/gediz-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2023/6701568/",
        },
        {
            "symbol": "GEDZA",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 14),
            "announcement_source_url": "https://financialreports.eu/filings/6661866/content/",
        },
        {
            "symbol": "GEDZA",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 20),
            "announcement_source_url": "https://financialreports.eu/filings/gediz-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2024/6648134/",
        },
        {
            "symbol": "GEDZA",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 23),
            "announcement_source_url": "https://financialreports.eu/filings/gediz-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2024/6625263/",
        },
        {
            "symbol": "GEDZA",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 11),
            "announcement_source_url": "https://financialreports.eu/filings/gediz-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2024/6614473/",
        },
        {
            "symbol": "GEDZA",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 3, 6),
            "announcement_source_url": "https://financialreports.eu/filings/gediz-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2026/32909469/",
        },
    ]


def test_fetchRecords_usesSilvrFinancialreportsFallback(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    pages = {
        "6739916": '<html><head><meta property="article:published_time" content="2023-05-02T17:00:00+03:00"></head><body>31.03.2023 dönemi Yönetim Kurulu Faaliyet Raporu</body></html>',
        "6719250": '<html><head><meta property="article:published_time" content="2023-08-09T17:00:00+03:00"></head><body>2023/2. Dönem Yönetim Kurulu Faaliyet Raporu</body></html>',
        "6704073": '<html><head><meta property="article:published_time" content="2023-10-30T17:00:00+03:00"></head><body>2023/3. Dönem Yönetim Kurulu Faaliyet Raporu</body></html>',
        "6659114": '<html><head><meta property="article:published_time" content="2024-05-21T17:00:00+03:00"></head><body>31.12.2023 Faaliyet Raporu</body></html>',
        "6651309": '<html><head><meta property="article:published_time" content="2024-06-11T17:00:00+03:00"></head><body>31.03.2024 dönemi Yönetim Kurulu Faaliyet Raporu</body></html>',
        "6626891": '<html><head><meta property="article:published_time" content="2024-09-17T17:00:00+03:00"></head><body>2024/2. Dönem Yönetim Kurulu Faaliyet Raporu</body></html>',
        "6617683": '<html><head><meta property="article:published_time" content="2024-10-30T17:00:00+03:00"></head><body>2024/3. Dönem Yönetim Kurulu Faaliyet Raporu</body></html>',
        "38661174": '<html><head><meta property="article:published_time" content="2026-04-29T17:00:00+03:00"></head><body>31.03.2026 dönemi Yönetim Kurulu Faaliyet Raporu</body></html>',
    }

    def fake_request_text(url: str, **_kwargs):
        for key, html in pages.items():
            if key in url:
                return html
        raise AssertionError(url)

    monkeypatch.setattr(loader, "_request_text", fake_request_text)

    records = sorted(loader.fetch_records("SILVR"), key=lambda row: row["period_end"])

    assert records == [
        {
            "symbol": "SILVR",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 5, 2),
            "announcement_source_url": "https://financialreports.eu/filings/silverline-endustri-ve-ticaret-as/report-publication-announcement/2023/6739916/",
        },
        {
            "symbol": "SILVR",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 9),
            "announcement_source_url": "https://financialreports.eu/filings/silverline-endustri-ve-ticaret-as/report-publication-announcement/2023/6719250/",
        },
        {
            "symbol": "SILVR",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/silverline-endustri-ve-ticaret-as/report-publication-announcement/2023/6704073/",
        },
        {
            "symbol": "SILVR",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 21),
            "announcement_source_url": "https://financialreports.eu/filings/silverline-endustri-ve-ticaret-as/report-publication-announcement/2024/6659114/",
        },
        {
            "symbol": "SILVR",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 11),
            "announcement_source_url": "https://financialreports.eu/filings/silverline-endustri-ve-ticaret-as/report-publication-announcement/2024/6651309/",
        },
        {
            "symbol": "SILVR",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 17),
            "announcement_source_url": "https://financialreports.eu/filings/silverline-endustri-ve-ticaret-as/report-publication-announcement/2024/6626891/",
        },
        {
            "symbol": "SILVR",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/silverline-endustri-ve-ticaret-as/report-publication-announcement/2024/6617683/",
        },
        {
            "symbol": "SILVR",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 4, 29),
            "announcement_source_url": "https://financialreports.eu/filings/silverline-endustri-ve-ticaret-as/report-publication-announcement/2026/38661174/",
        },
    ]


def test_fetchRecords_usesOncsmFinancialreportsFallback(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    pages = {
        "6737520": '<html><head><meta property="article:published_time" content="2023-05-08T17:00:00+03:00"></head><body>01.01.2023 - 31.03.2023 Faaliyet Raporu</body></html>',
        "6721493": '<html><head><meta property="article:published_time" content="2023-08-01T17:00:00+03:00"></head><body>Faaliyet Raporu - 30.06.2023</body></html>',
        "6702769": '<html><head><meta property="article:published_time" content="2023-11-03T17:00:00+03:00"></head><body>Faaliyet Raporu - 30.09.2023</body></html>',
        "6672125": '<html><head><meta property="article:published_time" content="2024-04-09T17:00:00+03:00"></head><body>01.01.2023 - 31.12.2023 Faaliyet Raporu</body></html>',
        "6648272": '<html><head><meta property="article:published_time" content="2024-06-20T17:00:00+03:00"></head><body>01.01.2024 - 31.03.2024 Faaliyet Raporu</body></html>',
        "6623861": '<html><head><meta property="article:published_time" content="2024-09-27T17:00:00+03:00"></head><body>Faaliyet Raporu - 30.06.2024</body></html>',
        "6615160": '<html><head><meta property="article:published_time" content="2024-11-08T17:00:00+03:00"></head><body>Faaliyet Raporu (30.09.2024)</body></html>',
        "38661174": '<html><head><meta property="article:published_time" content="2026-04-29T17:00:00+03:00"></head><body>31.03.2026 dönemi Yönetim Kurulu Faaliyet Raporu</body></html>',
    }

    def fake_request_text(url: str, **_kwargs):
        for key, html in pages.items():
            if key in url:
                return html
        raise AssertionError(url)

    monkeypatch.setattr(loader, "_request_text", fake_request_text)

    records = sorted(loader.fetch_records("ONCSM"), key=lambda row: row["period_end"])

    assert records == [
        {
            "symbol": "ONCSM",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 5, 8),
            "announcement_source_url": "https://financialreports.eu/filings/oncosem-onkolojik-sistemler-sanayi-ve-ticaret-as/report-publication-announcement/2023/6737520/",
        },
        {
            "symbol": "ONCSM",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 1),
            "announcement_source_url": "https://financialreports.eu/filings/oncosem-onkolojik-sistemler-sanayi-ve-ticaret-as/report-publication-announcement/2023/6721493/",
        },
        {
            "symbol": "ONCSM",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 3),
            "announcement_source_url": "https://financialreports.eu/filings/oncosem-onkolojik-sistemler-sanayi-ve-ticaret-as/report-publication-announcement/2023/6702769/",
        },
        {
            "symbol": "ONCSM",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 4, 9),
            "announcement_source_url": "https://financialreports.eu/filings/oncosem-onkolojik-sistemler-sanayi-ve-ticaret-as/report-publication-announcement/2024/6672125/",
        },
        {
            "symbol": "ONCSM",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 20),
            "announcement_source_url": "https://financialreports.eu/filings/oncosem-onkolojik-sistemler-sanayi-ve-ticaret-as/report-publication-announcement/2024/6648272/",
        },
        {
            "symbol": "ONCSM",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 27),
            "announcement_source_url": "https://financialreports.eu/filings/oncosem-onkolojik-sistemler-sanayi-ve-ticaret-as/report-publication-announcement/2024/6623861/",
        },
        {
            "symbol": "ONCSM",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 8),
            "announcement_source_url": "https://financialreports.eu/filings/oncosem-onkolojik-sistemler-sanayi-ve-ticaret-as/report-publication-announcement/2024/6615160/",
        },
        {
            "symbol": "ONCSM",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 4, 29),
            "announcement_source_url": "https://financialreports.eu/filings/oncosem-onkolojik-sistemler-sanayi-ve-ticaret-as/report-publication-announcement/2026/38661174/",
        },
    ]


def test_fetchRecords_usesIskplFinancialreportsFallback(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    pages = {
        "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2022/6834416/": """
        <html><head><meta property="article:published_time" content="2022-03-09T17:41:59+01:00"></head>
        <body><h1>Report Publication Announcement</h1></body></html>
        """,
        "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2022/6821644/": """
        <html><head><meta property="article:published_time" content="2022-04-26T19:14:27+02:00"></head>
        <body><h1>Report Publication Announcement</h1></body></html>
        """,
        "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2022/6793791/": """
        <html><head><meta property="article:published_time" content="2022-08-12T18:31:47+02:00"></head>
        <body><h1>Report Publication Announcement</h1></body></html>
        """,
        "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2022/6781606/": """
        <html><head><meta property="article:published_time" content="2022-11-03T17:05:50+01:00"></head>
        <body><h1>Report Publication Announcement</h1></body></html>
        """,
        "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2023/6736439/": """
        <html><head><meta property="article:published_time" content="2023-05-10T07:00:00Z"></head>
        <body><h1>Report Publication Announcement</h1></body></html>
        """,
        "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2023/6716775/": """
        <html><head><meta property="article:published_time" content="2023-08-16T07:00:00Z"></head>
        <body><h1>Report Publication Announcement</h1></body></html>
        """,
        "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2023/6701034/": """
        <html><head><meta property="article:published_time" content="2023-11-09T07:00:00Z"></head>
        <body><h1>Report Publication Announcement</h1></body></html>
        """,
        "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2024/6661315/": """
        <html><head><meta property="article:published_time" content="2024-05-16T07:00:00Z"></head>
        <body><h1>Report Publication Announcement</h1></body></html>
        """,
        "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2024/6648279/": """
        <html><head><meta property="article:published_time" content="2024-06-20T07:00:00Z"></head>
        <body><h1>Report Publication Announcement</h1></body></html>
        """,
        "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2024/6624743/": """
        <html><head><meta property="article:published_time" content="2024-09-25T07:00:00Z"></head>
        <body><h1>Report Publication Announcement</h1></body></html>
        """,
        "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2024/6614373/": """
        <html><head><meta property="article:published_time" content="2024-11-11T07:00:00Z"></head>
        <body><h1>Report Publication Announcement</h1></body></html>
        """,
    }
    monkeypatch.setattr(loader, "_request_text", lambda url, **_: pages[url])

    records = loader.fetch_records("ISKPL")

    assert records == [
        {
            "symbol": "ISKPL",
            "period_end": date(2021, 12, 1),
            "announcement_date": date(2022, 3, 9),
            "announcement_source_url": "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2022/6834416/",
        },
        {
            "symbol": "ISKPL",
            "period_end": date(2022, 3, 1),
            "announcement_date": date(2022, 4, 26),
            "announcement_source_url": "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2022/6821644/",
        },
        {
            "symbol": "ISKPL",
            "period_end": date(2022, 6, 1),
            "announcement_date": date(2022, 8, 12),
            "announcement_source_url": "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2022/6793791/",
        },
        {
            "symbol": "ISKPL",
            "period_end": date(2022, 9, 1),
            "announcement_date": date(2022, 11, 3),
            "announcement_source_url": "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2022/6781606/",
        },
        {
            "symbol": "ISKPL",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 5, 10),
            "announcement_source_url": "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2023/6736439/",
        },
        {
            "symbol": "ISKPL",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 16),
            "announcement_source_url": "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2023/6716775/",
        },
        {
            "symbol": "ISKPL",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 9),
            "announcement_source_url": "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2023/6701034/",
        },
        {
            "symbol": "ISKPL",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 16),
            "announcement_source_url": "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2024/6661315/",
        },
        {
            "symbol": "ISKPL",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 20),
            "announcement_source_url": "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2024/6648279/",
        },
        {
            "symbol": "ISKPL",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 25),
            "announcement_source_url": "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2024/6624743/",
        },
        {
            "symbol": "ISKPL",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 11),
            "announcement_source_url": "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2024/6614373/",
        },
        {
            "symbol": "ISKPL",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 5, 11),
            "announcement_source_url": "https://bigpara.hurriyet.com.tr/haberler/kap-haberleri/iskpl-isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as-finansal-rapor_ID3493402/",
        },
    ]


def test_fetchRecords_parsesKtskrOfficialInvestorPage(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    html = """
    <html><body>
      <a href="data/1_a.pdf">2023 YILI 3 AYLIK ARA DÖNEM FAALİYET RAPORU</a>
      <a href="data/faaliyet.pdf">2023 YILI 6 AYLIK ARA DÖNEM FAALİYET RAPORU</a>
      <a href="data/2023_faliyet9.pdf">2023 YILI 9 AYLIK ARA DÖNEM FAALİYET RAPORU</a>
      <a href="data/2023_faliyet12.pdf">2023 YILI 12 AYLIK ARA DÖNEM FAALİYET RAPORU</a>
      <a href="data/2024_3_1.pdf">2024 YILI 3 AYLIK ARA DÖNEM FAALİYET RAPORU</a>
      <a href="data/2024_3_2.pdf">2024 YILI 6 AYLIK ARA DÖNEM FAALİYET RAPORU</a>
      <a href="data/2024_3_3.pdf">2024 YILI 9 AYLIK ARA DÖNEM FAALİYET RAPORU</a>
      <a href="data/2026_1_1_1.pdf">2026 YILI 3 AYLIK ARA DÖNEM FAALİYET RAPORU</a>
    </body></html>
    """
    monkeypatch.setattr(loader, "_request_text", lambda *_, **__: html)
    publication_dates = iter(
        [
            date(2023, 5, 15),
            date(2023, 8, 11),
            date(2023, 11, 1),
            date(2024, 5, 13),
            date(2024, 6, 12),
            date(2024, 9, 20),
            date(2024, 11, 28),
            date(2026, 5, 4),
        ]
    )
    monkeypatch.setattr(loader, "_resolve_publication_date", lambda *_, **__: next(publication_dates))

    records = sorted(loader.fetch_records("KTSKR"), key=lambda row: row["period_end"])

    assert records == [
        {
            "symbol": "KTSKR",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 5, 15),
            "announcement_source_url": "https://kutahyaseker.com.tr/data/1_a.pdf",
        },
        {
            "symbol": "KTSKR",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 11),
            "announcement_source_url": "https://kutahyaseker.com.tr/data/faaliyet.pdf",
        },
        {
            "symbol": "KTSKR",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 1),
            "announcement_source_url": "https://kutahyaseker.com.tr/data/2023_faliyet9.pdf",
        },
        {
            "symbol": "KTSKR",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 13),
            "announcement_source_url": "https://kutahyaseker.com.tr/data/2023_faliyet12.pdf",
        },
        {
            "symbol": "KTSKR",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 12),
            "announcement_source_url": "https://kutahyaseker.com.tr/data/2024_3_1.pdf",
        },
        {
            "symbol": "KTSKR",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 20),
            "announcement_source_url": "https://kutahyaseker.com.tr/data/2024_3_2.pdf",
        },
        {
            "symbol": "KTSKR",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 28),
            "announcement_source_url": "https://kutahyaseker.com.tr/data/2024_3_3.pdf",
        },
        {
            "symbol": "KTSKR",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 5, 4),
            "announcement_source_url": "https://kutahyaseker.com.tr/data/2026_1_1_1.pdf",
        },
    ]


def test_pageUrlsForConfig_includesExtraPageUrls():
    loader = IssuerIRAnnouncementsLoader()
    config = IssuerIRSourceConfig(
        symbol="TEST",
        page_url="https://example.com/quarterly",
        extra_page_urls=("https://example.com/annual",),
    )

    assert loader._page_urls_for_config(config) == [
        "https://example.com/quarterly",
        "https://example.com/annual",
    ]


def test_request_supportsDisabledSslVerification(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    captured: dict[str, bool] = {}

    def fake_request(method, url, timeout, headers, allow_redirects, verify, data=None):
        captured["verify"] = verify
        return SimpleNamespace(
            raise_for_status=lambda: None,
            headers={},
            text="<html></html>",
        )

    monkeypatch.setattr("bist_factor_backtest.data.issuer_ir_announcements.requests.request", fake_request)

    loader._request("GET", "https://example.com/report.pdf", verify_ssl=False)

    assert captured["verify"] is False


def test_pageUrlsForConfig_supportsCustomYearParamName():
    loader = IssuerIRAnnouncementsLoader()
    config = IssuerIRSourceConfig(
        symbol="BLCYT",
        page_url="https://www.biliciyatirim.com/mali-tablolar",
        year_param=True,
        first_year=2024,
        year_param_name="yil",
    )

    urls = loader._page_urls_for_config(config)

    assert urls[0].startswith("https://www.biliciyatirim.com/mali-tablolar?yil=")
    assert urls[-1].endswith("yil=2024")


def test_parseHtml_usesAnchorTitleAsContextForYear(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    monkeypatch.setattr(loader, "_resolve_publication_date", lambda *_, **__: date(2024, 3, 10))
    html = """
    <html><body>
      <a href="https://www.biliciyatirim.com/pdf/example.pdf" title="2024">
        <div class="txt">PDF Görüntüle</div>
        <div class="head">12 Aylık Mali Tablolar</div>
      </a>
    </body></html>
    """

    records = loader.parse_html("BLCYT", html, "https://www.biliciyatirim.com/mali-tablolar")

    assert records == [
        {
            "symbol": "BLCYT",
            "period_end": date(2024, 12, 1),
            "announcement_date": date(2024, 3, 10),
            "announcement_source_url": "https://www.biliciyatirim.com/pdf/example.pdf",
        }
    ]


def test_parseHtml_handlesKutpoFinancialReports(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    monkeypatch.setattr(loader, "_resolve_publication_date", lambda *_, **__: date(2024, 6, 27))
    html = """
    <html><body>
      <a href="/uploads/2024/06/31-03-2024-bagimsiz-denetim-finansal-raporu.pdf">
        31-03-2024 Bağımsız Denetim Finansal Raporu
      </a>
    </body></html>
    """

    records = loader.parse_html(
        "KUTPO",
        html,
        "https://kurumsal.kutahyaporselen.com/tr/yatirimci-iliskileri/periyodik-mali-tablo-ve-raporlar",
        verify_ssl=False,
    )

    assert records == [
        {
            "symbol": "KUTPO",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 27),
            "announcement_source_url": "https://kurumsal.kutahyaporselen.com/uploads/2024/06/31-03-2024-bagimsiz-denetim-finansal-raporu.pdf",
        }
    ]


def test_parseHtml_handlesKrstlAutoindexFinancialReports(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    monkeypatch.setattr(loader, "_resolve_publication_date", lambda *_, **__: date(2024, 6, 20))
    html = """
    <html><body>
      <a href="/dokumanlar/mali-tablolar/2024/03/KRSTL_TMS_TFRS_Kons_31_03_2024.pdf">
        KRSTL_TMS_TFRS_Kons_31_03_2024.pdf
      </a>
    </body></html>
    """

    records = loader.parse_html(
        "KRSTL",
        html,
        "https://kristalkola.com.tr/dokumanlar/mali-tablolar/2024/03/",
        verify_ssl=False,
    )

    assert records == [
        {
            "symbol": "KRSTL",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 20),
            "announcement_source_url": "https://kristalkola.com.tr/dokumanlar/mali-tablolar/2024/03/KRSTL_TMS_TFRS_Kons_31_03_2024.pdf",
        }
    ]


def test_fetchRecords_handlesSelvaJsonEndpoint(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()

    def fake_request(method, url, verify_ssl=True, data=None):
        assert method == "POST"
        assert "GetFilterByYearwType" in url
        year = (data or {}).get("year")
        items = []
        if year == "2024":
            items = [
                {
                    "financeID": 44,
                    "financeName": "2024-03 Hesap Dönemine Ait Konsolide Finansal Tablolar ve Dipnotlar",
                    "financeFile": "selva-31032024-mali-tablo-ve-dipnotlar.pdf",
                    "financeDate": "2024-06-20T00:00:00",
                }
            ]
        return SimpleNamespace(json=lambda: items)

    monkeypatch.setattr(loader, "_request", fake_request)

    records = loader.fetch_records("SELVA")

    assert {
        "symbol": "SELVA",
        "period_end": date(2024, 3, 1),
        "announcement_date": date(2024, 6, 20),
        "announcement_source_url": "https://admin.selva.com.tr/Files/Finans/44/selva-31032024-mali-tablo-ve-dipnotlar.pdf",
    } in records


def test_parseHtml_handlesEksunFinancialReports(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    monkeypatch.setattr(loader, "_resolve_publication_date", lambda *_, **__: date(2024, 11, 11))
    html = """
    <html><body>
      <a href="/userfiles/docs/63866964611765465430092024FinansalRapor.pdf" target="_blank">
        <strong>30.09.2024 Tarihli Finansal Tablo ve Dipnotları</strong>
      </a>
    </body></html>
    """

    records = loader.parse_html(
        "EKSUN",
        html,
        "https://www.eksun.com.tr/yatirimci-iliskileri/finansal-raporlar-ve-sunumlar",
        verify_ssl=False,
    )

    assert records == [
        {
            "symbol": "EKSUN",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 11),
            "announcement_source_url": "https://www.eksun.com.tr/userfiles/docs/63866964611765465430092024FinansalRapor.pdf",
        }
    ]


def test_parseHtml_handlesCvkmdFinancialReports(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()
    monkeypatch.setattr(loader, "_resolve_publication_date", lambda *_, **__: date(2024, 11, 11))
    html = """
    <html><body>
      <a href="https://www.cvkmadencilik.com/uploads/files/pages/2024.09-konsolide-finansal-rapor-77.pdf">
        2024/09 Konsolide Finansal Rapor
      </a>
    </body></html>
    """

    records = loader.parse_html(
        "CVKMD",
        html,
        "https://www.cvkmadencilik.com/yatirimci-iliskileri/finansal-raporlar",
        verify_ssl=False,
    )

    assert records == [
        {
            "symbol": "CVKMD",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 11),
            "announcement_source_url": "https://www.cvkmadencilik.com/uploads/files/pages/2024.09-konsolide-finansal-rapor-77.pdf",
        }
    ]


def test_fetchRecords_handlesYylgdFinancialreportsFallback(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()

    publication_dates = {
        "https://financialreports.eu/filings/yayla-agro-gida-sanayi-ve-ticaret-as/report-publication-announcement/2023/6734516/": date(2023, 5, 15),
        "https://financialreports.eu/filings/yayla-agro-gida-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6719711/": date(2023, 8, 8),
        "https://financialreports.eu/filings/yayla-agro-gida-sanayi-ve-ticaret-as/report-publication-announcement/2023/6705747/": date(2023, 10, 24),
        "https://financialreports.eu/filings/yayla-agro-gida-sanayi-ve-ticaret-as/report-publication-announcement/2024/6666007/": date(2024, 5, 6),
        "https://financialreports.eu/filings/6662132/content/": date(2024, 5, 14),
        "https://financialreports.eu/filings/6627740/content/": date(2024, 9, 13),
        "https://financialreports.eu/filings/yayla-agro-gida-sanayi-ve-ticaret-as/report-publication-announcement/2024/6621683/": date(2024, 11, 8),
        "https://financialreports.eu/filings/yayla-agro-gida-sanayi-ve-ticaret-as/report-publication-announcement/2026/8243505/": date(2026, 4, 29),
    }

    monkeypatch.setattr(
        "bist_factor_backtest.data.issuer_ir_announcements._extract_financialreports_published_date",
        lambda soup: publication_dates[soup._page_url],
    )
    monkeypatch.setattr(
        "bist_factor_backtest.data.issuer_ir_announcements.BeautifulSoup",
        lambda html, parser, **kwargs: SimpleNamespace(_page_url=html),
    )
    monkeypatch.setattr(loader, "_request_text", lambda url, verify_ssl=True: url)
    records = loader.fetch_records("YYLGD")

    assert records == [
        {
            "symbol": "YYLGD",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 5, 15),
            "announcement_source_url": "https://financialreports.eu/filings/yayla-agro-gida-sanayi-ve-ticaret-as/report-publication-announcement/2023/6734516/",
        },
        {
            "symbol": "YYLGD",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 8),
            "announcement_source_url": "https://financialreports.eu/filings/yayla-agro-gida-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6719711/",
        },
        {
            "symbol": "YYLGD",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 24),
            "announcement_source_url": "https://financialreports.eu/filings/yayla-agro-gida-sanayi-ve-ticaret-as/report-publication-announcement/2023/6705747/",
        },
        {
            "symbol": "YYLGD",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 6),
            "announcement_source_url": "https://financialreports.eu/filings/yayla-agro-gida-sanayi-ve-ticaret-as/report-publication-announcement/2024/6666007/",
        },
        {
            "symbol": "YYLGD",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 5, 14),
            "announcement_source_url": "https://financialreports.eu/filings/6662132/content/",
        },
        {
            "symbol": "YYLGD",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 13),
            "announcement_source_url": "https://financialreports.eu/filings/6627740/content/",
        },
        {
            "symbol": "YYLGD",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 8),
            "announcement_source_url": "https://financialreports.eu/filings/yayla-agro-gida-sanayi-ve-ticaret-as/report-publication-announcement/2024/6621683/",
        },
        {
            "symbol": "YYLGD",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 4, 29),
            "announcement_source_url": "https://financialreports.eu/filings/yayla-agro-gida-sanayi-ve-ticaret-as/report-publication-announcement/2026/8243505/",
        },
    ]


def test_fetchRecords_handlesHktmFinancialreportsFallback(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()

    publication_dates = {
        "https://financialreports.eu/filings/hidropar-hareket-kontrol-teknolojileri-merkezi-sanayi-ve-ticaret-as/audit-report-information/2024/6661795/": date(2024, 5, 15),
        "https://financialreports.eu/filings/hidropar-hareket-kontrol-teknolojileri-merkezi-sanayi-ve-ticaret-as/annual-report/2024/6648941/": date(2024, 6, 14),
        "https://financialreports.eu/filings/6624330/content/": date(2024, 9, 26),
        "https://financialreports.eu/filings/6614020/content/": date(2024, 11, 11),
        "https://financialreports.eu/filings/hidropar-hareket-kontrol-teknolojileri-merkezi-sanayi-ve-ticaret-as/regulatory-filings/2026/43132006/": date(2026, 5, 7),
    }

    monkeypatch.setattr(
        "bist_factor_backtest.data.issuer_ir_announcements._extract_financialreports_published_date",
        lambda soup: publication_dates[soup._page_url],
    )
    monkeypatch.setattr(
        "bist_factor_backtest.data.issuer_ir_announcements.BeautifulSoup",
        lambda html, parser, **kwargs: SimpleNamespace(_page_url=html),
    )
    monkeypatch.setattr(loader, "_request_text", lambda url, verify_ssl=True: url)

    records = loader.fetch_records("HKTM")

    assert records == [
        {
            "symbol": "HKTM",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 15),
            "announcement_source_url": "https://financialreports.eu/filings/hidropar-hareket-kontrol-teknolojileri-merkezi-sanayi-ve-ticaret-as/audit-report-information/2024/6661795/",
        },
        {
            "symbol": "HKTM",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 14),
            "announcement_source_url": "https://financialreports.eu/filings/hidropar-hareket-kontrol-teknolojileri-merkezi-sanayi-ve-ticaret-as/annual-report/2024/6648941/",
        },
        {
            "symbol": "HKTM",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 26),
            "announcement_source_url": "https://financialreports.eu/filings/6624330/content/",
        },
        {
            "symbol": "HKTM",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 11),
            "announcement_source_url": "https://financialreports.eu/filings/6614020/content/",
        },
        {
            "symbol": "HKTM",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 5, 7),
            "announcement_source_url": "https://financialreports.eu/filings/hidropar-hareket-kontrol-teknolojileri-merkezi-sanayi-ve-ticaret-as/regulatory-filings/2026/43132006/",
        },
    ]


def test_fetchRecords_handlesImasmFinancialreportsFallback(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()

    publication_dates = {
        "https://financialreports.eu/filings/imas-makina-sanayi-as/interim-quarterly-report/2023/6719392/": date(2023, 8, 9),
        "https://financialreports.eu/filings/imas-makina-sanayi-as/interim-quarterly-report/2023/6703629/": date(2023, 10, 31),
        "https://financialreports.eu/filings/imas-makina-sanayi-as/interim-quarterly-report/2024/6675716/": date(2024, 3, 27),
        "https://financialreports.eu/filings/imas-makina-sanayi-as/interim-quarterly-report/2024/6648226/": date(2024, 6, 20),
        "https://financialreports.eu/filings/imas-makina-sanayi-as/report-publication-announcement/2024/6626690/": date(2024, 9, 18),
        "https://financialreports.eu/filings/imas-makina-sanayi-as/report-publication-announcement/2024/6615634/": date(2024, 11, 8),
        "https://financialreports.eu/filings/imas-makina-sanayi-as/report-publication-announcement/2026/32932268/": date(2026, 3, 11),
    }

    monkeypatch.setattr(
        "bist_factor_backtest.data.issuer_ir_announcements._extract_financialreports_published_date",
        lambda soup: publication_dates[soup._page_url],
    )
    monkeypatch.setattr(
        "bist_factor_backtest.data.issuer_ir_announcements.BeautifulSoup",
        lambda html, parser, **kwargs: SimpleNamespace(_page_url=html),
    )
    monkeypatch.setattr(loader, "_request_text", lambda url, verify_ssl=True: url)

    records = loader.fetch_records("IMASM")

    assert records == [
        {
            "symbol": "IMASM",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 9),
            "announcement_source_url": "https://financialreports.eu/filings/imas-makina-sanayi-as/interim-quarterly-report/2023/6719392/",
        },
        {
            "symbol": "IMASM",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 31),
            "announcement_source_url": "https://financialreports.eu/filings/imas-makina-sanayi-as/interim-quarterly-report/2023/6703629/",
        },
        {
            "symbol": "IMASM",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 3, 27),
            "announcement_source_url": "https://financialreports.eu/filings/imas-makina-sanayi-as/interim-quarterly-report/2024/6675716/",
        },
        {
            "symbol": "IMASM",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 20),
            "announcement_source_url": "https://financialreports.eu/filings/imas-makina-sanayi-as/interim-quarterly-report/2024/6648226/",
        },
        {
            "symbol": "IMASM",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 18),
            "announcement_source_url": "https://financialreports.eu/filings/imas-makina-sanayi-as/report-publication-announcement/2024/6626690/",
        },
        {
            "symbol": "IMASM",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 8),
            "announcement_source_url": "https://financialreports.eu/filings/imas-makina-sanayi-as/report-publication-announcement/2024/6615634/",
        },
        {
            "symbol": "IMASM",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 3, 11),
            "announcement_source_url": "https://financialreports.eu/filings/imas-makina-sanayi-as/report-publication-announcement/2026/32932268/",
        },
    ]


def test_fetchRecords_handlesAcselFinancialreportsFallback(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()

    publication_dates = {
        "https://financialreports.eu/filings/aciselsan-acipayam-seluloz-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6721056/": date(2023, 8, 3),
        "https://financialreports.eu/filings/aciselsan-acipayam-seluloz-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6706227/": date(2023, 10, 20),
        "https://financialreports.eu/filings/aciselsan-acipayam-seluloz-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6667790/": date(2024, 4, 30),
        "https://financialreports.eu/filings/aciselsan-acipayam-seluloz-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6651272/": date(2024, 6, 11),
        "https://financialreports.eu/filings/aciselsan-acipayam-seluloz-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6633749/": date(2024, 8, 19),
        "https://financialreports.eu/filings/aciselsan-acipayam-seluloz-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6618190/": date(2024, 10, 30),
        "https://financialreports.eu/filings/aciselsan-acipayam-seluloz-sanayi-ve-ticaret-as/annual-report/2026/32866652/": date(2026, 3, 2),
    }

    monkeypatch.setattr(
        "bist_factor_backtest.data.issuer_ir_announcements._extract_financialreports_published_date",
        lambda soup: publication_dates[soup._page_url],
    )
    monkeypatch.setattr(
        "bist_factor_backtest.data.issuer_ir_announcements.BeautifulSoup",
        lambda html, parser, **kwargs: SimpleNamespace(_page_url=html),
    )
    monkeypatch.setattr(loader, "_request_text", lambda url, verify_ssl=True: url)

    records = loader.fetch_records("ACSEL")

    assert records == [
        {
            "symbol": "ACSEL",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 3),
            "announcement_source_url": "https://financialreports.eu/filings/aciselsan-acipayam-seluloz-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6721056/",
        },
        {
            "symbol": "ACSEL",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 20),
            "announcement_source_url": "https://financialreports.eu/filings/aciselsan-acipayam-seluloz-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6706227/",
        },
        {
            "symbol": "ACSEL",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 4, 30),
            "announcement_source_url": "https://financialreports.eu/filings/aciselsan-acipayam-seluloz-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6667790/",
        },
        {
            "symbol": "ACSEL",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 11),
            "announcement_source_url": "https://financialreports.eu/filings/aciselsan-acipayam-seluloz-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6651272/",
        },
        {
            "symbol": "ACSEL",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 8, 19),
            "announcement_source_url": "https://financialreports.eu/filings/aciselsan-acipayam-seluloz-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6633749/",
        },
        {
            "symbol": "ACSEL",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/aciselsan-acipayam-seluloz-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6618190/",
        },
        {
            "symbol": "ACSEL",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 3, 2),
            "announcement_source_url": "https://financialreports.eu/filings/aciselsan-acipayam-seluloz-sanayi-ve-ticaret-as/annual-report/2026/32866652/",
        },
    ]


def test_fetchRecords_handlesBlumeMetemturFinancialreportsFallback(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()

    publication_dates = {
        "https://financialreports.eu/filings/metemtur-yatirim-enerji-turizm-ve-insaat-as/interim-quarterly-report/2023/6717872/": date(2023, 8, 11),
        "https://financialreports.eu/filings/metemtur-yatirim-enerji-turizm-ve-insaat-as/interim-quarterly-report/2023/6703000/": date(2023, 11, 2),
        "https://financialreports.eu/filings/metemtur-yatirim-enerji-turizm-ve-insaat-as/annual-report/2024/6677283/": date(2024, 3, 21),
        "https://financialreports.eu/filings/metemtur-yatirim-enerji-turizm-ve-insaat-as/interim-quarterly-report/2024/6653686/": date(2024, 6, 4),
        "https://financialreports.eu/filings/metemtur-yatirim-enerji-turizm-ve-insaat-as/interim-quarterly-report/2024/6629336/": date(2024, 9, 9),
        "https://financialreports.eu/filings/metemtur-yatirim-enerji-turizm-ve-insaat-as/interim-quarterly-report/2024/6615163/": date(2024, 11, 8),
    }

    monkeypatch.setattr(
        "bist_factor_backtest.data.issuer_ir_announcements._extract_financialreports_published_date",
        lambda soup: publication_dates[soup._page_url],
    )
    monkeypatch.setattr(
        "bist_factor_backtest.data.issuer_ir_announcements.BeautifulSoup",
        lambda html, parser, **kwargs: SimpleNamespace(_page_url=html),
    )
    monkeypatch.setattr(loader, "_request_text", lambda url, verify_ssl=True: url)

    records = loader.fetch_records("BLUME")

    assert records == [
        {
            "symbol": "BLUME",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 11),
            "announcement_source_url": "https://financialreports.eu/filings/metemtur-yatirim-enerji-turizm-ve-insaat-as/interim-quarterly-report/2023/6717872/",
        },
        {
            "symbol": "BLUME",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 2),
            "announcement_source_url": "https://financialreports.eu/filings/metemtur-yatirim-enerji-turizm-ve-insaat-as/interim-quarterly-report/2023/6703000/",
        },
        {
            "symbol": "BLUME",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 3, 21),
            "announcement_source_url": "https://financialreports.eu/filings/metemtur-yatirim-enerji-turizm-ve-insaat-as/annual-report/2024/6677283/",
        },
        {
            "symbol": "BLUME",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 4),
            "announcement_source_url": "https://financialreports.eu/filings/metemtur-yatirim-enerji-turizm-ve-insaat-as/interim-quarterly-report/2024/6653686/",
        },
        {
            "symbol": "BLUME",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 9),
            "announcement_source_url": "https://financialreports.eu/filings/metemtur-yatirim-enerji-turizm-ve-insaat-as/interim-quarterly-report/2024/6629336/",
        },
        {
            "symbol": "BLUME",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 8),
            "announcement_source_url": "https://financialreports.eu/filings/metemtur-yatirim-enerji-turizm-ve-insaat-as/interim-quarterly-report/2024/6615163/",
        },
    ]


def test_fetchRecords_handlesBurceFinancialreportsFallback(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()

    publication_dates = {
        "https://financialreports.eu/filings/burcelik-bursa-celik-dokum-sanayii-as/interim-quarterly-report/2023/6715537/": date(2023, 8, 18),
        "https://financialreports.eu/filings/burcelik-bursa-celik-dokum-sanayii-as/interim-quarterly-report/2023/6700882/": date(2023, 11, 9),
        "https://financialreports.eu/filings/burcelik-bursa-celik-dokum-sanayii-as/annual-report/2024/6666115/": date(2024, 5, 6),
        "https://financialreports.eu/filings/burcelik-bursa-celik-dokum-sanayii-as/interim-quarterly-report/2024/6648097/": date(2024, 6, 20),
        "https://financialreports.eu/filings/burcelik-bursa-celik-dokum-sanayii-as/interim-quarterly-report/2024/6623389/": date(2024, 9, 30),
        "https://financialreports.eu/filings/burcelik-bursa-celik-dokum-sanayii-as/interim-quarterly-report/2024/6614442/": date(2024, 11, 11),
        "https://financialreports.eu/filings/burcelik-bursa-celik-dokum-sanayii-as/regulatory-filings/2026/36131474/": date(2026, 4, 24),
    }

    monkeypatch.setattr(
        "bist_factor_backtest.data.issuer_ir_announcements._extract_financialreports_published_date",
        lambda soup: publication_dates[soup._page_url],
    )
    monkeypatch.setattr(
        "bist_factor_backtest.data.issuer_ir_announcements.BeautifulSoup",
        lambda html, parser, **kwargs: SimpleNamespace(_page_url=html),
    )
    monkeypatch.setattr(loader, "_request_text", lambda url, verify_ssl=True: url)

    records = loader.fetch_records("BURCE")

    assert records == [
        {
            "symbol": "BURCE",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 18),
            "announcement_source_url": "https://financialreports.eu/filings/burcelik-bursa-celik-dokum-sanayii-as/interim-quarterly-report/2023/6715537/",
        },
        {
            "symbol": "BURCE",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 9),
            "announcement_source_url": "https://financialreports.eu/filings/burcelik-bursa-celik-dokum-sanayii-as/interim-quarterly-report/2023/6700882/",
        },
        {
            "symbol": "BURCE",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 6),
            "announcement_source_url": "https://financialreports.eu/filings/burcelik-bursa-celik-dokum-sanayii-as/annual-report/2024/6666115/",
        },
        {
            "symbol": "BURCE",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 20),
            "announcement_source_url": "https://financialreports.eu/filings/burcelik-bursa-celik-dokum-sanayii-as/interim-quarterly-report/2024/6648097/",
        },
        {
            "symbol": "BURCE",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 30),
            "announcement_source_url": "https://financialreports.eu/filings/burcelik-bursa-celik-dokum-sanayii-as/interim-quarterly-report/2024/6623389/",
        },
        {
            "symbol": "BURCE",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 11),
            "announcement_source_url": "https://financialreports.eu/filings/burcelik-bursa-celik-dokum-sanayii-as/interim-quarterly-report/2024/6614442/",
        },
        {
            "symbol": "BURCE",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 4, 24),
            "announcement_source_url": "https://financialreports.eu/filings/burcelik-bursa-celik-dokum-sanayii-as/regulatory-filings/2026/36131474/",
        },
    ]


def test_fetchRecords_handlesBurvaFinancialreportsFallback(monkeypatch):
    loader = IssuerIRAnnouncementsLoader()

    publication_dates = {
        "https://financialreports.eu/filings/burcelik-vana-sanayi-ve-ticaret-as/report-publication-announcement/2023/6718973/": date(2023, 8, 9),
        "https://financialreports.eu/filings/burcelik-vana-sanayi-ve-ticaret-as/audit-report-information/2023/6704106/": date(2023, 10, 30),
        "https://financialreports.eu/filings/6665973/content/": date(2024, 5, 6),
        "https://financialreports.eu/filings/6650915/content/": date(2024, 6, 11),
        "https://financialreports.eu/filings/6627811/content/": date(2024, 9, 13),
        "https://financialreports.eu/filings/burcelik-vana-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6618004/": date(2024, 10, 30),
    }

    monkeypatch.setattr(
        "bist_factor_backtest.data.issuer_ir_announcements._extract_financialreports_published_date",
        lambda soup: publication_dates[soup._page_url],
    )
    monkeypatch.setattr(
        "bist_factor_backtest.data.issuer_ir_announcements.BeautifulSoup",
        lambda html, parser, **kwargs: SimpleNamespace(_page_url=html),
    )
    monkeypatch.setattr(loader, "_request_text", lambda url, verify_ssl=True: url)

    records = loader.fetch_records("BURVA")

    assert records == [
        {
            "symbol": "BURVA",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 9),
            "announcement_source_url": "https://financialreports.eu/filings/burcelik-vana-sanayi-ve-ticaret-as/report-publication-announcement/2023/6718973/",
        },
        {
            "symbol": "BURVA",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/burcelik-vana-sanayi-ve-ticaret-as/audit-report-information/2023/6704106/",
        },
        {
            "symbol": "BURVA",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 6),
            "announcement_source_url": "https://financialreports.eu/filings/6665973/content/",
        },
        {
            "symbol": "BURVA",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 11),
            "announcement_source_url": "https://financialreports.eu/filings/6650915/content/",
        },
        {
            "symbol": "BURVA",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 13),
            "announcement_source_url": "https://financialreports.eu/filings/6627811/content/",
        },
        {
            "symbol": "BURVA",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/burcelik-vana-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6618004/",
        },
    ]


def test_fetchRecords_handlesKopolFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("KOPOL")

    assert records == [
        {
            "symbol": "KOPOL",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 9),
            "announcement_source_url": "https://financialreports.eu/filings/koza-polyester-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6718876/",
        },
        {
            "symbol": "KOPOL",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/koza-polyester-sanayi-ve-ticaret-as/report-publication-announcement/2023/6704320/",
        },
        {
            "symbol": "KOPOL",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 2, 29),
            "announcement_source_url": "https://financialreports.eu/filings/koza-polyester-sanayi-ve-ticaret-as/audit-report-information/2024/6678474/",
        },
        {
            "symbol": "KOPOL",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 4, 30),
            "announcement_source_url": "https://financialreports.eu/filings/6667515/content/",
        },
        {
            "symbol": "KOPOL",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 8, 8),
            "announcement_source_url": "https://financialreports.eu/filings/6636072/content/",
        },
        {
            "symbol": "KOPOL",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/6617840/content/",
        },
    ]


def test_fetchRecords_handlesDardlFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("DARDL")

    assert records == [
        {
            "symbol": "DARDL",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 5, 10),
            "announcement_source_url": "https://financialreports.eu/filings/dardanel-onentas-gida-sanayi-as/annual-quarterly-financial-statement/2023/6736161/",
        },
        {
            "symbol": "DARDL",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 21),
            "announcement_source_url": "https://financialreports.eu/filings/6715291/content/",
        },
        {
            "symbol": "DARDL",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 9),
            "announcement_source_url": "https://financialreports.eu/filings/dardanel-onentas-gida-sanayi-as/report-publication-announcement/2023/6700737/",
        },
        {
            "symbol": "DARDL",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 5, 22),
            "announcement_source_url": "https://financialreports.eu/filings/dardanel-onentas-gida-sanayi-as/interim-quarterly-report/2024/6658344/",
        },
        {
            "symbol": "DARDL",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 10, 4),
            "announcement_source_url": "https://financialreports.eu/filings/dardanel-onentas-gida-sanayi-as/interim-quarterly-report/2024/6621827/",
        },
        {
            "symbol": "DARDL",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 11),
            "announcement_source_url": "https://financialreports.eu/filings/dardanel-onentas-gida-sanayi-as/report-publication-announcement/2024/6614140/",
        },
        {
            "symbol": "DARDL",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 3, 11),
            "announcement_source_url": "https://financialreports.eu/filings/dardanel-onentas-gida-sanayi-as/interim-quarterly-report/2026/32931685/",
        },
    ]


def test_fetchRecords_handlesDoktaFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("DOKTA")

    assert records == [
        {
            "symbol": "DOKTA",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 3, 9),
            "announcement_source_url": "https://financialreports.eu/filings/doktas-dokumculuk-ticaret-ve-sanayi-as/interim-quarterly-report/2026/32919101/",
        },
    ]


def test_fetchRecords_handlesBntasOfficialAndFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("BNTAS")

    assert records == [
        {
            "symbol": "BNTAS",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 4, 29),
            "announcement_source_url": "https://www.bantas.com.tr/wp-content/uploads/2023/04/FaaliyetRaporu.pdf",
        },
        {
            "symbol": "BNTAS",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 4, 29),
            "announcement_source_url": "https://financialreports.eu/filings/bantas-bandirma-ambalaj-sanayi-ticaret-as/report-publication-announcement/2026/38656829/",
        },
    ]


def test_fetchRecords_handlesDagiFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("DAGI")

    assert records == [
        {
            "symbol": "DAGI",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 5, 10),
            "announcement_source_url": "https://financialreports.eu/filings/dagi-giyim-sanayi-ve-ticaret-as/report-publication-announcement/2023/6736234/",
        },
        {
            "symbol": "DAGI",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 18),
            "announcement_source_url": "https://financialreports.eu/filings/dagi-giyim-sanayi-ve-ticaret-as/report-publication-announcement/2023/6715321/",
        },
        {
            "symbol": "DAGI",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 9),
            "announcement_source_url": "https://financialreports.eu/filings/dagi-giyim-sanayi-ve-ticaret-as/report-publication-announcement/2023/6701209/",
        },
        {
            "symbol": "DAGI",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 4, 26),
            "announcement_source_url": "https://financialreports.eu/filings/dagi-giyim-sanayi-ve-ticaret-as/report-publication-announcement/2024/6668750/",
        },
        {
            "symbol": "DAGI",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 7),
            "announcement_source_url": "https://financialreports.eu/filings/dagi-giyim-sanayi-ve-ticaret-as/report-publication-announcement/2024/6652092/",
        },
        {
            "symbol": "DAGI",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 8, 23),
            "announcement_source_url": "https://financialreports.eu/filings/dagi-giyim-sanayi-ve-ticaret-as/report-publication-announcement/2024/6632483/",
        },
        {
            "symbol": "DAGI",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 8),
            "announcement_source_url": "https://financialreports.eu/filings/dagi-giyim-sanayi-ve-ticaret-as/report-publication-announcement/2024/6615320/",
        },
        {
            "symbol": "DAGI",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 3, 11),
            "announcement_source_url": "https://financialreports.eu/filings/dagi-giyim-sanayi-ve-ticaret-as/report-publication-announcement/2026/32930519/",
        },
    ]


def test_fetchRecords_handlesGubrfOfficialPdfDates():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("GUBRF")

    assert records == [
        {
            "symbol": "GUBRF",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 19),
            "announcement_source_url": "https://www.gubretas.com.tr/uploads/files/pages/gubretas-rapor-spk-30.06.2023-287.pdf",
        },
        {
            "symbol": "GUBRF",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 4, 8),
            "announcement_source_url": "https://www.gubretas.com.tr/uploads/files/pages/gubretas-rapor-spk-31.12.2023-842.pdf",
        },
        {
            "symbol": "GUBRF",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 20),
            "announcement_source_url": "https://www.gubretas.com.tr/uploads/files/pages/31-mart-2024-finansal-tablo-ve-dipnotlar-899.pdf",
        },
        {
            "symbol": "GUBRF",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 25),
            "announcement_source_url": "https://www.gubretas.com.tr/uploads/files/pages/30-haziran-2024-finansal-tablo-ve-dipnotlar-928.pdf",
        },
    ]


def test_fetchRecords_handlesGiptaFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("GIPTA")

    assert records == [
        {
            "symbol": "GIPTA",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 27),
            "announcement_source_url": "https://financialreports.eu/filings/gipta-ofis-kirtasiye-ve-promosyon-urunleri-imalat-sanayi-as/interim-quarterly-report/2023/6705005/",
        },
        {
            "symbol": "GIPTA",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 3),
            "announcement_source_url": "https://financialreports.eu/filings/gipta-ofis-kirtasiye-ve-promosyon-urunleri-imalat-sanayi-as/interim-quarterly-report/2024/6666776/",
        },
        {
            "symbol": "GIPTA",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 11),
            "announcement_source_url": "https://financialreports.eu/filings/gipta-ofis-kirtasiye-ve-promosyon-urunleri-imalat-sanayi-as/interim-quarterly-report/2024/6650972/",
        },
        {
            "symbol": "GIPTA",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 8, 19),
            "announcement_source_url": "https://financialreports.eu/filings/gipta-ofis-kirtasiye-ve-promosyon-urunleri-imalat-sanayi-as/interim-quarterly-report/2024/6633672/",
        },
        {
            "symbol": "GIPTA",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/gipta-ofis-kirtasiye-ve-promosyon-urunleri-imalat-sanayi-as/interim-quarterly-report/2024/6617617/",
        },
    ]


def test_fetchRecords_handlesTatgdFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("TATGD")

    assert records == [
        {
            "symbol": "TATGD",
            "period_end": date(2019, 3, 1),
            "announcement_date": date(2019, 4, 27),
            "announcement_source_url": "https://financialreports.eu/filings/tat-gida-sanayi-as/interim-quarterly-report/2019/6992412/",
        },
        {
            "symbol": "TATGD",
            "period_end": date(2019, 6, 1),
            "announcement_date": date(2019, 8, 7),
            "announcement_source_url": "https://financialreports.eu/filings/tat-gida-sanayi-as/interim-quarterly-report/2019/6978065/",
        },
        {
            "symbol": "TATGD",
            "period_end": date(2019, 9, 1),
            "announcement_date": date(2019, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/tat-gida-sanayi-as/interim-quarterly-report/2019/6968857/",
        },
        {
            "symbol": "TATGD",
            "period_end": date(2019, 12, 1),
            "announcement_date": date(2020, 2, 12),
            "announcement_source_url": "https://financialreports.eu/filings/tat-gida-sanayi-as/interim-quarterly-report/2020/6956910/",
        },
        {
            "symbol": "TATGD",
            "period_end": date(2020, 3, 1),
            "announcement_date": date(2020, 5, 14),
            "announcement_source_url": "https://financialreports.eu/filings/tat-gida-sanayi-as/interim-quarterly-report/2020/6940168/",
        },
        {
            "symbol": "TATGD",
            "period_end": date(2020, 6, 1),
            "announcement_date": date(2020, 8, 6),
            "announcement_source_url": "https://financialreports.eu/filings/tat-gida-sanayi-as/interim-quarterly-report/2020/6927225/",
        },
    ]


def test_fetchRecords_handlesDoferFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("DOFER")

    assert records == [
        {
            "symbol": "DOFER",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 6),
            "announcement_source_url": "https://financialreports.eu/filings/dofer-yapi-malzemeleri-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6665721/",
        },
        {
            "symbol": "DOFER",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 11),
            "announcement_source_url": "https://financialreports.eu/filings/dofer-yapi-malzemeleri-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6650533/",
        },
        {
            "symbol": "DOFER",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 18),
            "announcement_source_url": "https://financialreports.eu/filings/dofer-yapi-malzemeleri-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6626754/",
        },
        {
            "symbol": "DOFER",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 10, 28),
            "announcement_source_url": "https://financialreports.eu/filings/dofer-yapi-malzemeleri-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6618352/",
        },
        {
            "symbol": "DOFER",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 4, 29),
            "announcement_source_url": "https://financialreports.eu/filings/dofer-yapi-malzemeleri-sanayi-ve-ticaret-as/interim-quarterly-report/2026/38655889/",
        },
    ]


def test_fetchRecords_handlesAgrotFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("AGROT")

    assert records == [
        {
            "symbol": "AGROT",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 4, 16),
            "announcement_source_url": "https://financialreports.eu/filings/agrotech-yuksek-teknoloji-ve-yatirim-as/interim-quarterly-report/2024/6671612/",
        },
        {
            "symbol": "AGROT",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 4, 17),
            "announcement_source_url": "https://financialreports.eu/filings/agrotech-yuksek-teknoloji-ve-yatirim-as/interim-quarterly-report/2024/6670897/",
        },
        {
            "symbol": "AGROT",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 27),
            "announcement_source_url": "https://financialreports.eu/filings/agrotech-yuksek-teknoloji-ve-yatirim-as/interim-quarterly-report/2024/6624190/",
        },
        {
            "symbol": "AGROT",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 11),
            "announcement_source_url": "https://financialreports.eu/filings/agrotech-yuksek-teknoloji-ve-yatirim-as/interim-quarterly-report/2024/6614217/",
        },
        {
            "symbol": "AGROT",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 3, 11),
            "announcement_source_url": "https://financialreports.eu/filings/agrotech-yuksek-teknoloji-ve-yatirim-as/interim-quarterly-report/2026/32932166/",
        },
    ]


def test_fetchRecords_handlesEkosFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("EKOS")

    assert records == [
        {
            "symbol": "EKOS",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 10),
            "announcement_source_url": "https://financialreports.eu/filings/ekos-teknoloji-ve-elektrik-as/interim-quarterly-report/2024/6663344/",
        },
        {
            "symbol": "EKOS",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 21),
            "announcement_source_url": "https://financialreports.eu/filings/ekos-teknoloji-ve-elektrik-as/interim-quarterly-report/2024/6647209/",
        },
        {
            "symbol": "EKOS",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 27),
            "announcement_source_url": "https://financialreports.eu/filings/ekos-teknoloji-ve-elektrik-as/interim-quarterly-report/2024/6624054/",
        },
        {
            "symbol": "EKOS",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 9),
            "announcement_source_url": "https://financialreports.eu/filings/ekos-teknoloji-ve-elektrik-as/interim-quarterly-report/2024/6614987/",
        },
        {
            "symbol": "EKOS",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 3, 11),
            "announcement_source_url": "https://financialreports.eu/filings/ekos-teknoloji-ve-elektrik-as/interim-quarterly-report/2026/32930742/",
        },
    ]


def test_fetchRecords_handlesMegmtFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("MEGMT")

    assert records == [
        {
            "symbol": "MEGMT",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 2, 23),
            "announcement_source_url": "https://financialreports.eu/filings/mega-metal-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6683050/",
        },
        {
            "symbol": "MEGMT",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 4, 30),
            "announcement_source_url": "https://financialreports.eu/filings/mega-metal-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6667236/",
        },
        {
            "symbol": "MEGMT",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 8, 14),
            "announcement_source_url": "https://financialreports.eu/filings/mega-metal-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6634706/",
        },
        {
            "symbol": "MEGMT",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 4),
            "announcement_source_url": "https://financialreports.eu/filings/mega-metal-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6616787/",
        },
        {
            "symbol": "MEGMT",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 3, 5),
            "announcement_source_url": "https://financialreports.eu/filings/mega-metal-sanayi-ve-ticaret-as/interim-quarterly-report/2026/32904875/",
        },
    ]


def test_fetchRecords_handlesMekagFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("MEKAG")

    assert records == [
        {
            "symbol": "MEKAG",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 4, 25),
            "announcement_source_url": "https://financialreports.eu/filings/meka-global-makine-imalat-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6669069/",
        },
        {
            "symbol": "MEKAG",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 14),
            "announcement_source_url": "https://financialreports.eu/filings/meka-global-makine-imalat-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6649105/",
        },
        {
            "symbol": "MEKAG",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 26),
            "announcement_source_url": "https://financialreports.eu/filings/meka-global-makine-imalat-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6624301/",
        },
        {
            "symbol": "MEKAG",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 22),
            "announcement_source_url": "https://financialreports.eu/filings/meka-global-makine-imalat-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6611862/",
        },
        {
            "symbol": "MEKAG",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 3, 6),
            "announcement_source_url": "https://financialreports.eu/filings/meka-global-makine-imalat-sanayi-ve-ticaret-as/interim-quarterly-report/2026/32909378/",
        },
    ]


def test_fetchRecords_handlesKboruFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("KBORU")

    assert records == [
        {
            "symbol": "KBORU",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 2, 29),
            "announcement_source_url": "https://financialreports.eu/filings/kuzey-boru-as/interim-quarterly-report/2024/6681327/",
        },
        {
            "symbol": "KBORU",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 7),
            "announcement_source_url": "https://financialreports.eu/filings/kuzey-boru-as/interim-quarterly-report/2024/6652487/",
        },
        {
            "symbol": "KBORU",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 11),
            "announcement_source_url": "https://financialreports.eu/filings/kuzey-boru-as/interim-quarterly-report/2024/6628696/",
        },
        {
            "symbol": "KBORU",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/kuzey-boru-as/interim-quarterly-report/2024/6618010/",
        },
        {
            "symbol": "KBORU",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 4, 30),
            "announcement_source_url": "https://www.vkyanaliz.com/rap/KBORU_2026-05-04_39856.pdf",
        },
    ]


def test_fetchRecords_handlesPetunVkyFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("PETUN")

    assert records == [
        {
            "symbol": "PETUN",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 4, 30),
            "announcement_source_url": "https://www.vkyanaliz.com/rap/PETUN_2026-05-05_40256.pdf",
        },
    ]


def test_fetchRecords_handlesFmizpVkyFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("FMIZP")

    assert records == [
        {
            "symbol": "FMIZP",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 4, 27),
            "announcement_source_url": "https://www.vkyanaliz.com/rap/FMIZP_2026-05-04_39574.pdf",
        },
    ]


def test_fetchRecords_handlesBrksnFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("BRKSN")

    assert records == [
        {
            "symbol": "BRKSN",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 5, 9),
            "announcement_source_url": "https://kap.org.tr/tr/Bildirim/1149276",
        },
        {
            "symbol": "BRKSN",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 6),
            "announcement_source_url": "https://finans.cnnturk.com/kap-haberi/brksn-berkosan-yalitim-ve-tecrit-maddeleri-uretim-ve-ticaret-as-faaliyet-raporu-konsolide--3047607",
        },
        {
            "symbol": "BRKSN",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 20),
            "announcement_source_url": "https://financialreports.eu/filings/berkosan-yalitim-ve-tecrit-maddeleri-uretim-ve-ticaret-as/interim-quarterly-report/2024/6648140/",
        },
        {
            "symbol": "BRKSN",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 27),
            "announcement_source_url": "https://financialreports.eu/filings/berkosan-yalitim-ve-tecrit-maddeleri-uretim-ve-ticaret-as/interim-quarterly-report/2024/6624179/",
        },
        {
            "symbol": "BRKSN",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 3, 11),
            "announcement_source_url": "https://financialreports.eu/filings/berkosan-yalitim-ve-tecrit-maddeleri-uretim-ve-ticaret-as/management-reports/2026/32930579/",
        },
    ]


def test_fetchRecords_handlesDmrgdFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("DMRGD")

    assert records == [
        {
            "symbol": "DMRGD",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/dmr-unlu-mamuller-uretim-gida-toptan-perakende-ihracat-as/interim-quarterly-report/2023/6704252/",
        },
        {
            "symbol": "DMRGD",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 6),
            "announcement_source_url": "https://financialreports.eu/filings/dmr-unlu-mamuller-uretim-gida-toptan-perakende-ihracat-as/interim-quarterly-report/2024/6666153/",
        },
        {
            "symbol": "DMRGD",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 20),
            "announcement_source_url": "https://financialreports.eu/filings/dmr-unlu-mamuller-uretim-gida-toptan-perakende-ihracat-as/interim-quarterly-report/2024/6648118/",
        },
        {
            "symbol": "DMRGD",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 30),
            "announcement_source_url": "https://financialreports.eu/filings/dmr-unlu-mamuller-uretim-gida-toptan-perakende-ihracat-as/interim-quarterly-report/2024/6623250/",
        },
        {
            "symbol": "DMRGD",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 11),
            "announcement_source_url": "https://financialreports.eu/filings/dmr-unlu-mamuller-uretim-gida-toptan-perakende-ihracat-as/interim-quarterly-report/2024/6614069/",
        },
        {
            "symbol": "DMRGD",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 5, 11),
            "announcement_source_url": "https://bigpara.hurriyet.com.tr/haberler/kap-haberleri/dmrgd-dmr-unlu-mamuller-uretim-gida-toptan-perakende-ihracat-as-finansal-rapor_ID3493521/",
        },
    ]


def test_fetchRecords_handlesOfsymFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("OFSYM")

    assert records == [
        {
            "symbol": "OFSYM",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/ofis-yem-gida-sanayi-ticaret-as/interim-quarterly-report/2023/6704252/",
        },
        {
            "symbol": "OFSYM",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 6),
            "announcement_source_url": "https://financialreports.eu/filings/ofis-yem-gida-sanayi-ticaret-as/interim-quarterly-report/2024/6666153/",
        },
        {
            "symbol": "OFSYM",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 20),
            "announcement_source_url": "https://financialreports.eu/filings/ofis-yem-gida-sanayi-ticaret-as/interim-quarterly-report/2024/6648118/",
        },
        {
            "symbol": "OFSYM",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 30),
            "announcement_source_url": "https://financialreports.eu/filings/ofis-yem-gida-sanayi-ticaret-as/interim-quarterly-report/2024/6623250/",
        },
        {
            "symbol": "OFSYM",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 11),
            "announcement_source_url": "https://financialreports.eu/filings/ofis-yem-gida-sanayi-ticaret-as/interim-quarterly-report/2024/6614069/",
        },
    ]


def test_fetchRecords_handlesKonkaFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("KONKA")

    assert records == [
        {
            "symbol": "KONKA",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/konya-kagit-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6704045/",
        },
        {
            "symbol": "KONKA",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 9),
            "announcement_source_url": "https://financialreports.eu/filings/konya-kagit-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6663765/",
        },
        {
            "symbol": "KONKA",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 11),
            "announcement_source_url": "https://financialreports.eu/filings/konya-kagit-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6650902/",
        },
        {
            "symbol": "KONKA",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 20),
            "announcement_source_url": "https://financialreports.eu/filings/konya-kagit-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6625716/",
        },
        {
            "symbol": "KONKA",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/konya-kagit-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6618075/",
        },
        {
            "symbol": "KONKA",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 3, 2),
            "announcement_source_url": "https://financialreports.eu/filings/konya-kagit-sanayi-ve-ticaret-as/interim-quarterly-report/2026/32864435/",
        },
    ]


def test_fetchRecords_handlesKlserFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("KLSER")

    assert records == [
        {
            "symbol": "KLSER",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 27),
            "announcement_source_url": "https://financialreports.eu/filings/kaleseramik-canakkale-kalebodur-seramik-sanayi-as/interim-quarterly-report/2023/6705030/",
        },
        {
            "symbol": "KLSER",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 2),
            "announcement_source_url": "https://financialreports.eu/filings/kaleseramik-canakkale-kalebodur-seramik-sanayi-as/interim-quarterly-report/2024/6667161/",
        },
        {
            "symbol": "KLSER",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 21),
            "announcement_source_url": "https://financialreports.eu/filings/kaleseramik-canakkale-kalebodur-seramik-sanayi-as/interim-quarterly-report/2024/6647796/",
        },
        {
            "symbol": "KLSER",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 30),
            "announcement_source_url": "https://financialreports.eu/filings/kaleseramik-canakkale-kalebodur-seramik-sanayi-as/interim-quarterly-report/2024/6623333/",
        },
        {
            "symbol": "KLSER",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 11),
            "announcement_source_url": "https://financialreports.eu/filings/kaleseramik-canakkale-kalebodur-seramik-sanayi-as/interim-quarterly-report/2024/6614925/",
        },
        {
            "symbol": "KLSER",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 3, 6),
            "announcement_source_url": "https://financialreports.eu/filings/kaleseramik-canakkale-kalebodur-seramik-sanayi-as/interim-quarterly-report/2026/32909481/",
        },
    ]


def test_fetchRecords_handlesHatsnFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("HATSN")

    assert records == [
        {
            "symbol": "HATSN",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 28),
            "announcement_source_url": "https://financialreports.eu/filings/hat-san-gemi-insaa-bakim-onarim-deniz-nakliyat-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6704690/",
        },
        {
            "symbol": "HATSN",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 4),
            "announcement_source_url": "https://financialreports.eu/filings/hat-san-gemi-insaa-bakim-onarim-deniz-nakliyat-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6666204/",
        },
        {
            "symbol": "HATSN",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 10),
            "announcement_source_url": "https://financialreports.eu/filings/hat-san-gemi-insaa-bakim-onarim-deniz-nakliyat-sanayi-ve-ticaret-as/report-publication-announcement/2024/6651796/",
        },
        {
            "symbol": "HATSN",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 7),
            "announcement_source_url": "https://financialreports.eu/filings/hat-san-gemi-insaa-bakim-onarim-deniz-nakliyat-sanayi-ve-ticaret-as/report-publication-announcement/2024/6629398/",
        },
        {
            "symbol": "HATSN",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 12),
            "announcement_source_url": "https://financialreports.eu/filings/hat-san-gemi-insaa-bakim-onarim-deniz-nakliyat-sanayi-ve-ticaret-as/report-publication-announcement/2024/6613674/",
        },
        {
            "symbol": "HATSN",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 4, 29),
            "announcement_source_url": "https://financialreports.eu/filings/hat-san-gemi-insaa-bakim-onarim-deniz-nakliyat-sanayi-ve-ticaret-as/report-publication-announcement/2026/38668529/",
        },
    ]


def test_fetchRecords_handlesEupwrFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("EUPWR")

    assert records == [
        {
            "symbol": "EUPWR",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 5, 22),
            "announcement_source_url": "https://financialreports.eu/filings/europower-enerji-ve-otomasyon-teknolojileri-sanayi-ticaret-as/interim-quarterly-report/2023/6733625/",
        },
        {
            "symbol": "EUPWR",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 18),
            "announcement_source_url": "https://financialreports.eu/filings/europower-enerji-ve-otomasyon-teknolojileri-sanayi-ticaret-as/interim-quarterly-report/2023/6715351/",
        },
        {
            "symbol": "EUPWR",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 9),
            "announcement_source_url": "https://financialreports.eu/filings/europower-enerji-ve-otomasyon-teknolojileri-sanayi-ticaret-as/interim-quarterly-report/2023/6701147/",
        },
        {
            "symbol": "EUPWR",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 2),
            "announcement_source_url": "https://financialreports.eu/filings/europower-enerji-ve-otomasyon-teknolojileri-sanayi-ticaret-as/interim-quarterly-report/2024/6667131/",
        },
        {
            "symbol": "EUPWR",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 5, 22),
            "announcement_source_url": "https://financialreports.eu/filings/europower-enerji-ve-otomasyon-teknolojileri-sanayi-ticaret-as/interim-quarterly-report/2024/6658586/",
        },
        {
            "symbol": "EUPWR",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 13),
            "announcement_source_url": "https://financialreports.eu/filings/europower-enerji-ve-otomasyon-teknolojileri-sanayi-ticaret-as/interim-quarterly-report/2024/6628030/",
        },
        {
            "symbol": "EUPWR",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 11),
            "announcement_source_url": "https://financialreports.eu/filings/europower-enerji-ve-otomasyon-teknolojileri-sanayi-ticaret-as/interim-quarterly-report/2024/6614536/",
        },
    ]


def test_fetchRecords_handlesMakimFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("MAKIM")

    assert records == [
        {
            "symbol": "MAKIM",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 9),
            "announcement_source_url": "https://financialreports.eu/filings/makim-makina-teknolojileri-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6663915/",
        },
        {
            "symbol": "MAKIM",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 11),
            "announcement_source_url": "https://financialreports.eu/filings/makim-makina-teknolojileri-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6650843/",
        },
        {
            "symbol": "MAKIM",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 18),
            "announcement_source_url": "https://financialreports.eu/filings/makim-makina-teknolojileri-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6626599/",
        },
        {
            "symbol": "MAKIM",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/makim-makina-teknolojileri-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6617864/",
        },
        {
            "symbol": "MAKIM",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 3, 2),
            "announcement_source_url": "https://financialreports.eu/filings/makim-makina-teknolojileri-sanayi-ve-ticaret-as/interim-quarterly-report/2026/32864162/",
        },
    ]


def test_fetchRecords_handlesTarkmFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("TARKM")

    assert records == [
        {
            "symbol": "TARKM",
            "period_end": date(2022, 12, 1),
            "announcement_date": date(2023, 3, 1),
            "announcement_source_url": "https://financialreports.eu/filings/tarkim-bitki-koruma-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6758497/",
        },
        {
            "symbol": "TARKM",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 9),
            "announcement_source_url": "https://financialreports.eu/filings/tarkim-bitki-koruma-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6719272/",
        },
        {
            "symbol": "TARKM",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/tarkim-bitki-koruma-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6704536/",
        },
        {
            "symbol": "TARKM",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 4, 4),
            "announcement_source_url": "https://financialreports.eu/filings/tarkim-bitki-koruma-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6673252/",
        },
        {
            "symbol": "TARKM",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 11),
            "announcement_source_url": "https://financialreports.eu/filings/tarkim-bitki-koruma-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6650898/",
        },
        {
            "symbol": "TARKM",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 20),
            "announcement_source_url": "https://financialreports.eu/filings/tarkim-bitki-koruma-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6625753/",
        },
        {
            "symbol": "TARKM",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/tarkim-bitki-koruma-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6617672/",
        },
        {
            "symbol": "TARKM",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 3, 2),
            "announcement_source_url": "https://financialreports.eu/filings/tarkim-bitki-koruma-sanayi-ve-ticaret-as/interim-quarterly-report/2026/32866316/",
        },
    ]


def test_fetchRecords_handlesSeykmOfficialPdfDates():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("SEYKM")

    assert records == [
        {
            "symbol": "SEYKM",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 7),
            "announcement_source_url": "https://file.portay.com.tr/files/2023/08/Seyitler_06_2023_SPK_TR.pdf",
        },
        {
            "symbol": "SEYKM",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 26),
            "announcement_source_url": "https://file.portay.com.tr/files/2023/11/Seyitler_09_2023_SPK_TR.pdf",
        },
        {
            "symbol": "SEYKM",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 8),
            "announcement_source_url": "https://file.portay.com.tr/files/2024/05/Seyitler_12_2023_SPK_TR.pdf",
        },
        {
            "symbol": "SEYKM",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 10),
            "announcement_source_url": "https://file.portay.com.tr/files/2024/06/Seyitler_03_2024_SPK_TR.pdf",
        },
        {
            "symbol": "SEYKM",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 19),
            "announcement_source_url": "https://file.portay.com.tr/files/2024/10/Seyitler_06_2024_SPK_TR.pdf",
        },
        {
            "symbol": "SEYKM",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 10, 30),
            "announcement_source_url": "https://file.portay.com.tr/files/2024/12/Seyitler_09_2024_SPK_TR.pdf",
        },
        {
            "symbol": "SEYKM",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 5, 11),
            "announcement_source_url": "https://file.portay.com.tr/files/2026/Seyitler_03_2026_SPK_TR.pdf",
        },
    ]


def test_fetchRecords_handlesCusanFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("CUSAN")

    assert records == [
        {
            "symbol": "CUSAN",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 5, 10),
            "announcement_source_url": "https://financialreports.eu/filings/6735985/content/",
        },
        {
            "symbol": "CUSAN",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 23),
            "announcement_source_url": "https://financialreports.eu/filings/cuhadaroglu-metal-sanayi-ve-pazarlama-as/interim-quarterly-report/2024/6632276/",
        },
        {
            "symbol": "CUSAN",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 9),
            "announcement_source_url": "https://financialreports.eu/filings/cuhadaroglu-metal-sanayi-ve-pazarlama-as/interim-quarterly-report/2023/6700928/",
        },
        {
            "symbol": "CUSAN",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 3),
            "announcement_source_url": "https://financialreports.eu/filings/cuhadaroglu-metal-sanayi-ve-pazarlama-as/annual-report/2024/6666402/",
        },
        {
            "symbol": "CUSAN",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 5, 21),
            "announcement_source_url": "https://financialreports.eu/filings/cuhadaroglu-metal-sanayi-ve-pazarlama-as/annual-quarterly-financial-statement/2024/6658835/",
        },
        {
            "symbol": "CUSAN",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 8, 23),
            "announcement_source_url": "https://financialreports.eu/filings/cuhadaroglu-metal-sanayi-ve-pazarlama-as/interim-quarterly-report/2024/6632276/",
        },
    ]


def test_fetchRecords_handlesDnisiFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("DNISI")

    assert records == [
        {
            "symbol": "DNISI",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 3),
            "announcement_source_url": "https://financialreports.eu/filings/6721009/content/",
        },
        {
            "symbol": "DNISI",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 3),
            "announcement_source_url": "https://financialreports.eu/filings/dinamik-isi-makina-yalitim-malzemeleri-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6704328/",
        },
        {
            "symbol": "DNISI",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 4, 18),
            "announcement_source_url": "https://financialreports.eu/filings/dinamik-isi-makina-yalitim-malzemeleri-sanayi-ve-ticaret-as/annual-report/2024/6669492/",
        },
        {
            "symbol": "DNISI",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 13),
            "announcement_source_url": "https://financialreports.eu/filings/dinamik-isi-makina-yalitim-malzemeleri-sanayi-ve-ticaret-as/annual-quarterly-financial-statement/2024/6650138/",
        },
        {
            "symbol": "DNISI",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 13),
            "announcement_source_url": "https://financialreports.eu/filings/dinamik-isi-makina-yalitim-malzemeleri-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6627449/",
        },
        {
            "symbol": "DNISI",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 11),
            "announcement_source_url": "https://financialreports.eu/filings/dinamik-isi-makina-yalitim-malzemeleri-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6615855/",
        },
    ]


def test_fetchRecords_handlesDogubFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("DOGUB")

    assert records == [
        {
            "symbol": "DOGUB",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 8),
            "announcement_source_url": "https://financialreports.eu/filings/dogusan-boru-sanayi-ve-ticaret-as/business-and-financial-review/2023/6719811/",
        },
        {
            "symbol": "DOGUB",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 27),
            "announcement_source_url": "https://financialreports.eu/filings/dogusan-boru-sanayi-ve-ticaret-as/report-publication-announcement/2023/6704993/",
        },
        {
            "symbol": "DOGUB",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 10),
            "announcement_source_url": "https://financialreports.eu/filings/dogusan-boru-sanayi-ve-ticaret-as/report-publication-announcement/2024/6651887/",
        },
        {
            "symbol": "DOGUB",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 4),
            "announcement_source_url": "https://financialreports.eu/filings/dogusan-boru-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6630246/",
        },
        {
            "symbol": "DOGUB",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/dogusan-boru-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6617774/",
        },
    ]


def test_fetchRecords_handlesEgproFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("EGPRO")

    assert records == [
        {
            "symbol": "EGPRO",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 23),
            "announcement_source_url": "https://financialreports.eu/filings/ege-profil-ticaret-ve-sanayi-as/report-publication-announcement/2023/6714471/",
        },
        {
            "symbol": "EGPRO",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 7),
            "announcement_source_url": "https://financialreports.eu/filings/ege-profil-ticaret-ve-sanayi-as/report-publication-announcement/2023/6702184/",
        },
        {
            "symbol": "EGPRO",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 2, 28),
            "announcement_source_url": "https://financialreports.eu/filings/ege-profil-ticaret-ve-sanayi-as/report-publication-announcement/2024/6682107/",
        },
        {
            "symbol": "EGPRO",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 5, 16),
            "announcement_source_url": "https://financialreports.eu/filings/ege-profil-ticaret-ve-sanayi-as/interim-quarterly-report/2024/6661042/",
        },
        {
            "symbol": "EGPRO",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 8, 22),
            "announcement_source_url": "https://financialreports.eu/filings/ege-profil-ticaret-ve-sanayi-as/report-publication-announcement/2024/6632517/",
        },
        {
            "symbol": "EGPRO",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 8),
            "announcement_source_url": "https://financialreports.eu/filings/6615564/content/",
        },
        {
            "symbol": "EGPRO",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 5, 12),
            "announcement_source_url": "https://financialreports.eu/filings/ege-profil-ticaret-ve-sanayi-as/report-publication-announcement/2026/45021431/",
        },
    ]


def test_fetchRecords_handlesAlkaFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("ALKA")

    assert records == [
        {
            "symbol": "ALKA",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 3, 2),
            "announcement_source_url": "https://financialreports.eu/filings/alkim-kagit-sanayi-ve-ticaret-as/report-publication-announcement/2026/32864135/",
        }
    ]


def test_fetchRecords_handlesFormtFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("FORMT")

    assert records == [
        {
            "symbol": "FORMT",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 7, 7),
            "announcement_source_url": "https://financialreports.eu/filings/formet-metal-ve-cam-sanayi-as/report-publication-announcement/2023/6725953/",
        },
        {
            "symbol": "FORMT",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 4, 19),
            "announcement_source_url": "https://financialreports.eu/filings/formet-metal-ve-cam-sanayi-as/report-publication-announcement/2024/6670357/",
        },
        {
            "symbol": "FORMT",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 22),
            "announcement_source_url": "https://financialreports.eu/filings/formet-metal-ve-cam-sanayi-as/interim-quarterly-report/2024/6647253/",
        },
        {
            "symbol": "FORMT",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 27),
            "announcement_source_url": "https://financialreports.eu/filings/6623959/content/",
        },
        {
            "symbol": "FORMT",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 11),
            "announcement_source_url": "https://financialreports.eu/filings/6613919/content/",
        },
    ]


def test_fetchRecords_handlesEgserFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("EGSER")

    assert records == [
        {
            "symbol": "EGSER",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 4, 22),
            "announcement_source_url": "https://financialreports.eu/filings/ege-seramik-sanayi-ve-ticaret-as/regulatory-filings/2026/35271483/",
        },
    ]


def test_fetchRecords_handlesEggubFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("EGGUB")

    assert records == [
        {
            "symbol": "EGGUB",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 4, 23),
            "announcement_source_url": "https://financialreports.eu/filings/ege-gubre-sanayii-as/regulatory-filings/2026/35683644/",
        },
    ]


def test_fetchRecords_handlesJantsFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("JANTS")

    assert records == [
        {
            "symbol": "JANTS",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 9, 5),
            "announcement_source_url": "https://financialreports.eu/filings/jantsa-jant-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6712574/",
        },
        {
            "symbol": "JANTS",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/jantsa-jant-sanayi-ve-ticaret-as/report-publication-announcement/2023/6703648/",
        },
        {
            "symbol": "JANTS",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 3, 4),
            "announcement_source_url": "https://financialreports.eu/filings/jantsa-jant-sanayi-ve-ticaret-as/annual-report/2024/6681105/",
        },
        {
            "symbol": "JANTS",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 5, 16),
            "announcement_source_url": "https://financialreports.eu/filings/jantsa-jant-sanayi-ve-ticaret-as/annual-quarterly-financial-statement/2024/6661253/",
        },
        {
            "symbol": "JANTS",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 19),
            "announcement_source_url": "https://financialreports.eu/filings/jantsa-jant-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6626216/",
        },
        {
            "symbol": "JANTS",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 10, 25),
            "announcement_source_url": "https://financialreports.eu/filings/jantsa-jant-sanayi-ve-ticaret-as/report-publication-announcement/2024/6618784/",
        },
        {
            "symbol": "JANTS",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 4, 16),
            "announcement_source_url": "https://financialreports.eu/filings/jantsa-jant-sanayi-ve-ticaret-as/regulatory-filings/2026/34646438/",
        },
    ]


def test_fetchRecords_handlesGerelFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("GEREL")

    assert records == [
        {
            "symbol": "GEREL",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 16),
            "announcement_source_url": "https://financialreports.eu/filings/6716635/content/",
        },
        {
            "symbol": "GEREL",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 9),
            "announcement_source_url": "https://financialreports.eu/filings/gersan-elektrik-ticaret-ve-sanayi-as/interim-quarterly-report/2023/6700805/",
        },
        {
            "symbol": "GEREL",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 4, 4),
            "announcement_source_url": "https://financialreports.eu/filings/6673235/content/",
        },
        {
            "symbol": "GEREL",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 5, 22),
            "announcement_source_url": "https://financialreports.eu/filings/6657725/content/",
        },
        {
            "symbol": "GEREL",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 30),
            "announcement_source_url": "https://financialreports.eu/filings/gersan-elektrik-ticaret-ve-sanayi-as/interim-quarterly-report/2024/6623378/",
        },
        {
            "symbol": "GEREL",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 11),
            "announcement_source_url": "https://financialreports.eu/filings/6614786/content/",
        },
    ]


def test_fetchRecords_handlesKartnFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("KARTN")

    assert records == [
        {
            "symbol": "KARTN",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 16),
            "announcement_source_url": "https://financialreports.eu/filings/kartonsan-karton-sanayi-ve-ticaret-as/regulatory-filings/2023/6716657/",
        },
        {
            "symbol": "KARTN",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 6),
            "announcement_source_url": "https://financialreports.eu/filings/kartonsan-karton-sanayi-ve-ticaret-as/regulatory-filings/2023/6702570/",
        },
        {
            "symbol": "KARTN",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 6),
            "announcement_source_url": "https://financialreports.eu/filings/kartonsan-karton-sanayi-ve-ticaret-as/annual-report/2024/6665375/",
        },
        {
            "symbol": "KARTN",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 5, 22),
            "announcement_source_url": "https://financialreports.eu/filings/6657785/content/",
        },
        {
            "symbol": "KARTN",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 8, 23),
            "announcement_source_url": "https://financialreports.eu/filings/kartonsan-karton-sanayi-ve-ticaret-as/annual-quarterly-financial-statement/2024/6632412/",
        },
        {
            "symbol": "KARTN",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 8),
            "announcement_source_url": "https://cdn.financialreports.eu/financialreports/media/filings/8938/2024/RNS/8938_rns_2024-11-08_b4391c65-8558-4e1d-968f-2f3f9bc55c8d.pdf",
        },
        {
            "symbol": "KARTN",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 5, 11),
            "announcement_source_url": "https://bigpara.hurriyet.com.tr/haberler/kap-haberleri/kartn-kartonsan-karton-sanayi-ve-ticaret-as-finansal-rapor_ID3493423/",
        },
    ]


def test_fetchRecords_handlesDgnmoBigparaFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("DGNMO")

    assert records == [
        {
            "symbol": "DGNMO",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 5, 11),
            "announcement_source_url": "https://bigpara.hurriyet.com.tr/haberler/kap-haberleri/dgnmo-doganlar-mobilya-grubu-imalat-sanayi-ve-ticaret-as-finansal-rapor_ID3493937/",
        }
    ]


def test_fetchRecords_handlesMercnFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("MERCN")

    assert records == [
        {
            "symbol": "MERCN",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 5, 9),
            "announcement_source_url": "https://financialreports.eu/filings/mercan-kimya-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6737252/",
        },
        {
            "symbol": "MERCN",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 16),
            "announcement_source_url": "https://financialreports.eu/filings/mercan-kimya-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6716837/",
        },
        {
            "symbol": "MERCN",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 7),
            "announcement_source_url": "https://financialreports.eu/filings/mercan-kimya-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6702058/",
        },
        {
            "symbol": "MERCN",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 20),
            "announcement_source_url": "https://financialreports.eu/filings/mercan-kimya-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6659692/",
        },
        {
            "symbol": "MERCN",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 21),
            "announcement_source_url": "https://financialreports.eu/filings/mercan-kimya-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6647806/",
        },
        {
            "symbol": "MERCN",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 13),
            "announcement_source_url": "https://financialreports.eu/filings/mercan-kimya-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6627724/",
        },
        {
            "symbol": "MERCN",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 11),
            "announcement_source_url": "https://financialreports.eu/filings/mercan-kimya-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6614199/",
        },
    ]


def test_fetchRecords_handlesAlvesFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("ALVES")

    assert records == [
        {
            "symbol": "ALVES",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 22),
            "announcement_source_url": "https://financialreports.eu/filings/alves-kablo-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6647228/",
        },
        {
            "symbol": "ALVES",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 30),
            "announcement_source_url": "https://financialreports.eu/filings/alves-kablo-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6623091/",
        },
        {
            "symbol": "ALVES",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 11),
            "announcement_source_url": "https://financialreports.eu/filings/alves-kablo-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6613968/",
        },
        {
            "symbol": "ALVES",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 5, 8),
            "announcement_source_url": "https://mbigpara.hurriyet.com.tr/kap-haberleri/alves-alves-kablo-sanayi-ve-ticaret-as-finansal-rapor/3491922",
        },
    ]


def test_fetchRecords_handlesObamsFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("OBAMS")

    assert records == [
        {
            "symbol": "OBAMS",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 21),
            "announcement_source_url": "https://financialreports.eu/filings/oba-makarnacilik-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6647820/",
        },
        {
            "symbol": "OBAMS",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 30),
            "announcement_source_url": "https://financialreports.eu/filings/oba-makarnacilik-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6623260/",
        },
        {
            "symbol": "OBAMS",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 12, 11),
            "announcement_source_url": "https://financialreports.eu/filings/oba-makarnacilik-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6608856/",
        },
    ]


def test_fetchRecords_handlesArtmsFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("ARTMS")

    assert records == [
        {
            "symbol": "ARTMS",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 11),
            "announcement_source_url": "https://financialreports.eu/filings/artemis-hali-as/interim-quarterly-report/2024/6650970/",
        },
        {
            "symbol": "ARTMS",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 20),
            "announcement_source_url": "https://financialreports.eu/filings/artemis-hali-as/interim-quarterly-report/2024/6625789/",
        },
        {
            "symbol": "ARTMS",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/artemis-hali-as/interim-quarterly-report/2024/6618195/",
        },
        {
            "symbol": "ARTMS",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 3, 2),
            "announcement_source_url": "https://financialreports.eu/filings/artemis-hali-as/interim-quarterly-report/2026/32865622/",
        },
    ]


def test_fetchRecords_handlesLmkdcFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("LMKDC")

    assert records == [
        {
            "symbol": "LMKDC",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 7, 9),
            "announcement_source_url": "https://financialreports.eu/filings/limak-dogu-anadolu-cimento-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6642084/",
        },
        {
            "symbol": "LMKDC",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 19),
            "announcement_source_url": "https://financialreports.eu/filings/limak-dogu-anadolu-cimento-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6626365/",
        },
        {
            "symbol": "LMKDC",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 25),
            "announcement_source_url": "https://financialreports.eu/filings/limak-dogu-anadolu-cimento-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6611703/",
        },
        {
            "symbol": "LMKDC",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 3, 2),
            "announcement_source_url": "https://financialreports.eu/filings/limak-dogu-anadolu-cimento-sanayi-ve-ticaret-as/interim-quarterly-report/2026/32865622/",
        },
    ]


def test_fetchRecords_handlesTborgFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("TBORG")

    assert records == [
        {
            "symbol": "TBORG",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 21),
            "announcement_source_url": "https://financialreports.eu/filings/6714890/content/",
        },
        {
            "symbol": "TBORG",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 8),
            "announcement_source_url": "https://financialreports.eu/filings/turk-tuborg-bira-ve-malt-sanayii-as/report-publication-announcement/2023/6700830/",
        },
        {
            "symbol": "TBORG",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 6),
            "announcement_source_url": "https://financialreports.eu/filings/6665785/content/",
        },
        {
            "symbol": "TBORG",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 21),
            "announcement_source_url": "https://financialreports.eu/filings/turk-tuborg-bira-ve-malt-sanayii-as/regulatory-filings/2024/6647524/",
        },
        {
            "symbol": "TBORG",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 13),
            "announcement_source_url": "https://financialreports.eu/filings/turk-tuborg-bira-ve-malt-sanayii-as/interim-report/2024/6627824/",
        },
        {
            "symbol": "TBORG",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 7),
            "announcement_source_url": "https://financialreports.eu/filings/turk-tuborg-bira-ve-malt-sanayii-as/report-publication-announcement/2024/6615827/",
        },
        {
            "symbol": "TBORG",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 3, 31),
            "announcement_source_url": "https://financialreports.eu/filings/turk-tuborg-bira-ve-malt-sanayii-as/regulatory-filings/2026/33118400/",
        },
    ]


def test_fetchRecords_handlesBfrenFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("BFREN")

    assert records == [
        {
            "symbol": "BFREN",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 9),
            "announcement_source_url": "https://financialreports.eu/filings/bosch-fren-sistemleri-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6718492/",
        },
        {
            "symbol": "BFREN",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/bosch-fren-sistemleri-sanayi-ve-ticaret-as/report-publication-announcement/2023/6704538/",
        },
        {
            "symbol": "BFREN",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 7),
            "announcement_source_url": "https://financialreports.eu/filings/6665215/content/",
        },
        {
            "symbol": "BFREN",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 7, 12),
            "announcement_source_url": "https://financialreports.eu/filings/bosch-fren-sistemleri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6641734/",
        },
        {
            "symbol": "BFREN",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 20),
            "announcement_source_url": "https://financialreports.eu/filings/bosch-fren-sistemleri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6625381/",
        },
        {
            "symbol": "BFREN",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 13),
            "announcement_source_url": "https://financialreports.eu/filings/bosch-fren-sistemleri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6613442/",
        },
    ]


def test_fetchRecords_handlesUluunFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("ULUUN")

    assert records == [
        {
            "symbol": "ULUUN",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 14),
            "announcement_source_url": "https://financialreports.eu/filings/ulusoy-un-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6649528/",
        },
        {
            "symbol": "ULUUN",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 17),
            "announcement_source_url": "https://financialreports.eu/filings/ulusoy-un-sanayi-ve-ticaret-as/annual-quarterly-financial-statement/2023/6716336/",
        },
        {
            "symbol": "ULUUN",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 8),
            "announcement_source_url": "https://financialreports.eu/filings/ulusoy-un-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6701746/",
        },
        {
            "symbol": "ULUUN",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 18),
            "announcement_source_url": "https://financialreports.eu/filings/ulusoy-un-sanayi-ve-ticaret-as/annual-report/2024/6660299/",
        },
        {
            "symbol": "ULUUN",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 12),
            "announcement_source_url": "https://financialreports.eu/filings/ulusoy-un-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6624184/",
        },
        {
            "symbol": "ULUUN",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 8),
            "announcement_source_url": "https://financialreports.eu/filings/6615226/content/",
        },
        {
            "symbol": "ULUUN",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 4, 22),
            "announcement_source_url": "https://financialreports.eu/filings/ulusoy-un-sanayi-ve-ticaret-as/interim-quarterly-report/2026/35432866/",
        },
    ]


def test_fetchRecords_handlesYaprkFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("YAPRK")

    assert records == [
        {
            "symbol": "YAPRK",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 21),
            "announcement_source_url": "https://financialreports.eu/filings/6714835/content/",
        },
        {
            "symbol": "YAPRK",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 9),
            "announcement_source_url": "https://financialreports.eu/filings/6701076/content/",
        },
        {
            "symbol": "YAPRK",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 18),
            "announcement_source_url": "https://financialreports.eu/filings/yaprak-sut-ve-besi-ciftlikleri-sanayi-ve-ticaret-as/annual-report/2024/6660328/",
        },
        {
            "symbol": "YAPRK",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 5, 22),
            "announcement_source_url": "https://financialreports.eu/filings/6658495/content/",
        },
        {
            "symbol": "YAPRK",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 13),
            "announcement_source_url": "https://financialreports.eu/filings/6627597/content/",
        },
        {
            "symbol": "YAPRK",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 11),
            "announcement_source_url": "https://financialreports.eu/filings/6613905/content/",
        },
        {
            "symbol": "YAPRK",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 3, 11),
            "announcement_source_url": "https://financialreports.eu/filings/yaprak-sut-ve-besi-ciftlikleri-sanayi-ve-ticaret-as/report-publication-announcement/2026/32931112/",
        },
    ]


def test_fetchRecords_handlesYunsaFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("YUNSA")

    assert records == [
        {
            "symbol": "YUNSA",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 4, 17),
            "announcement_source_url": "https://financialreports.eu/filings/yunsa-yunlu-sanayi-ve-ticaret-as/regulatory-filings/2026/34659872/",
        },
    ]


def test_fetchRecords_handlesTukasFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("TUKAS")

    assert records == [
        {
            "symbol": "TUKAS",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 16),
            "announcement_source_url": "https://www.kap.org.tr/tr/Bildirim/1186172",
        },
        {
            "symbol": "TUKAS",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 6),
            "announcement_source_url": "https://www.bloomberght.com/borsa/hisse/tukas/kap-haberi/325401",
        },
        {
            "symbol": "TUKAS",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 9),
            "announcement_source_url": "https://www.kap.org.tr/tr/api/BildirimPdf/1284527",
        },
        {
            "symbol": "TUKAS",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 5, 22),
            "announcement_source_url": "https://financialreports.eu/filings/tukas-gda-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6658096/",
        },
        {
            "symbol": "TUKAS",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 12),
            "announcement_source_url": "https://financialreports.eu/filings/tukas-gda-sanayi-ve-ticaret-as/interim-report/2024/6628304/",
        },
        {
            "symbol": "TUKAS",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 11),
            "announcement_source_url": "https://financialreports.eu/filings/tukas-gda-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6614015/",
        },
        {
            "symbol": "TUKAS",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 3, 2),
            "announcement_source_url": "https://financialreports.eu/filings/tukas-gda-sanayi-ve-ticaret-as/report-publication-announcement/2026/32866801/",
        },
    ]


def test_fetchRecords_handlesTuclkOfficialPdfFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("TUCLK")

    assert records == [
        {
            "symbol": "TUCLK",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 9),
            "announcement_source_url": "https://www.tugcelik.com.tr/tr/pdf/spk-finansal-raporlar-2023-q2_4763.pdf",
        },
        {
            "symbol": "TUCLK",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 30),
            "announcement_source_url": "https://www.tugcelik.com.tr/tr/pdf/spk-finansal-raporlar-2023-q3_6577.pdf",
        },
        {
            "symbol": "TUCLK",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 9),
            "announcement_source_url": "https://www.tugcelik.com.tr/tr/pdf/spk-finansal-raporlar-2023-q4_2609.pdf",
        },
        {
            "symbol": "TUCLK",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 11),
            "announcement_source_url": "https://www.tugcelik.com.tr/tr/pdf/tugcelik-31032024-raporu_1385.pdf",
        },
        {
            "symbol": "TUCLK",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 20),
            "announcement_source_url": "https://www.tugcelik.com.tr/tr/pdf/tugcelik-30-06-2024-raporu.pdf",
        },
        {
            "symbol": "TUCLK",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 7),
            "announcement_source_url": "https://www.tugcelik.com.tr/tr/pdf/30.09.2024-konsolide-olmayan-finansal-durum-raporu.pdf",
        },
    ]


def test_fetchRecords_handlesMaktkOfficialPdfFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("MAKTK")

    assert records == [
        {
            "symbol": "MAKTK",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 16),
            "announcement_source_url": "https://makinatakim.com.tr/wp-content/uploads/2026/01/16082023051957330.pdf",
        },
        {
            "symbol": "MAKTK",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 9),
            "announcement_source_url": "https://makinatakim.com.tr/wp-content/uploads/2026/01/09112023053414288.pdf",
        },
        {
            "symbol": "MAKTK",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 3),
            "announcement_source_url": "https://makinatakim.com.tr/wp-content/uploads/2026/01/03052024201357505.pdf",
        },
        {
            "symbol": "MAKTK",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 13),
            "announcement_source_url": "https://makinatakim.com.tr/wp-content/uploads/2026/01/13062024051216567.pdf",
        },
        {
            "symbol": "MAKTK",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 18),
            "announcement_source_url": "https://makinatakim.com.tr/wp-content/uploads/2026/01/18092024180950962.pdf",
        },
        {
            "symbol": "MAKTK",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 7),
            "announcement_source_url": "https://makinatakim.com.tr/wp-content/uploads/2026/01/07112024053903283.pdf",
        },
    ]


def test_fetchRecords_handlesOylumOfficialPdfFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("OYLUM")

    assert records == [
        {
            "symbol": "OYLUM",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 9),
            "announcement_source_url": "https://www.oylum.com/wp-content/uploads/2025/04/Finansal-Rapor-2023-2.-3-Aylik.pdf",
        },
        {
            "symbol": "OYLUM",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 30),
            "announcement_source_url": "https://www.oylum.com/wp-content/uploads/2025/04/Finansal-Rapor-2023-3.-3-Aylik.pdf",
        },
        {
            "symbol": "OYLUM",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 9),
            "announcement_source_url": "https://www.oylum.com/wp-content/uploads/2025/11/Finansal-Raporu-2023-4.-3-Aylik.pdf",
        },
        {
            "symbol": "OYLUM",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 11),
            "announcement_source_url": "https://www.oylum.com/wp-content/uploads/2025/11/Finansal-Raporu-2024-1.-3-Aylik.pdf",
        },
        {
            "symbol": "OYLUM",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 20),
            "announcement_source_url": "https://www.oylum.com/wp-content/uploads/2025/11/Finansal-Raporu-2024-2.-3-Aylik.pdf",
        },
        {
            "symbol": "OYLUM",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 10, 30),
            "announcement_source_url": "https://www.oylum.com/wp-content/uploads/2025/11/Finansal-Raporu-2024-3.-3-Aylik.pdf",
        },
    ]


def test_fetchRecords_handlesOzsubOfficialPdfFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("OZSUB")

    assert records == [
        {
            "symbol": "OZSUB",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 12, 12),
            "announcement_source_url": "https://ozsubalik.com.tr/wp-content/uploads/2023/12/Ozsu-30.06.2023-Finansal-Rapor.pdf",
        },
        {
            "symbol": "OZSUB",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 12, 12),
            "announcement_source_url": "https://ozsubalik.com.tr/wp-content/uploads/2023/12/Ozsu-Rapor-30.09.2023-.pdf",
        },
        {
            "symbol": "OZSUB",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 21),
            "announcement_source_url": "https://ozsubalik.com.tr/wp-content/uploads/2024/05/31.12.2023-Finansal-Rapor-3.pdf",
        },
        {
            "symbol": "OZSUB",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 14),
            "announcement_source_url": "https://ozsubalik.com.tr/wp-content/uploads/2024/06/31.03.2024-Ozsu-Finansal-Rapor.pdf",
        },
        {
            "symbol": "OZSUB",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 27),
            "announcement_source_url": "https://ozsubalik.com.tr/wp-content/uploads/2024/09/30.06.2024-Finansal-Rapor.pdf",
        },
        {
            "symbol": "OZSUB",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 12),
            "announcement_source_url": "https://ozsubalik.com.tr/wp-content/uploads/2024/11/Ozsu-SPK-Rapor-30.09.2024-1.pdf",
        },
        {
            "symbol": "OZSUB",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 5, 8),
            "announcement_source_url": "https://ozsubalik.com.tr/wp-content/uploads/2026/05/Finansal-Rapor-31.03.2026.pdf",
        },
    ]


def test_fetchRecords_handlesMrshlFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("MRSHL")

    assert records == [
        {
            "symbol": "MRSHL",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 4),
            "announcement_source_url": "https://financialreports.eu/filings/6720785/content/",
        },
        {
            "symbol": "MRSHL",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 9),
            "announcement_source_url": "https://financialreports.eu/filings/marshall-boya-ve-vernik-sanayii-as/report-publication-announcement/2023/6704934/",
        },
        {
            "symbol": "MRSHL",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 6),
            "announcement_source_url": "https://financialreports.eu/filings/6665924/content/",
        },
        {
            "symbol": "MRSHL",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 11),
            "announcement_source_url": "https://financialreports.eu/filings/6651072/content/",
        },
        {
            "symbol": "MRSHL",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 19),
            "announcement_source_url": "https://financialreports.eu/filings/marshall-boya-ve-vernik-sanayii-as/report-publication-announcement/2024/6626352/",
        },
        {
            "symbol": "MRSHL",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 8),
            "announcement_source_url": "https://financialreports.eu/filings/marshall-boya-ve-vernik-sanayii-as/report-publication-announcement/2024/6617655/",
        },
        {
            "symbol": "MRSHL",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 4, 30),
            "announcement_source_url": "https://financialreports.eu/filings/marshall-boya-ve-vernik-sanayii-as/regulatory-filings/2026/39129203/",
        },
    ]


def test_fetchRecords_handlesMerkoFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("MERKO")

    assert records == [
        {
            "symbol": "MERKO",
            "period_end": date(2023, 3, 1),
            "announcement_date": date(2023, 5, 10),
            "announcement_source_url": "https://financialreports.eu/filings/merko-gida-sanayi-ve-ticaret-as/audit-report-information/2023/6736589/",
        },
        {
            "symbol": "MERKO",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 9, 8),
            "announcement_source_url": "https://financialreports.eu/filings/merko-gida-sanayi-ve-ticaret-as/report-publication-announcement/2023/6711992/",
        },
        {
            "symbol": "MERKO",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 9),
            "announcement_source_url": "https://financialreports.eu/filings/merko-gida-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6700592/",
        },
        {
            "symbol": "MERKO",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 3, 26),
            "announcement_source_url": "https://financialreports.eu/filings/6676061/content/",
        },
        {
            "symbol": "MERKO",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 5, 22),
            "announcement_source_url": "https://financialreports.eu/filings/6658520/content/",
        },
        {
            "symbol": "MERKO",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 11, 18),
            "announcement_source_url": "https://financialreports.eu/filings/6612771/content/",
        },
        {
            "symbol": "MERKO",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 12, 23),
            "announcement_source_url": "https://financialreports.eu/filings/6607269/content/",
        },
    ]


def test_fetchRecords_handlesSamatFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("SAMAT")

    assert records == [
        {
            "symbol": "SAMAT",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 8),
            "announcement_source_url": "https://financialreports.eu/filings/saray-matbaacilik-kagitcilik-kirtasiyecilik-ticaret-ve-sanayi-as/report-publication-announcement/2023/6719858/",
        },
        {
            "symbol": "SAMAT",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/saray-matbaacilik-kagitcilik-kirtasiyecilik-ticaret-ve-sanayi-as/report-publication-announcement/2023/6704149/",
        },
        {
            "symbol": "SAMAT",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 6),
            "announcement_source_url": "https://financialreports.eu/filings/6665924/content/",
        },
        {
            "symbol": "SAMAT",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 12),
            "announcement_source_url": "https://financialreports.eu/filings/saray-matbaacilik-kagitcilik-kirtasiyecilik-ticaret-ve-sanayi-as/report-publication-announcement/2024/6650465/",
        },
        {
            "symbol": "SAMAT",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 11, 19),
            "announcement_source_url": "https://financialreports.eu/filings/saray-matbaacilik-kagitcilik-kirtasiyecilik-ticaret-ve-sanayi-as/report-publication-announcement/2024/6612572/",
        },
        {
            "symbol": "SAMAT",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 29),
            "announcement_source_url": "https://financialreports.eu/filings/saray-matbaacilik-kagitcilik-kirtasiyecilik-ticaret-ve-sanayi-as/report-publication-announcement/2024/6610762/",
        },
    ]


def test_fetchRecords_handlesSarkyFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("SARKY")

    assert records == [
        {
            "symbol": "SARKY",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 21),
            "announcement_source_url": "https://financialreports.eu/filings/sarkuysan-elektrolitik-bakir-sanayi-ve-ticaret-as/report-publication-announcement/2023/6715002/",
        },
        {
            "symbol": "SARKY",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 6),
            "announcement_source_url": "https://financialreports.eu/filings/6666038/content/",
        },
        {
            "symbol": "SARKY",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 14),
            "announcement_source_url": "https://financialreports.eu/filings/sarkuysan-elektrolitik-bakir-sanayi-ve-ticaret-as/report-publication-announcement/2024/6648967/",
        },
        {
            "symbol": "SARKY",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 27),
            "announcement_source_url": "https://financialreports.eu/filings/sarkuysan-elektrolitik-bakir-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6623902/",
        },
        {
            "symbol": "SARKY",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 11),
            "announcement_source_url": "https://financialreports.eu/filings/6614168/content/",
        },
        {
            "symbol": "SARKY",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 5, 11),
            "announcement_source_url": "https://financialreports.eu/filings/sarkuysan-elektrolitik-bakir-sanayi-ve-ticaret-as/interim-quarterly-report/2026/44977803/",
        },
    ]


def test_fetchRecords_handlesSayasFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("SAYAS")

    assert records == [
        {
            "symbol": "SAYAS",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 9),
            "announcement_source_url": "https://financialreports.eu/filings/say-yenilenebilir-enerji-ekipmanlari-sanayi-ve-ticaret-as/report-publication-announcement/2023/6702104/",
        },
        {
            "symbol": "SAYAS",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/say-yenilenebilir-enerji-ekipmanlari-sanayi-ve-ticaret-as/report-publication-announcement/2023/6716668/",
        },
        {
            "symbol": "SAYAS",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 9),
            "announcement_source_url": "https://financialreports.eu/filings/say-yenilenebilir-enerji-ekipmanlari-sanayi-ve-ticaret-as/annual-report/2024/6666516/",
        },
        {
            "symbol": "SAYAS",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 11),
            "announcement_source_url": "https://financialreports.eu/filings/say-yenilenebilir-enerji-ekipmanlari-sanayi-ve-ticaret-as/report-publication-announcement/2024/6652195/",
        },
        {
            "symbol": "SAYAS",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 13),
            "announcement_source_url": "https://financialreports.eu/filings/say-yenilenebilir-enerji-ekipmanlari-sanayi-ve-ticaret-as/report-publication-announcement/2024/6624002/",
        },
        {
            "symbol": "SAYAS",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 8),
            "announcement_source_url": "https://financialreports.eu/filings/say-yenilenebilir-enerji-ekipmanlari-sanayi-ve-ticaret-as/report-publication-announcement/2024/6614010/",
        },
    ]


def test_fetchRecords_handlesSnicaFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("SNICA")

    assert records == [
        {
            "symbol": "SNICA",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 9),
            "announcement_source_url": "https://financialreports.eu/filings/sanica-isi-sanayi-as/report-publication-announcement/2023/6718096/",
        },
        {
            "symbol": "SNICA",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/sanica-isi-sanayi-as/report-publication-announcement/2023/6704663/",
        },
        {
            "symbol": "SNICA",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 4, 15),
            "announcement_source_url": "https://financialreports.eu/filings/sanica-isi-sanayi-as/report-publication-announcement/2024/6671987/",
        },
        {
            "symbol": "SNICA",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 11),
            "announcement_source_url": "https://financialreports.eu/filings/sanica-isi-sanayi-as/report-publication-announcement/2024/6650031/",
        },
        {
            "symbol": "SNICA",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 13),
            "announcement_source_url": "https://financialreports.eu/filings/sanica-isi-sanayi-as/report-publication-announcement/2024/6625373/",
        },
        {
            "symbol": "SNICA",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 8),
            "announcement_source_url": "https://financialreports.eu/filings/sanica-isi-sanayi-as/report-publication-announcement/2024/6618266/",
        },
        {
            "symbol": "SNICA",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 3, 2),
            "announcement_source_url": "https://financialreports.eu/filings/sanica-isi-sanayi-as/report-publication-announcement/2026/32865891/",
        },
    ]


def test_fetchRecords_handlesFrigoFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("FRIGO")

    assert records == [
        {
            "symbol": "FRIGO",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 11, 8),
            "announcement_source_url": "https://financialreports.eu/filings/frigo-pak-gida-maddeleri-sanayi-ve-ticaret-as/report-publication-announcement/2023/6701425/",
        },
        {
            "symbol": "FRIGO",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 14),
            "announcement_source_url": "https://financialreports.eu/filings/frigo-pak-gida-maddeleri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6662043/",
        },
        {
            "symbol": "FRIGO",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 7, 3),
            "announcement_source_url": "https://financialreports.eu/filings/frigo-pak-gida-maddeleri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6644020/",
        },
        {
            "symbol": "FRIGO",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 27),
            "announcement_source_url": "https://financialreports.eu/filings/frigo-pak-gida-maddeleri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6624074/",
        },
        {
            "symbol": "FRIGO",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 8),
            "announcement_source_url": "https://financialreports.eu/filings/frigo-pak-gida-maddeleri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6615156/",
        },
        {
            "symbol": "FRIGO",
            "period_end": date(2024, 12, 1),
            "announcement_date": date(2025, 3, 5),
            "announcement_source_url": "https://financialreports.eu/filings/6589714/content/",
        },
        {
            "symbol": "FRIGO",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 5, 11),
            "announcement_source_url": "https://bigpara.hurriyet.com.tr/haberler/kap-haberleri/frigo-frigo-pak-gida-maddeleri-sanayi-ve-ticaret-as-finansal-rapor_ID3493576/",
        },
    ]


def test_fetchRecords_handlesDesaFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("DESA")

    assert records == [
        {
            "symbol": "DESA",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 7),
            "announcement_source_url": "https://financialreports.eu/filings/desa-deri-sanayi-ve-ticaret-as/report-publication-announcement/2023/6720158/",
        },
        {
            "symbol": "DESA",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/desa-deri-sanayi-ve-ticaret-as/report-publication-announcement/2023/6703864/",
        },
        {
            "symbol": "DESA",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 3, 27),
            "announcement_source_url": "https://financialreports.eu/filings/desa-deri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6675485/",
        },
        {
            "symbol": "DESA",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 22),
            "announcement_source_url": "https://financialreports.eu/filings/desa-deri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6647244/",
        },
        {
            "symbol": "DESA",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 10),
            "announcement_source_url": "https://financialreports.eu/filings/desa-deri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6629018/",
        },
        {
            "symbol": "DESA",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 6),
            "announcement_source_url": "https://financialreports.eu/filings/desa-deri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6616241/",
        },
    ]


def test_fetchRecords_handlesPrzmaFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("PRZMA")

    assert records == [
        {
            "symbol": "PRZMA",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 8),
            "announcement_source_url": "https://financialreports.eu/filings/prizma-pres-matbaacilik-yayincilik-sanayi-ve-ticaret-as/report-publication-announcement/2023/6719910/",
        },
        {
            "symbol": "PRZMA",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 27),
            "announcement_source_url": "https://financialreports.eu/filings/prizma-pres-matbaacilik-yayincilik-sanayi-ve-ticaret-as/report-publication-announcement/2023/6704815/",
        },
        {
            "symbol": "PRZMA",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 4, 24),
            "announcement_source_url": "https://financialreports.eu/filings/prizma-pres-matbaacilik-yayincilik-sanayi-ve-ticaret-as/report-publication-announcement/2024/6669605/",
        },
        {
            "symbol": "PRZMA",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 11),
            "announcement_source_url": "https://financialreports.eu/filings/prizma-pres-matbaacilik-yayincilik-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6650860/",
        },
        {
            "symbol": "PRZMA",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 20),
            "announcement_source_url": "https://financialreports.eu/filings/prizma-pres-matbaacilik-yayincilik-sanayi-ve-ticaret-as/report-publication-announcement/2024/6625610/",
        },
        {
            "symbol": "PRZMA",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 4, 30),
            "announcement_source_url": "https://financialreports.eu/filings/prizma-pres-matbaacilik-yayincilik-sanayi-ve-ticaret-as/regulatory-filings/2026/39126088/",
        },
    ]


def test_fetchRecords_handlesYkslnFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("YKSLN")

    assert records == [
        {
            "symbol": "YKSLN",
            "period_end": date(2023, 6, 1),
            "announcement_date": date(2023, 8, 9),
            "announcement_source_url": "https://financialreports.eu/filings/yukselen-celik-as/interim-quarterly-report/2023/6719259/",
        },
        {
            "symbol": "YKSLN",
            "period_end": date(2023, 9, 1),
            "announcement_date": date(2023, 10, 30),
            "announcement_source_url": "https://financialreports.eu/filings/yukselen-celik-as/interim-quarterly-report/2023/6704472/",
        },
        {
            "symbol": "YKSLN",
            "period_end": date(2023, 12, 1),
            "announcement_date": date(2024, 5, 10),
            "announcement_source_url": "https://financialreports.eu/filings/yukselen-celik-as/interim-quarterly-report/2024/6663241/",
        },
        {
            "symbol": "YKSLN",
            "period_end": date(2024, 3, 1),
            "announcement_date": date(2024, 6, 21),
            "announcement_source_url": "https://financialreports.eu/filings/yukselen-celik-as/interim-quarterly-report/2024/6647830/",
        },
        {
            "symbol": "YKSLN",
            "period_end": date(2024, 6, 1),
            "announcement_date": date(2024, 9, 30),
            "announcement_source_url": "https://financialreports.eu/filings/yukselen-celik-as/interim-quarterly-report/2024/6623547/",
        },
        {
            "symbol": "YKSLN",
            "period_end": date(2024, 9, 1),
            "announcement_date": date(2024, 11, 11),
            "announcement_source_url": "https://financialreports.eu/filings/yukselen-celik-as/interim-quarterly-report/2024/6614247/",
        },
    ]


def test_fetchRecords_handlesOyakcFinancialreportsFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("OYAKC")

    assert records == [
        {
            "symbol": "OYAKC",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 5, 7),
            "announcement_source_url": "https://financialreports.eu/filings/oyak-cimento-fabrikalar-as/regulatory-filings/2026/43199204/",
        },
    ]


def test_fetchRecords_handlesBanvtOfficialPdfFallback():
    loader = IssuerIRAnnouncementsLoader()

    records = loader.fetch_records("BANVT")

    assert records == [
        {
            "symbol": "BANVT",
            "period_end": date(2026, 3, 1),
            "announcement_date": date(2026, 5, 4),
            "announcement_source_url": "https://www.banvit.com/sites/default/files/2026-05/banvit-finansal-rapor-31.03.2026-turkce.pdf",
        },
    ]
