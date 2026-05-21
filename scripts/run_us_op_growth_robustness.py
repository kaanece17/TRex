from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from bist_factor_backtest.backtest.monthly_rotation import run_monthly_rotation_backtest
from bist_factor_backtest.cli import _load_membership_for_run
from bist_factor_backtest.config import BacktestConfig, load_config
from bist_factor_backtest.data.storage import DuckDbStorage
from bist_factor_backtest.factors.ttm import add_earnings_momentum_features


ROOT = Path("/Users/kaanece/projects/TRex")
DB_PATH = ROOT / "data" / "us_backtest.duckdb"
OUTPUT_DIR = ROOT / "outputs" / "formula_research_reference"


@dataclass(frozen=True)
class ProfileSpec:
    label: str
    family: str
    config_path: Path
    formula: str | None = None
    earnings_weight: float | None = None


PROFILES = [
    ProfileSpec(
        label="us_momentum",
        family="baseline",
        config_path=ROOT / "config.us_industrials_momentum.yaml",
    ),
    ProfileSpec(
        label="us_quality_scorecap",
        family="quality",
        config_path=ROOT / "config.us_industrials_quality_scorecap.yaml",
    ),
    ProfileSpec(
        label="us_quality_earnings",
        family="quality_earnings",
        config_path=ROOT / "config.us_industrials_quality_earnings.yaml",
    ),
    ProfileSpec(
        label="us_quality_op_growth",
        family="quality_op_growth",
        config_path=ROOT / "config.us_industrials_quality_earnings.yaml",
        formula="quality_plus_op_growth",
        earnings_weight=1.0,
    ),
]


def _load_inputs(base_config: BacktestConfig) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    storage = DuckDbStorage(DB_PATH)
    storage.initialize()
    prices = storage.read_table("market_prices")
    financials = storage.read_table("financial_snapshots")
    financials["announcement_datetime"] = pd.to_datetime(financials["announcement_datetime"], errors="coerce")
    financials = (
        financials.sort_values(["symbol", "period_end", "announcement_datetime"])
        .drop_duplicates(["symbol", "period_end", "announcement_datetime"], keep="last")
        .reset_index(drop=True)
    )
    financials = add_earnings_momentum_features(financials)
    membership = _load_membership_for_run(base_config)
    storage.close()
    return prices, financials, membership


def _apply_profile(spec: ProfileSpec) -> BacktestConfig:
    settings = load_config(spec.config_path)
    if spec.formula is not None:
        settings = deepcopy(settings)
        settings.project.name = spec.label
        settings.scoring.formula = spec.formula
        if spec.earnings_weight is not None:
            settings.scoring.earnings_weight = spec.earnings_weight
    return settings


def _max_drawdown(returns: pd.Series) -> float:
    curve = (1 + returns).cumprod()
    peak = curve.cummax()
    return float((curve / peak - 1).min())


def _summary_row(profile: ProfileSpec, settings: BacktestConfig, result: dict) -> dict[str, object]:
    monthly = result["monthly_results"].copy()
    net = pd.to_numeric(monthly["net_return"], errors="coerce")
    return {
        "label": profile.label,
        "family": profile.family,
        "run_id": result["run_id"],
        "months": len(monthly),
        "multiple": float(monthly["portfolio_value_end"].iloc[-1] / settings.backtest.initial_capital),
        "final_capital": float(monthly["portfolio_value_end"].iloc[-1]),
        "win_rate": float((net > 0).mean()),
        "avg_monthly_return": float(net.mean()),
        "max_drawdown": _max_drawdown(net),
    }


