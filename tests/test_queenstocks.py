from __future__ import annotations

from datetime import date
import json
from types import SimpleNamespace

import pandas as pd

from bist_factor_backtest.cli import (
    _parse_symbol_csv,
    _queenstocks_balance_format_slug,
    _queenstocks_probe_missing_fields,
    _resolve_queenstocks_backfill_targets,
    _resolve_queenstocks_target_symbols,
)
from bist_factor_backtest.data.queenstocks import (
    QueenStocksClient,
    _build_statement_record_from_detail,
)


class _FakeResponse:
    def __init__(self, *, text: str = "", json_value=None, status_code: int = 200):
        self.text = text
        self._json_value = json_value
        self.status_code = status_code
        self.ok = status_code < 400

    def json(self):
        return self._json_value

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class _FakeSession:
    def __init__(self):
        self.headers = {}
        self.calls: list[tuple[str, str, dict]] = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return _FakeResponse(
            text=(
                '<html><body><form action="/queenstockspro/Uye/GirisYap">'
                '<input type="hidden" name="ReturnUrl" value="/QueenStocksPro" />'
                '<input type="hidden" name="__RequestVerificationToken" value="token-1" />'
                "</form></body></html>"
            )
        )

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        if "GetServisKey" in url:
            return _FakeResponse(json_value="service-key-123")
        return _FakeResponse(text="ok")

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return _FakeResponse(json_value={})


def test_queenstocksClient_ensureAuthenticated_logsInAndFetchesServiceKey():
    client = QueenStocksClient("user@example.com", "secret")
    client.session = _FakeSession()

    client._ensure_authenticated()

    assert client._service_key == "service-key-123"
    login_post = client.session.calls[1]
    assert login_post[0] == "POST"
    assert login_post[1].endswith("/queenstockspro/Uye/GirisYap")
    assert login_post[2]["data"]["mail"] == "user@example.com"
    assert login_post[2]["data"]["password"] == "secret"
    assert login_post[2]["data"]["__RequestVerificationToken"] == "token-1"


def test_queenstocksClient_fetchFinancialReportDetails_filtersToFinancialReports():
    client = QueenStocksClient("user@example.com", "secret")
    client._list_company_news = lambda symbol, page_size: [  # type: ignore[method-assign]
        {"HaberId": 1, "BildirimTip": "FR", "Ozet": "Finansal Rapor"},
        {"HaberId": 2, "BildirimTip": "DG", "Ozet": "Temettu Dagitimi"},
    ]
    client._get_news_detail = lambda haber_id, piyasa_id=1: {  # type: ignore[method-assign]
        "HaberDetayGetirResult": json.dumps(
            {
                "HaberId": haber_id,
                "BildirimId": 2000 + haber_id,
                "BildirimTip": "FR",
                "AciklanmaTarihi": "11.05.2026 22:38",
                "Yil": 2026,
                "Donem": 3,
                "HaberTablolarList": {"Tablo": {"Rows": []}},
            }
        )
    }

    details = client.fetch_financial_report_details("ASTOR")

    assert len(details) == 1
    assert details[0]["HaberId"] == 1
    assert details[0]["BildirimTip"] == "FR"


def test_queenstocksClient_fetchFinancialReportDetails_excludesNonFrFinancialNotices():
    client = QueenStocksClient("user@example.com", "secret")
    client._list_company_news = lambda symbol, page_size: [  # type: ignore[method-assign]
        {"HaberId": 1, "BildirimTip": None, "Ozet": "Finansal Rapor Ek Süre Taleplerine İlişkin SPK Değerlendirmesi"},
        {"HaberId": 2, "BildirimTip": None, "Ozet": "2021/04.Dönem Finansal Rapor Bildirimi Düzeltmesi"},
        {"HaberId": 3, "BildirimTip": None, "Ozet": "Finansal Rapor"},
    ]

    def _fake_detail(haber_id, piyasa_id=1):
        tip = {1: "DUY", 2: "ODA", 3: "FR"}[haber_id]
        return {
            "HaberDetayGetirResult": json.dumps(
                {
                    "HaberId": haber_id,
                    "BildirimId": 3000 + haber_id,
                    "BildirimTip": tip,
                    "AciklanmaTarihi": "11.05.2026 22:38",
                    "Yil": 2026,
                    "Donem": 3,
                    "HaberTablolarList": {"Tablo": {"Rows": []}},
                    "Ozet": "Finansal Rapor",
                }
            )
        }

    client._get_news_detail = _fake_detail  # type: ignore[method-assign]

    details = client.fetch_financial_report_details("ASTOR")

    assert len(details) == 1
    assert details[0]["HaberId"] == 3
    assert details[0]["BildirimTip"] == "FR"


