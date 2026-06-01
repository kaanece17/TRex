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
        DashboardProfile(
            id="us_industrials_quality_op_growth",
            label="US Industrials Quality + OP Growth",
            config_path=root / "config.us_industrials_quality_op_growth.yaml",
            market_id="us",
            market_label="US",
        ),
        DashboardProfile(
            id="us_large_cap_tech_quality_earnings",
            label="US Large-Cap Tech Quality + Earnings",
            config_path=root / "config.us_large_cap_tech_quality_earnings.yaml",
            market_id="us",
            market_label="US",
        ),
        DashboardProfile(
            id="us_large_cap_tech_asset_growth_guard",
            label="US Large-Cap Tech Asset-Growth Guard",
            config_path=root / "config.us_large_cap_tech_asset_growth_guard.yaml",
            market_id="us",
            market_label="US",
        ),
        DashboardProfile(
            id="us_large_cap_tech_no_legacy_hw_top3",
            label="US Large-Cap Tech No Legacy HW Top3",
            config_path=root / "config.us_large_cap_tech_no_legacy_hw_top3.yaml",
            market_id="us",
            market_label="US",
        ),
        DashboardProfile(
            id="us_large_cap_tech_quality_earnings_regime",
            label="US Large-Cap Tech Q+E + QQQ Risk-Off Cash",
            config_path=root / "config.us_large_cap_tech_quality_earnings_regime.yaml",
            market_id="us",
            market_label="US",
        ),
    ]
