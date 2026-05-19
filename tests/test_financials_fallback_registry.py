from __future__ import annotations

from datetime import date

from bs4 import BeautifulSoup

from bist_factor_backtest.data.financials_fallback_registry import (
    FinancialFallbackRegistryLoader,
    load_financial_fallback_registry,
    record_to_statement_rows,
)


def test_loadFinancialFallbackRegistry_readsEntries(tmp_path):
    registry = tmp_path / "financial_fallback_registry.csv"
    registry.write_text(
        "\n".join(
            [
                "symbol,period_end,fiscal_year,fiscal_period,source_type,source_url,announcement_date,is_active,notes",
                "BORSK,2025-12-01,2025,Q4,financialreports_filing,https://example.com,2026-01-30,true,test",
            ]
        ),
        encoding="utf-8",
    )

    entries = load_financial_fallback_registry(str(registry))

    assert len(entries) == 1
    assert entries[0].symbol == "BORSK"
    assert entries[0].period_end == date(2025, 12, 1)
    assert entries[0].announcement_date == date(2026, 1, 30)


def test_extractFinancialreportsValues_readsCoreLineItems():
    html = """
    <html><body>
      <table>
        <tr><td>ifrs-full_Equity|http://www.xbrl.org/2003/role/totalLabel</td><td></td><td>TOPLAM ÖZKAYNAKLAR</td><td>Total equity</td><td>1.246.101.351</td><td>1.555.985.728</td></tr>
        <tr><td>ifrs-full_IssuedCapital|</td><td></td><td>Ödenmiş Sermaye</td><td>Issued capital</td><td>147.102.475</td><td>147.102.475</td></tr>
        <tr><td>ifrs-full_ProfitLossFromOperatingActivities|</td><td></td><td>ESAS FAALİYET KARI (ZARARI)</td><td>PROFIT (LOSS) FROM OPERATING ACTIVITIES</td><td>-294.612.529</td><td>221.386.909</td></tr>
        <tr><td>ifrs-full_ProfitLossFromContinuingOperations|</td><td></td><td>SÜRDÜRÜLEN FAALİYETLER DÖNEM KARI (ZARARI)</td><td>PROFIT (LOSS) FROM CONTINUING OPERATIONS</td><td>-296.513.427</td><td>140.594.168</td></tr>
        <tr><td>ifrs-full_CashAndCashEquivalents|</td><td></td><td>Nakit ve Nakit Benzerleri</td><td>Cash and cash equivalents</td><td>128.516.533</td><td>69.222.142</td></tr>
        <tr><td>ifrs-full_CurrentBorrowings|</td><td></td><td>Kısa Vadeli Borçlanmalar</td><td>Short-term borrowings</td><td>250.044.319</td><td>130.940.604</td></tr>
        <tr><td>ifrs-full_NoncurrentBorrowings|</td><td></td><td>Uzun Vadeli Borçlanmalar</td><td>Long-term borrowings</td><td>33.842.845</td><td>0</td></tr>
      </table>
    </body></html>
    """
    loader = FinancialFallbackRegistryLoader()

    values = loader._extract_financialreports_values(BeautifulSoup(html, "html.parser"))

    assert values["equity"] == 1246101351.0
    assert values["shares_outstanding"] == 147102475.0
    assert values["operating_profit"] == -294612529.0
    assert values["net_income"] == -296513427.0
    assert values["cash"] == 128516533.0
    assert values["total_debt"] == 283887164.0


def test_recordToStatementRows_buildsStatementAndItems():
    statement, items = record_to_statement_rows(
        {
            "statement_id": "FALLBACK-BORSK-20251201",
            "symbol": "BORSK",
            "period_end": date(2025, 12, 1),
            "fiscal_year": 2025,
            "fiscal_period": "Q4",
            "statement_type": "financial_statement",
            "announcement_datetime": None,
            "announcement_date": date(2026, 1, 30),
            "currency": "TRY",
            "is_consolidated": True,
            "is_revised": False,
            "source_url": "https://example.com",
            "announcement_source_url": "https://example.com",
            "raw_hash": "abc",
            "created_at": None,
            "shares_outstanding": 240000000.0,
            "shares_announcement_datetime": None,
            "shares_source_url": "https://example.com",
            "net_income": 10.0,
            "equity": 20.0,
            "operating_profit": 30.0,
            "cash": 40.0,
            "total_debt": 50.0,
        }
    )

    assert statement.iloc[0]["statement_id"] == "FALLBACK-BORSK-20251201"
    assert set(items["item_code"].tolist()) == {"net_income", "equity", "operating_profit", "cash", "total_debt"}


def test_extractIssuerIrPdfTextValues_readsCoreLineItems():
    text = """
Toplam Özkaynaklar 3.649.015.543 4.792.252.977 1.992.794.093
Ödenmiş Sermaye 22 1.112.000.000 1.112.000.000 76.576.681
ESAS FAALİYET KARI 375.363.934 1.039.261.705 639.915.744 610.773.407
DÖNEM KARI / (ZARARI) (780.037.326) 203.868.902 (39.136.924) (31.587.024)
Nakit ve Nakit Benzerleri 7 212.349.113 586.764.338 549.794.166
Kısa Vadeli Borçlanmalar 9 9.588.794.982 6.215.890.498 3.228.284.474
Uzun Vadeli Borçlanmaların Kısa Vadeli Kısımları 9 1.913.257.465 1.967.954.742 1.207.562.127
Uzun Vadeli Borçlanmalar 9 2.017.491.406 1.303.496.350 449.607.009
"""
    loader = FinancialFallbackRegistryLoader()

    values = loader._extract_issuer_ir_pdf_text_values(text)

    assert values["equity"] == 3649015543.0
    assert values["shares_outstanding"] == 1112000000.0
    assert values["operating_profit"] == 375363934.0
    assert values["net_income"] == -780037326.0
    assert values["cash"] == 212349113.0
    assert values["total_debt"] == 13519543853.0
