from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bist_factor_backtest.dashboard import project_root


@dataclass(frozen=True)
class DashboardProfile:
    id: str
    label: str
    config_path: Path
    active: bool = True


def active_dashboard_profiles() -> list[DashboardProfile]:
    root = project_root()
    return [
        DashboardProfile(
            id="momentum_watchlist",
            label="Kabul Edilen Ana Profil",
            config_path=root / "config.formula_research_momentum.yaml",
        ),
        DashboardProfile(
            id="technical_confirmation",
            label="Teknik Dogrulama Alternatifi",
            config_path=root / "config.formula_research_technical_confirmation.yaml",
        ),
        DashboardProfile(
            id="accepted_top6",
            label="Legacy Kabul Edilen Top6",
            config_path=root / "config.formula_research.yaml",
        ),
        DashboardProfile(
            id="cumhur",
            label="Cumhur",
            config_path=root / "config.formula_research_cumhur.yaml",
        ),
        DashboardProfile(
            id="momentum_watchlist_queenstocks_shadow",
            label="Kabul Edilen Ana Profil (QueenStocks Fallback Shadow)",
            config_path=root / "config.formula_research_momentum_queenstocks_shadow.yaml",
        ),
    ]
