from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bist_factor_backtest.dashboard import project_root


@dataclass(frozen=True)
class DashboardProfile:
    id: str
    label: str
    config_path: Path
    market_id: str
    market_label: str
    active: bool = True


def active_dashboard_profiles() -> list[DashboardProfile]:
    root = project_root()
    return [
        DashboardProfile(
            id="momentum_watchlist",
            label="Kabul Edilen Ana Profil",
            config_path=root / "config.formula_research_momentum.yaml",
            market_id="tr",
            market_label="TR",
        ),
        DashboardProfile(
            id="technical_confirmation",
            label="Teknik Dogrulama Alternatifi",
            config_path=root / "config.formula_research_technical_confirmation.yaml",
            market_id="tr",
            market_label="TR",
        ),
        DashboardProfile(
            id="accepted_top6",
            label="Legacy Kabul Edilen Top6",
            config_path=root / "config.formula_research.yaml",
            market_id="tr",
            market_label="TR",
        ),
        DashboardProfile(
            id="us_industrials_momentum",
            label="US Industrials Momentum",
            config_path=root / "config.us_industrials_momentum.yaml",
            market_id="us",
            market_label="US",
        ),
        DashboardProfile(
            id="us_industrials_quality_scorecap",
            label="US Industrials Quality ScoreCap",
            config_path=root / "config.us_industrials_quality_scorecap.yaml",
            market_id="us",
            market_label="US",
        ),
        DashboardProfile(
            id="us_industrials_quality_earnings",
            label="US Industrials Quality + Earnings",
            config_path=root / "config.us_industrials_quality_earnings.yaml",
            market_id="us",
            market_label="US",
        ),
    ]
