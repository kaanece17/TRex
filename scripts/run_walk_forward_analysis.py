from __future__ import annotations

import math
from copy import deepcopy
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from bist_factor_backtest.backtest.monthly_rotation import run_monthly_rotation_backtest
from bist_factor_backtest.config import BacktestConfig, load_config
from bist_factor_backtest.data.universe import load_universe_membership


VARIANTS: list[dict] = [
    {
        "name": "current_note_best_fit",
        "description": "Current note_best_fit config",
        "updates": {},
    },
    {
        "name": "top3_concentrated",
        "description": "More concentrated portfolio with top 3 names",
        "updates": {"strategy": {"top_n": 3}},
    },
    {
        "name": "top7_diversified",
        "description": "More diversified portfolio with top 7 names",
        "updates": {"strategy": {"top_n": 7}},
    },
    {
        "name": "liquidity_5m",
        "description": "Require minimum 5m average 20d turnover",
        "updates": {"filters": {"min_avg_turnover_20d": 5_000_000}},
    },
]

SPLITS: list[dict[str, str]] = [
    {"name": "era_2020_2021", "start_date": "2020-01-01", "end_date": "2021-12-31"},
    {"name": "era_2022_2023", "start_date": "2022-01-01", "end_date": "2023-12-31"},
    {"name": "era_2024_2026ytd", "start_date": "2024-01-01", "end_date": "2026-05-31"},
]


def _apply_updates(config: BacktestConfig, updates: dict) -> BacktestConfig:
    payload = config.model_dump()
    merged = deepcopy(payload)
    for section, values in updates.items():
        merged[section].update(values)
    return BacktestConfig.model_validate(merged)


def _set_dates(config: BacktestConfig, start_date: str, end_date: str) -> BacktestConfig:
    payload = config.model_dump()
    payload["backtest"]["start_date"] = start_date
    payload["backtest"]["end_date"] = end_date
    return BacktestConfig.model_validate(payload)


