from __future__ import annotations

from datetime import date

from bist_factor_backtest.data.fintables import FintablesClient, FintablesFinancialLoader


def test_fintablesClient_fetchLatestScreenerRows_parsesLatestRows():
    client = FintablesClient()
    client._get_json = lambda url: {  # type: ignore[method-assign]
        "data": [
            {
                "code": "ASTOR",
                "published_at": "2026-05-11T19:38:31Z",
                "period": "2026/3",
                "net_kar": 1811756765,
            },
            {
                "code": "GUBRF",
                "published_at": "2026-06-11T15:17:28Z",
                "period": "2026/3",
                "net_kar": 3070462803,
            },
        ]
    }

    rows = client.fetch_latest_screener_rows(["ASTOR"])

    assert list(rows["symbol"]) == ["ASTOR"]
    assert rows.iloc[0]["period_end"] == date(2026, 3, 1)
    assert rows.iloc[0]["announcement_date"] == date(2026, 5, 11)
    assert rows.iloc[0]["net_income"] == 1_811_756_765
    assert rows.iloc[0]["announcement_source_system"] == "fintables_son_bilancolar"


def test_fintablesClient_fetchStatementRecords_parsesCoreFinancialFields():
    header_table = """
    <table>
      <tr>
        <th>Bilanço Kalemleri</th>
        <th>2026 / 3 E</th>
        <th>2025 / 12 E</th>
      </tr>
    </table>
    """
    balance_table = """
    <table>
      <tr><td>Nakit ve Nakit Benzerleri</td><td>% 10 1.924.175</td><td>% 5 1.403.812</td></tr>
      <tr><td>Ödenmiş Sermaye</td><td>% 0 998.000</td><td>% 0 998.000</td></tr>
      <tr><td>Toplam Özkaynaklar</td><td>% 5 38.403.566</td><td>% 9 36.621.515</td></tr>
      <tr><td>Kısa Vadeli Borçlanmalar</td><td>% 0 700.000</td><td>% 0 600.000</td></tr>
      <tr><td>Uzun Vadeli Borçlanmalar</td><td>% 0 300.000</td><td>% 0 250.000</td></tr>
    </table>
    """
    income_table = """
    <table>
      <tr>
        <th>Gelir Tablosu Kalemleri</th>
        <th>2026 / 3 E</th>
        <th>2025 / 12 E</th>
      </tr>
    </table>
    <table>
      <tr><td>Finansman Geliri (Gideri) Öncesi Faaliyet Karı (Zararı)</td><td>% -77 3.999.379</td><td>% 46 17.100.938</td></tr>
      <tr><td>Dönem Karı (Zararı)</td><td>% -79 1.811.757</td><td>% 54 8.439.037</td></tr>
    </table>
    """
    client = FintablesClient()
    client._get_text = lambda url: header_table + balance_table if "bilanco" in url else income_table  # type: ignore[method-assign]

    records = client.fetch_statement_records("ASTOR")
    latest = next(record for record in records if record["period_end"] == date(2026, 3, 1))

    assert latest["shares_outstanding"] == 998_000_000.0
    assert latest["equity"] == 38_403_566_000.0
    assert latest["cash"] == 1_924_175_000.0
    assert latest["total_debt"] == 1_000_000_000.0
    assert latest["operating_profit"] == 3_999_379_000.0
    assert latest["net_income"] == 1_811_757_000.0


def test_fintablesFinancialLoader_buildFromRecords_createsStatementAndItems():
    loader = FintablesFinancialLoader()
    result = loader.build_from_records(
        "ASTOR",
        [
            {
                "symbol": "ASTOR",
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 5, 11),
                "announcement_source_url": "https://api.fintables.com/screener/",
                "announcement_source_system": "fintables_son_bilancolar",
                "source_url": "https://fintables.com/sirketler/ASTOR/finansal-tablolar",
                "shares_source_url": "https://fintables.com/sirketler/ASTOR/finansal-tablolar",
                "shares_outstanding": 998_000_000.0,
                "equity": 38_403_566_000.0,
                "cash": 1_924_175_000.0,
                "total_debt": 1_000_000_000.0,
                "operating_profit": 3_999_379_000.0,
                "net_income": 1_811_757_000.0,
            }
        ],
    )

    assert result.failures.empty
    assert len(result.statements) == 1
    assert set(result.items["item_code"]) == {
        "net_income",
        "equity",
        "operating_profit",
        "cash",
        "total_debt",
    }
    assert result.statements.iloc[0]["announcement_source_system"] == "fintables_son_bilancolar"
