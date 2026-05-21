from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from bist_factor_backtest.backtest.monthly_rotation import run_monthly_rotation_backtest
from bist_factor_backtest.cli import _load_membership_for_run
from bist_factor_backtest.config import BacktestConfig, load_config
from bist_factor_backtest.data.calendar import get_first_trading_day
from bist_factor_backtest.data.price_loader_yfinance import YFinancePriceLoader
from bist_factor_backtest.data.storage import DuckDbStorage
from bist_factor_backtest.factors.ttm import add_earnings_momentum_features


ROOT = Path("/Users/kaanece/projects/TRex")
DB_PATH = ROOT / "data" / "us_large_cap_tech_backtest.duckdb"
OUTPUT_DIR = ROOT / "outputs" / "formula_research_reference"
BASE_CONFIG = ROOT / "config.us_large_cap_tech_quality_earnings.yaml"


@dataclass(frozen=True)
class ProfileSpec:
    label: str
    family: str
    config_path: Path
    formula: str | None = None
    earnings_weight: float | None = None


PROFILES = [
    ProfileSpec(
        label="tech_quality_earnings",
        family="strategy",
        config_path=BASE_CONFIG,
    ),
    ProfileSpec(
        label="tech_quality_op_growth",
        family="strategy",
        config_path=BASE_CONFIG,
        formula="quality_plus_op_growth",
        earnings_weight=1.0,
    ),
    ProfileSpec(
        label="tech_quality_op_growth_w15",
        family="strategy",
        config_path=BASE_CONFIG,
        formula="quality_plus_op_growth",
        earnings_weight=1.5,
    ),
]

BENCHMARKS = ["QQQ", "XLK"]


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