def _subset_prices(prices: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    data = prices.copy()
    data["date"] = pd.to_datetime(data["date"])
    start = pd.Timestamp(start_date) - pd.Timedelta(days=40)
    end = pd.Timestamp(end_date)
    return data[(data["date"] >= start) & (data["date"] <= end)].copy()


def _subset_financials(financials: pd.DataFrame, end_date: str) -> pd.DataFrame:
    data = financials.copy()
    data["period_end"] = pd.to_datetime(data["period_end"], errors="coerce")
    cutoff = pd.Timestamp(end_date)
    return data[data["period_end"].notna() & (data["period_end"] <= cutoff)].copy()


def _max_drawdown(portfolio_values: pd.Series) -> float:
    rolling_peak = portfolio_values.cummax()
    drawdown = portfolio_values / rolling_peak - 1.0
    return float(drawdown.min())


def _annualized_multiple(end_value: float, start_value: float, months: int) -> float:
    if months <= 0 or start_value <= 0:
        return float("nan")
    years = months / 12.0
    return float((end_value / start_value) ** (1.0 / years))


def summarize_run(monthly_results: pd.DataFrame) -> dict[str, float | int]:
    monthly = monthly_results.sort_values("month").reset_index(drop=True)
    months = len(monthly)
    start_value = float(monthly.iloc[0]["portfolio_value_start"])
    end_value = float(monthly.iloc[-1]["portfolio_value_end"])
    net_returns = monthly["net_return"].astype(float)
    return {
        "months": months,
        "start_value": start_value,
        "end_value": end_value,
        "gross_multiple": end_value / start_value,
        "annualized_multiple": _annualized_multiple(end_value, start_value, months),
        "avg_monthly_return_pct": float(net_returns.mean() * 100.0),
        "median_monthly_return_pct": float(net_returns.median() * 100.0),
        "up_month_ratio": float((net_returns > 0).mean()),
        "max_drawdown_pct": float(_max_drawdown(monthly["portfolio_value_end"].astype(float)) * 100.0),
    }


def build_markdown_report(summary_df: pd.DataFrame, output_path: Path) -> None:
    lines: list[str] = []
    lines.append("# Walk-Forward Analysis")
    lines.append("")
    lines.append("Goal:")
    lines.append("- Reduce overfit risk by comparing a small set of intuitive variants across separate market eras.")
    lines.append("")
    lines.append("Splits:")
    for split in SPLITS:
        lines.append(f"- `{split['name']}`: `{split['start_date']}` -> `{split['end_date']}`")
    lines.append("")

    overall = summary_df[summary_df["split"] == "full_period"].copy()
    if not overall.empty:
        lines.append("## Full Period Ranking")
        lines.append("")
        top = overall.sort_values(["gross_multiple", "max_drawdown_pct"], ascending=[False, False])
        for _, row in top.iterrows():
            lines.append(
                f"- `{row['variant']}`: "
                f"multiple `{row['gross_multiple']:.2f}x`, "
                f"annualized `{row['annualized_multiple']:.2f}x`, "
                f"max DD `{row['max_drawdown_pct']:.2f}%`, "
                f"median month `{row['median_monthly_return_pct']:.2f}%`"
            )
        lines.append("")

    lines.append("## Era-by-Era Results")
    lines.append("")
    for split in ["era_2020_2021", "era_2022_2023", "era_2024_2026ytd"]:
        lines.append(f"### {split}")
        lines.append("")
        block = summary_df[summary_df["split"] == split].sort_values(
            ["gross_multiple", "median_monthly_return_pct"], ascending=[False, False]
        )
        for _, row in block.iterrows():
            lines.append(
                f"- `{row['variant']}`: "
                f"`{row['gross_multiple']:.2f}x`, "
                f"avg month `{row['avg_monthly_return_pct']:.2f}%`, "
                f"median month `{row['median_monthly_return_pct']:.2f}%`, "
                f"max DD `{row['max_drawdown_pct']:.2f}%`"
            )
        lines.append("")

    pivot = summary_df.pivot(index="variant", columns="split", values="gross_multiple").reset_index()
    pivot["worst_split_multiple"] = pivot[[c for c in pivot.columns if c.startswith("era_")]].min(axis=1)
    pivot["median_split_multiple"] = pivot[[c for c in pivot.columns if c.startswith("era_")]].median(axis=1)
    robust = pivot.sort_values(["worst_split_multiple", "median_split_multiple"], ascending=False)
    lines.append("## Robustness Read")
    lines.append("")
    if not robust.empty:
        best = robust.iloc[0]
        lines.append(
            f"- Most robust by worst-era / median-era multiple: `{best['variant']}` "
            f"(worst era `{best['worst_split_multiple']:.2f}x`, median era `{best['median_split_multiple']:.2f}x`)."
        )
    lines.append("- Use this section as a guardrail, not as a hyper-optimization target.")
    lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    repo_root = Path("/Users/kaanece/projects/TRex")
    config = load_config(repo_root / "config.formula_research.yaml")
    output_dir = repo_root / "outputs" / "walk_forward_note_best_fit"
    output_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(repo_root / "data" / "bist_backtest.duckdb"), read_only=True)
    prices = con.execute("select * from market_prices").df()
    financials = con.execute("select * from financial_snapshots").df()
    membership = load_universe_membership(
        config.universe.membership_file,
        config.universe.symbol_aliases_file,
    )

    rows: list[dict] = []
    for variant in VARIANTS:
        variant_config = _apply_updates(config, variant["updates"])
        for split in SPLITS + [{"name": "full_period", "start_date": "2020-01-01", "end_date": "2026-05-31"}]:
            print(f"running {variant['name']} on {split['name']}")
            split_config = _set_dates(variant_config, split["start_date"], split["end_date"])
            split_prices = _subset_prices(prices, split["start_date"], split["end_date"])
            split_financials = _subset_financials(financials, split["end_date"])
            result = run_monthly_rotation_backtest(split_config, split_prices, split_financials, membership)
            summary = summarize_run(result["monthly_results"])
            rows.append(
                {
                    "variant": variant["name"],
                    "description": variant["description"],
                    "split": split["name"],
                    **summary,
                }
            )

    summary_df = pd.DataFrame(rows)
    summary_df.to_csv(output_dir / "walk_forward_summary.csv", index=False)
    build_markdown_report(summary_df, output_dir / "walk_forward_analysis.md")
    print(f"wrote {output_dir / 'walk_forward_summary.csv'}")
    print(f"wrote {output_dir / 'walk_forward_analysis.md'}")


if __name__ == "__main__":
    main()
