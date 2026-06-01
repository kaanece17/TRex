from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from bist_factor_backtest.backtest.monthly_rotation import run_monthly_rotation_backtest
from bist_factor_backtest.cli import _load_membership_for_run, _merge_analyst_consensus_history
from bist_factor_backtest.config import BacktestConfig, load_config
from bist_factor_backtest.data.storage import DuckDbStorage
from bist_factor_backtest.factors.ttm import add_ttm_values, add_earnings_momentum_features


ROOT = Path("/Users/kaanece/projects/TRex")
DB_PATH = ROOT / "data" / "us_large_cap_tech_backtest.duckdb"
OUTPUT_DIR = ROOT / "outputs" / "formula_research_reference"
BASE_CONFIG = ROOT / "config.us_large_cap_tech_quality_earnings.yaml"
SUMMARY_CSV = OUTPUT_DIR / "us_large_cap_tech_pit_signal_robustness_summary.csv"
ROLLING_CSV = OUTPUT_DIR / "us_large_cap_tech_pit_signal_robustness_rolling.csv"
ROLLING_SUMMARY_CSV = OUTPUT_DIR / "us_large_cap_tech_pit_signal_robustness_rolling_summary.csv"
BOOTSTRAP_CSV = OUTPUT_DIR / "us_large_cap_tech_pit_signal_robustness_bootstrap.csv"
BOOTSTRAP_SUMMARY_CSV = OUTPUT_DIR / "us_large_cap_tech_pit_signal_robustness_bootstrap_summary.csv"
README_MD = OUTPUT_DIR / "us_large_cap_tech_pit_signal_robustness_readout.md"


@dataclass(frozen=True)
class ProfileSpec:
    label: str
    notes: str
    scoring_updates: dict[str, float | int | None]


PROFILES = [
    ProfileSpec(
        label="tech_quality_earnings_baseline",
        notes="Baseline large-cap tech quality plus earnings profile.",
        scoring_updates={},
    ),
    ProfileSpec(
        label="tech_announcement_freshness",
        notes="Favor fresher reports at rebalance time.",
        scoring_updates={"announcement_freshness_weight": 0.15},
    ),
    ProfileSpec(
        label="tech_announcement_drift",
        notes="Add a short post-announcement drift sleeve as a PEAD-style proxy.",
        scoring_updates={
            "announcement_drift_weight": 0.20,
            "announcement_drift_lookback_days": 20,
        },
    ),
    ProfileSpec(
        label="tech_asset_growth_guard",
        notes="Penalize aggressive asset growers.",
        scoring_updates={
            "asset_growth_penalty": 0.10,
            "asset_growth_threshold": 0.25,
        },
    ),
]


def _load_inputs(base_config: BacktestConfig) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    storage = DuckDbStorage(DB_PATH)
    storage.initialize()
    prices = storage.read_table("market_prices")
    financials = storage.read_table("financial_snapshots")
    analyst_snapshots = storage.read_table("analyst_snapshot_history")
    analyst_consensus = storage.read_table("analyst_consensus_history")
    financials["announcement_datetime"] = pd.to_datetime(financials["announcement_datetime"], errors="coerce")
    financials = (
        financials.sort_values(["symbol", "period_end", "announcement_datetime"])
        .drop_duplicates(["symbol", "period_end"], keep="last")
        .reset_index(drop=True)
    )
    financials = (
        financials.sort_values(["symbol", "fiscal_year", "fiscal_quarter", "announcement_datetime"])
        .drop_duplicates(["symbol", "fiscal_year", "fiscal_quarter"], keep="last")
        .reset_index(drop=True)
    )
    financials = add_ttm_values(financials)
    financials = add_earnings_momentum_features(financials)
    financials = _merge_analyst_consensus_history(financials, analyst_consensus)
    membership = _load_membership_for_run(base_config)
    storage.close()
    return prices, financials, membership, analyst_snapshots


def _apply_profile(base: BacktestConfig, spec: ProfileSpec) -> BacktestConfig:
    settings = deepcopy(base)
    settings.project.name = spec.label
    for key, value in spec.scoring_updates.items():
        setattr(settings.scoring, key, value)
    return settings


def _max_drawdown(returns: pd.Series) -> float:
    curve = (1 + returns).cumprod()
    peak = curve.cummax()
    return float((curve / peak - 1).min())


def _summary_row(label: str, monthly: pd.DataFrame, initial_capital: float) -> dict[str, object]:
    net = pd.to_numeric(monthly["net_return"], errors="coerce")
    final_capital = float(monthly["portfolio_value_end"].iloc[-1])
    return {
        "label": label,
        "months": len(monthly),
        "multiple": float(final_capital / initial_capital),
        "final_capital": final_capital,
        "win_rate": float((net > 0).mean()),
        "avg_monthly_return": float(net.mean()),
        "max_drawdown": _max_drawdown(net),
        "period_2025_plus": _period_multiple(monthly, "2025-01"),
    }