def test_buildStatementRecordFromDetail_extractsCoreValuesAndPeriodEnd():
    detail = {
        "HaberId": 4407605,
        "BildirimId": 991122,
        "BildirimTip": "FR",
        "AciklanmaTarihi": "11.05.2026 22:38",
        "Yil": 2026,
        "Donem": 3,
        "HaberTablolarList": {
            "BILANCO": {
                "Rows": [
                    {"Cells": [{"Data": "Cari Donem 31.03.2026"}, {"Data": "Onceki Donem 31.12.2025"}]},
                    {"Cells": [{"Data": "Toplam Ozkaynaklar"}, {"Data": "38,403,565,895.00"}]},
                    {"Cells": [{"Data": "Nakit ve Nakit Benzerleri"}, {"Data": "125.000"}]},
                    {"Cells": [{"Data": "Odenmis Sermaye"}, {"Data": "250.000"}]},
                    {"Cells": [{"Data": "Kisa Vadeli Borclanmalar"}, {"Data": "70.000"}]},
                    {"Cells": [{"Data": "Uzun Vadeli Borclanmalar"}, {"Data": "30.000"}]},
                ]
            },
            "GELIR": {
                "Rows": [
                    {"Cells": [{"Data": "Esas Faaliyet Kari (Zarari)"}, {"Data": "340.000"}]},
                    {"Cells": [{"Data": "Net Donem Kari (Zarari)"}, {"Data": "280.000"}]},
                ]
            },
        },
    }

    record = _build_statement_record_from_detail("ASTOR", detail, "Europe/Istanbul")

    assert record is not None
    assert record["period_end"] == date(2026, 3, 1)
    assert record["equity"] == 38_403_565_895.0
    assert record["cash"] == 125_000.0
    assert record["operating_profit"] == 340_000.0
    assert record["net_income"] == 280_000.0
    assert record["total_debt"] == 100_000.0
    assert record["shares_outstanding"] == 250_000.0
    assert str(record["statement_id"]).startswith("QUEENSTOCKS-ASTOR-20260301-991122")


def test_parseSymbolCsv_dedupesAndUppercases():
    assert _parse_symbol_csv(" astor,ASTOR, froto ,, gubrf ") == ["ASTOR", "FROTO", "GUBRF"]


def test_resolveQueenstocksTargetSymbols_appliesStartAndBatch(tmp_path):
    symbols_file = tmp_path / "symbols.csv"
    pd.DataFrame({"symbol": ["ASTOR", "FROTO", "GUBRF", "CCOLA"]}).to_csv(symbols_file, index=False)
    settings = SimpleNamespace(universe=SimpleNamespace(symbols_file=symbols_file, symbol_aliases_file=None))

    result = _resolve_queenstocks_target_symbols(
        settings,
        symbols=None,
        max_symbols=None,
        start_index=1,
        batch_size=2,
    )

    assert result == ["FROTO", "GUBRF"]


def test_resolveQueenstocksBackfillTargets_prefersFillQueueWhenPresent(tmp_path):
    symbols_file = tmp_path / "symbols.csv"
    fill_queue_file = tmp_path / "fill_queue.csv"
    pd.DataFrame({"symbol": ["ASTOR", "FROTO", "GUBRF"]}).to_csv(symbols_file, index=False)
    pd.DataFrame({"symbol": ["gubrf", "astor", "ASTOR"]}).to_csv(fill_queue_file, index=False)
    settings = SimpleNamespace(universe=SimpleNamespace(symbols_file=symbols_file, symbol_aliases_file=None))

    result = _resolve_queenstocks_backfill_targets(
        settings,
        symbols=None,
        fill_queue_file=fill_queue_file,
        only_fill_queue=True,
    )

    assert result == ["ASTOR", "GUBRF"]


def test_queenstocksBalanceFormatSlug_normalizesTurkishText():
    assert _queenstocks_balance_format_slug("Gayrimenkul Yatırım Ortaklığı") == "gayrimenkul-yatirim-ortakligi"
    assert _queenstocks_balance_format_slug("Sanayi") == "sanayi"


def test_queenstocksProbeMissingFields_reportsOnlyMissingRequiredValues():
    row = pd.Series(
        {
            "shares_outstanding": 998_000_000.0,
            "equity": None,
            "net_income": 1_000_000.0,
            "operating_profit_est": None,
        }
    )

    assert _queenstocks_probe_missing_fields(row) == "equity,operating_profit_est"
