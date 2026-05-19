import json

from fastapi.testclient import TestClient

from bist_factor_backtest.dashboard.app import create_app
from bist_factor_backtest.dashboard.settings import AdminSettings


class TestDashboardApp:
    def test_dashboardApp_requiresLoginAndRendersProtectedPages(self, tmp_path):
        root = tmp_path / "dashboard"
        profile_dir = root / "accepted_top6"
        profile_dir.mkdir(parents=True)
        (root / "manifest.json").write_text(
            json.dumps(
                {
                    "generated_at": "2026-05-18T00:00:00+00:00",
                    "profiles": [
                        {
                            "profile_id": "accepted_top6",
                            "label": "Kabul Edilen Ana Profil",
                            "config_path": "config.formula_research.yaml",
                            "run_id": "run-1",
                            "active": True,
                            "last_refreshed_at": "2026-05-18T00:00:00+00:00",
                            "latest_data_month": "2026-05",
                            "refresh_status": "success",
                            "message": None,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        files = {
            "summary.json": {
                "run_id": "run-1",
                "current_month": "2026-05",
                "latest_data_month": "2026-05",
                "latest_selected_month": "2026-04",
                "final_capital": 1000,
                "total_return": 0.2,
                "best_month": "2026-04",
                "worst_month": "2026-03",
            },
            "monthly_returns.json": [],
            "monthly_regimes.json": [
                {
                    "month": "2026-05",
                    "buy_date": "2026-05-04",
                    "breadth_200d": 0.22,
                    "regime_key": "riskli",
                    "regime_label": "Riskli Rejim",
                    "regime_risk": "high",
                    "regime_note": "Genis satis riski yuksek, piyasa breadth'i zayif.",
                }
            ],
            "selected_positions.json": [
                {
                    "month": "2026-05",
                    "symbol": "AAA",
                    "score": 1.0,
                    "x1": 0.6,
                    "x2": 0.4,
                    "x1_share": 0.6,
                    "x2_share": 0.4,
                    "selection_score": 1.0,
                    "net_income_growth": 0.2,
                    "equity": 100,
                    "operating_profit_ttm": 50,
                    "firm_value": 400,
                    "used_period_end": "2026-03-31",
                    "used_announcement_date": "2026-04-30",
                    "net_return": 0.1,
                    "confidence_level": "winner",
                    "repeat_count": 4,
                    "avg_net_return": 0.11,
                    "win_rate": 0.75,
                }
            ],
            "missing_financials.json": [
                {
                    "month": "2026-05",
                    "symbol": "BBB",
                    "provisional_rank": 2,
                    "score": 1.1,
                    "missing_fields": ["announcement_date"],
                    "rejection_reason": "missing_financial_data",
                }
            ],
            "current_month_alerts.json": [
                {
                    "month": "2026-05",
                    "symbol": "BBB",
                    "provisional_rank": 2,
                    "missing_fields": ["announcement_date"],
                }
            ],
            "current_month_stale_bases.json": [
                {
                    "month": "2026-05",
                    "symbol": "MERKO",
                    "used_period_label": "2024/Q4",
                    "financial_base_quarter_lag": 6,
                    "financial_base_warning": "Annual baz eski",
                }
            ],
            "symbol_confidence.json": [
                {
                    "symbol": "AAA",
                    "repeat_count": 4,
                    "avg_net_return": 0.11,
                    "win_rate": 0.75,
                    "confidence_level": "winner",
                }
            ],
        }
        for name, payload in files.items():
            (profile_dir / name).write_text(json.dumps(payload), encoding="utf-8")

        app = create_app(
            AdminSettings(
                dashboard_data_root=root,
                admin_password="secret",
                admin_password_hash=None,
                session_secret="secret-session",
                port=8000,
            )
        )
        client = TestClient(app)

        redirect_response = client.get("/", follow_redirects=False)
        assert redirect_response.status_code == 302
        assert redirect_response.headers["location"] == "/admin/login"

        bad_login = client.post("/admin/login", data={"password": "wrong"})
        assert bad_login.status_code == 401

        ok_login = client.post("/admin/login", data={"password": "secret"}, follow_redirects=False)
        assert ok_login.status_code == 302

        home = client.get("/")
        assert home.status_code == 200
        assert "AAA" in home.text
        assert "BBB" in home.text
        assert "MERKO" in home.text
        assert "announcement_date" in home.text
        assert "Riskli Rejim" in home.text
        assert "Son veri ayi 2026 / 05." in home.text

        positions = client.get("/positions?config=accepted_top6&year=2026&month=05")
        assert positions.status_code == 200
        assert "Guncel Eski Annual Baz Uyarilari" in positions.text
        assert "Ay Basi Rejimi" in positions.text

        missing = client.get("/missing-financials?config=accepted_top6&year=2026&month=05")
        assert missing.status_code == 200
        assert "announcement_date" in missing.text