def _period_multiple(monthly: pd.DataFrame, start_month: str) -> float | None:
    subset = monthly[monthly["month"] >= start_month].copy()
    if subset.empty:
        return None
    start_value = float(subset["portfolio_value_start"].iloc[0])
    end_value = float(subset["portfolio_value_end"].iloc[-1])
    if start_value <= 0:
        return None
    return end_value / start_value


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
                    "median_max_drawdown": float(subset.loc[subset["profile"] == profile, "max_drawdown"].median()),
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
    base = load_config(BASE_CONFIG)
    prices, financials, membership, analyst_snapshots = _load_inputs(base)

    monthly_by_profile: dict[str, pd.DataFrame] = {}
    summary_rows: list[dict[str, object]] = []
    for spec in PROFILES:
        config = _apply_profile(base, spec)
        print(f"running {spec.label}...", flush=True)
        result = run_monthly_rotation_backtest(
            config,
            prices,
            financials,
            membership,
            analyst_snapshots=analyst_snapshots,
        )
        monthly = result["monthly_results"].copy()
        monthly["profile"] = spec.label
        monthly_by_profile[spec.label] = monthly
        row = _summary_row(spec.label, monthly, config.backtest.initial_capital)
        row["notes"] = spec.notes
        summary_rows.append(row)
        print(
            f"done {spec.label}: multiple={row['multiple']:.2f}x win={row['win_rate']:.2%} dd={row['max_drawdown']:.2%}",
            flush=True,
        )

    summary = pd.DataFrame(summary_rows).sort_values("multiple", ascending=False).reset_index(drop=True)
    summary.to_csv(SUMMARY_CSV, index=False)

    rolling_rows: list[dict[str, object]] = []
    for profile, monthly in monthly_by_profile.items():
        for window in [12, 24, 36]:
            rolling_rows.extend(_rolling_rows(profile, monthly, window))
    rolling = pd.DataFrame(rolling_rows)
    rolling.to_csv(ROLLING_CSV, index=False)
    profiles = [spec.label for spec in PROFILES]
    rolling_summary = _rolling_summary(rolling, profiles)
    rolling_summary.to_csv(ROLLING_SUMMARY_CSV, index=False)

    returns_by_profile = {
        profile: pd.to_numeric(monthly_by_profile[profile]["net_return"], errors="coerce").reset_index(drop=True)
        for profile in profiles
    }
    bootstrap, bootstrap_summary = _block_bootstrap(returns_by_profile, profiles)
    bootstrap.to_csv(BOOTSTRAP_CSV, index=False)
    bootstrap_summary.to_csv(BOOTSTRAP_SUMMARY_CSV, index=False)

    top = summary.iloc[0]
    lines = [
        "# US Large-Cap Tech PIT Signal Robustness",
        "",
        "Profiles:",
    ]
    for spec in PROFILES:
        lines.append(f"- {spec.label}: {spec.notes}")
    lines.extend(
        [
            "",
            "Full-period summary:",
        ]
    )
    for row in summary.to_dict("records"):
        period_text = f"{row['period_2025_plus']:.2f}x" if pd.notna(row["period_2025_plus"]) else "n/a"
        lines.append(
            f"- {row['label']}: {row['multiple']:.2f}x, win={row['win_rate']:.2%}, "
            f"dd={row['max_drawdown']:.2%}, avg_month={row['avg_monthly_return']:.2%}, 2025+ {period_text}"
        )
    lines.extend(
        [
            "",
            f"Winner: `{top['label']}`",
            "",
            "Rolling winner share:",
        ]
    )
    for row in rolling_summary.sort_values(["window_months", "winner_share"], ascending=[True, False]).to_dict("records"):
        lines.append(
            f"- {int(row['window_months'])}m | {row['profile']}: winner_share={row['winner_share']:.2%}, "
            f"median_multiple={row['median_multiple']:.2f}x, median_dd={row['median_max_drawdown']:.2%}"
        )
    lines.append("")
    lines.append("Bootstrap winner share:")
    for row in bootstrap_summary.sort_values("bootstrap_win_share", ascending=False).to_dict("records"):
        lines.append(
            f"- {row['profile']}: winner_share={row['bootstrap_win_share']:.2%}, "
            f"median_multiple={row['median_multiple']:.2f}x, median_dd={row['median_max_drawdown']:.2%}"
        )
    README_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