def _rolling_rows(profile: str, monthly: pd.DataFrame, window: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    returns = monthly["net_return"].reset_index(drop=True)
    months = monthly["month"].reset_index(drop=True)
    for start in range(0, len(monthly) - window + 1):
        sub = returns.iloc[start : start + window]
        rows.append(
            {
                "profile": profile,
                "window_months": window,
                "start_month": months.iloc[start],
                "end_month": months.iloc[start + window - 1],
                "multiple": float((1 + sub).prod()),
                "avg_month_return": float(sub.mean()),
                "win_rate": float((sub > 0).mean()),
                "max_drawdown": _max_drawdown(sub),
            }
        )
    return rows


def _rolling_summary(rolling: pd.DataFrame, profiles: list[str]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for window, subset in rolling.groupby("window_months"):
        pivot = subset.pivot(index=["start_month", "end_month"], columns="profile", values="multiple").reset_index()
        pivot["winner"] = pivot[profiles].idxmax(axis=1)
        for profile in profiles:
            rows.append(
                {
                    "window_months": window,
                    "profile": profile,
                    "winner_share": float((pivot["winner"] == profile).mean()),
                    "median_multiple": float(pivot[profile].median()),
                    "p25_multiple": float(pivot[profile].quantile(0.25)),
                    "p75_multiple": float(pivot[profile].quantile(0.75)),
                    "median_max_drawdown": float(
                        subset.loc[subset["profile"] == profile, "max_drawdown"].median()
                    ),
                }
            )
    return pd.DataFrame(rows)


def _block_bootstrap(
    returns_by_profile: dict[str, pd.Series],
    profiles: list[str],
    block_size: int = 6,
    simulations: int = 2000,
    seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    n_months = len(next(iter(returns_by_profile.values())))
    max_start = n_months - block_size
    rows: list[dict[str, object]] = []
    for sim in range(simulations):
        sampled_idx: list[int] = []
        while len(sampled_idx) < n_months:
            start = int(rng.integers(0, max_start + 1))
            sampled_idx.extend(range(start, start + block_size))
        sampled_idx = sampled_idx[:n_months]
        for profile, returns in returns_by_profile.items():
            sampled = returns.iloc[sampled_idx].reset_index(drop=True)
            rows.append(
                {
                    "simulation": sim,
                    "profile": profile,
                    "multiple": float((1 + sampled).prod()),
                    "max_drawdown": _max_drawdown(sampled),
                    "win_rate": float((sampled > 0).mean()),
                }
            )
    bootstrap = pd.DataFrame(rows)
    winners = (
        bootstrap.pivot(index="simulation", columns="profile", values="multiple")[profiles]
        .idxmax(axis=1)
        .value_counts(normalize=True)
        .rename_axis("profile")
        .reset_index(name="bootstrap_win_share")
    )
    summary = (
        bootstrap.groupby("profile")
        .agg(
            median_multiple=("multiple", "median"),
            p25_multiple=("multiple", lambda s: float(s.quantile(0.25))),
            p75_multiple=("multiple", lambda s: float(s.quantile(0.75))),
            median_max_drawdown=("max_drawdown", "median"),
            median_win_rate=("win_rate", "median"),
        )
        .reset_index()
        .merge(winners, on="profile", how="left")
        .fillna({"bootstrap_win_share": 0.0})
    )
    return bootstrap, summary


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    base_settings = _apply_profile(PROFILES[0])
    prices, financials, membership = _load_inputs(base_settings)

    summary_rows: list[dict[str, object]] = []
    monthly_map: dict[str, pd.DataFrame] = {}

    for profile in PROFILES:
        settings = _apply_profile(profile)
        result = run_monthly_rotation_backtest(settings, prices, financials, membership)
        monthly = result["monthly_results"].copy()
        monthly["month"] = monthly["month"].astype(str)
        monthly["net_return"] = pd.to_numeric(monthly["net_return"], errors="coerce")
        monthly_map[profile.label] = monthly[["month", "net_return"]].copy()
        summary_rows.append(_summary_row(profile, settings, result))

    summary = pd.DataFrame(summary_rows).sort_values(["multiple", "max_drawdown"], ascending=[False, False]).reset_index(drop=True)
    summary.to_csv(OUTPUT_DIR / "us_op_growth_acceptance_summary.csv", index=False)

    profiles = [profile.label for profile in PROFILES]
    rolling_rows: list[dict[str, object]] = []
    for profile, monthly in monthly_map.items():
        for window in (12, 24, 36):
            rolling_rows.extend(_rolling_rows(profile, monthly, window))
    rolling = pd.DataFrame(rolling_rows)
    rolling_summary = _rolling_summary(rolling, profiles)
    rolling.to_csv(OUTPUT_DIR / "us_op_growth_acceptance_rolling.csv", index=False)
    rolling_summary.to_csv(OUTPUT_DIR / "us_op_growth_acceptance_rolling_summary.csv", index=False)

    aligned_returns = {profile: monthly_map[profile]["net_return"].reset_index(drop=True) for profile in profiles}
    bootstrap, bootstrap_summary = _block_bootstrap(aligned_returns, profiles)
    bootstrap.to_csv(OUTPUT_DIR / "us_op_growth_acceptance_bootstrap.csv", index=False)
    bootstrap_summary.to_csv(OUTPUT_DIR / "us_op_growth_acceptance_bootstrap_summary.csv", index=False)

    lines = [
        "# US OP-Growth Acceptance Review",
        "",
        "Profiles:",
        "- us_momentum: original baseline",
        "- us_quality_scorecap: prior quality baseline",
        "- us_quality_earnings: current US winner",
        "- us_quality_op_growth: evidence-based challenger from PEAD / operating-profit growth analysis",
        "",
        "Full-period summary:",
    ]
    for row in summary.to_dict(orient="records"):
        lines.append(
            f"- {row['label']} ({row['family']}): {row['multiple']:.2f}x, "
            f"win={row['win_rate']:.2%}, dd={row['max_drawdown']:.2%}, avg_month={row['avg_monthly_return']:.2%}"
        )
    lines.append("")
    lines.append("Rolling winner share:")
    for row in rolling_summary.sort_values(["window_months", "winner_share"], ascending=[True, False]).to_dict(orient="records"):
        lines.append(
            f"- {row['window_months']}m | {row['profile']}: "
            f"winner_share={row['winner_share']:.2%}, median_multiple={row['median_multiple']:.2f}x, "
            f"median_dd={row['median_max_drawdown']:.2%}"
        )
    lines.append("")
    lines.append("Bootstrap summary:")
    for row in bootstrap_summary.sort_values("bootstrap_win_share", ascending=False).to_dict(orient="records"):
        lines.append(
            f"- {row['profile']}: bootstrap_win_share={row['bootstrap_win_share']:.2%}, "
            f"median_multiple={row['median_multiple']:.2f}x, median_dd={row['median_max_drawdown']:.2%}"
        )
    (OUTPUT_DIR / "us_op_growth_acceptance_readout.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