def _summary_row(label: str, family: str, monthly: pd.DataFrame, initial_capital: float) -> dict[str, object]:
    net = pd.to_numeric(monthly["net_return"], errors="coerce")
    final_capital = float(monthly["portfolio_value_end"].iloc[-1])
    return {
        "label": label,
        "family": family,
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


def _load_benchmark_prices(config: BacktestConfig) -> pd.DataFrame:
    loader = YFinancePriceLoader()
    return loader.load(
        BENCHMARKS,
        config.data.price_preload_start or config.backtest.start_date,
        config.backtest.end_date,
        yahoo_suffix=config.data.price_symbol_suffix,
    )


def _build_benchmark_monthly(symbol: str, prices: pd.DataFrame, base_monthly: pd.DataFrame, initial_capital: float) -> pd.DataFrame:
    prepared = prices.copy()
    prepared["date"] = pd.to_datetime(prepared["date"]).dt.date
    symbol_prices = prepared[prepared["symbol"] == symbol].copy()
    months = base_monthly["month"].astype(str).tolist()
    rows: list[dict[str, object]] = []
    portfolio_value = initial_capital
    for idx, month in enumerate(months):
        buy_date = get_first_trading_day(symbol_prices, month)
        if idx + 1 < len(months):
            sell_date = get_first_trading_day(symbol_prices, months[idx + 1])
        else:
            sell_date = base_monthly.iloc[idx]["sell_date"]
        buy_row = symbol_prices[symbol_prices["date"] == buy_date]
        sell_row = symbol_prices[symbol_prices["date"] == sell_date]
        if buy_row.empty or sell_row.empty:
            continue
        buy_open = float(buy_row["open"].iloc[0])
        sell_open = float(sell_row["open"].iloc[0])
        net_return = (sell_open / buy_open) - 1 if buy_open > 0 else 0.0
        start_value = portfolio_value
        portfolio_value = portfolio_value * (1 + net_return)
        rows.append(
            {
                "month": month,
                "buy_date": buy_date,
                "sell_date": sell_date,
                "net_return": net_return,
                "portfolio_value_start": start_value,
                "portfolio_value_end": portfolio_value,
                "selected_symbols": symbol,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    base_settings = _apply_profile(PROFILES[0])
    prices, financials, membership = _load_inputs(base_settings)
    benchmark_prices = _load_benchmark_prices(base_settings)

    summary_rows: list[dict[str, object]] = []
    monthly_map: dict[str, pd.DataFrame] = {}

    for profile in PROFILES:
        settings = _apply_profile(profile)
        result = run_monthly_rotation_backtest(settings, prices, financials, membership)
        monthly = result["monthly_results"].copy()
        monthly["month"] = monthly["month"].astype(str)
        monthly["net_return"] = pd.to_numeric(monthly["net_return"], errors="coerce")
        monthly_map[profile.label] = monthly[["month", "buy_date", "sell_date", "net_return", "portfolio_value_start", "portfolio_value_end"]].copy()
        summary_rows.append(_summary_row(profile.label, profile.family, monthly, settings.backtest.initial_capital))

    base_monthly = monthly_map["tech_quality_earnings"]
    for symbol in BENCHMARKS:
        monthly = _build_benchmark_monthly(symbol, benchmark_prices, base_monthly, base_settings.backtest.initial_capital)
        monthly["month"] = monthly["month"].astype(str)
        monthly_map[symbol] = monthly[["month", "buy_date", "sell_date", "net_return", "portfolio_value_start", "portfolio_value_end"]].copy()
        summary_rows.append(_summary_row(symbol, "benchmark", monthly, base_settings.backtest.initial_capital))

    summary = pd.DataFrame(summary_rows).sort_values(["multiple", "max_drawdown"], ascending=[False, False]).reset_index(drop=True)
    summary.to_csv(OUTPUT_DIR / "us_large_cap_tech_robustness_summary.csv", index=False)

    profiles = list(monthly_map.keys())
    rolling_rows: list[dict[str, object]] = []
    for profile, monthly in monthly_map.items():
        for window in (12, 24, 36):
            rolling_rows.extend(_rolling_rows(profile, monthly, window))
    rolling = pd.DataFrame(rolling_rows)
    rolling_summary = _rolling_summary(rolling, profiles)
    rolling.to_csv(OUTPUT_DIR / "us_large_cap_tech_robustness_rolling.csv", index=False)
    rolling_summary.to_csv(OUTPUT_DIR / "us_large_cap_tech_robustness_rolling_summary.csv", index=False)

    aligned_returns = {profile: monthly_map[profile]["net_return"].reset_index(drop=True) for profile in profiles}
    bootstrap, bootstrap_summary = _block_bootstrap(aligned_returns, profiles)
    bootstrap.to_csv(OUTPUT_DIR / "us_large_cap_tech_robustness_bootstrap.csv", index=False)
    bootstrap_summary.to_csv(OUTPUT_DIR / "us_large_cap_tech_robustness_bootstrap_summary.csv", index=False)

    lines = [
        "# US Large-Cap Tech Robustness Review",
        "",
        "Profiles:",
        "- tech_quality_earnings: baseline large-cap tech PIT winner",
        "- tech_quality_op_growth: operating-profit growth variant",
        "- tech_quality_op_growth_w15: heavier op-growth sleeve",
        "- QQQ / XLK: open-to-open benchmark series matched to the strategy month schedule",
        "",
        "Full-period summary:",
    ]
    for row in summary.to_dict(orient="records"):
        period_2025 = row["period_2025_plus"]
        period_2025_text = f"{period_2025:.2f}x" if pd.notna(period_2025) else "n/a"
        lines.append(
            f"- {row['label']} ({row['family']}): {row['multiple']:.2f}x, "
            f"win={row['win_rate']:.2%}, dd={row['max_drawdown']:.2%}, avg_month={row['avg_monthly_return']:.2%}, 2025+ {period_2025_text}"
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
    lines.append("Bootstrap winner share:")
    for row in bootstrap_summary.sort_values("bootstrap_win_share", ascending=False).to_dict(orient="records"):
        lines.append(
            f"- {row['profile']}: winner_share={row['bootstrap_win_share']:.2%}, "
            f"median_multiple={row['median_multiple']:.2f}x, median_dd={row['median_max_drawdown']:.2%}"
        )
    (OUTPUT_DIR / "us_large_cap_tech_robustness_readout.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
