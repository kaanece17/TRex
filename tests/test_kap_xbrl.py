import pytest

from bist_factor_backtest.data.kap_xbrl import parse_financial_report_html


class TestParseFinancialReportHtml:
    def test_parseFinancialReportHtml_issuedCapitalRow_returnsSharesOutstanding(self):
        html = """
        <table>
          <tr class="data-input-row">
            <td>ifrs-full_IssuedCapital</td><td></td><td>Ödenmiş Sermaye</td><td>Issued capital</td><td>350.910</td><td>350.910</td>
          </tr>
          <tr class="data-input-row">
            <td>ifrs-full_ProfitLossAttributableToOwnersOfParent</td><td></td><td>Ana Ortaklık Payları</td><td>Owners</td><td>25.665.591</td>
          </tr>
          <tr class="data-input-row">
            <td>ifrs-full_ProfitLossFromOperatingActivities</td><td></td><td>ESAS FAALİYET KARI</td><td>Operating</td><td>22.942.584</td>
          </tr>
          <tr class="data-input-row">
            <td>ifrs-full_EquityAttributableToOwnersOfParent</td><td></td><td>Özkaynak</td><td>Equity</td><td>101.378.034</td>
          </tr>
          <tr class="data-input-row">
            <td>ifrs-full_CashAndCashEquivalents</td><td></td><td>Nakit</td><td>Cash</td><td>30.136.854</td>
          </tr>
        </table>
        """
        expected = 350_910_000

        result = parse_financial_report_html(html)

        assert result.shares_outstanding == expected
        assert result.net_income == 25_665_591_000
        assert result.operating_profit == 22_942_584_000
        assert result.equity == 101_378_034_000
        assert result.cash == 30_136_854_000
        assert result.to_items()["shares_outstanding"] == pytest.approx(expected)

    def test_parseFinancialReportHtml_debtAndNonNumericRows_returnsDebtAndSkipsInvalidRows(self):
        html = """
        <table>
          <tr class="data-input-row">
            <td>kap-fr_CurrentBorowings</td><td></td><td>Kısa Vadeli Borçlanmalar</td><td>Debt</td><td>10</td>
          </tr>
          <tr class="data-input-row">
            <td>ifrs-full_NoncurrentBorrowings</td><td></td><td>Uzun Vadeli Borçlanmalar</td><td>Debt</td><td>20</td>
          </tr>
          <tr class="data-input-row">
            <td>ifrs-full_CashAndCashEquivalents</td><td></td><td>Nakit</td><td>Cash</td><td>-</td>
          </tr>
        </table>
        """

        result = parse_financial_report_html(html)

        assert result.total_debt == 30_000
        assert result.cash is None

    def test_parseFinancialReportHtml_taxonomyRowsWithContextValues_returnsCoreValues(self):
        html = """
        <table class="financial-table">
          <tr>
            <td class="taxonomy-field-name">ifrs-full_ProfitLossAttributableToOwnersOfParent|</td>
            <td class="taxonomy-context-value">1.234</td>
          </tr>
          <tr>
            <td class="taxonomy-field-name">ifrs-full_ProfitLossFromOperatingActivities|</td>
            <td class="taxonomy-context-value">2.345</td>
          </tr>
          <tr>
            <td class="taxonomy-field-name">ifrs-full_EquityAttributableToOwnersOfParent|</td>
            <td class="taxonomy-context-value">3.456</td>
          </tr>
          <tr>
            <td class="taxonomy-field-name">ifrs-full_IssuedCapital|</td>
            <td class="taxonomy-context-value">4.567</td>
          </tr>
        </table>
        """

        result = parse_financial_report_html(html)

        assert result.net_income == 1_234_000
        assert result.operating_profit == 2_345_000
        assert result.equity == 3_456_000
        assert result.shares_outstanding == 4_567_000

    def test_parseFinancialReportHtml_kapFrFallbackConceptAndParentheses_returnsSignedValue(self):
        html = """
        <table>
          <tr>
            <td>x</td>
            <td>kap-fr_OperatingProfitLoss</td>
            <td>y</td>
            <td>(1.250)</td>
          </tr>
        </table>
        """

        result = parse_financial_report_html(html)

        assert result.operating_profit == -1_250_000
