from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from bist_factor_backtest.backtest.monthly_rotation import run_monthly_rotation_backtest
from bist_factor_backtest.cli import _load_membership_for_run
from bist_factor_backtest.config import BacktestConfig, load_config
from bist_factor_backtest.data.price_loader_yfinance import YFinancePriceLoader
from bist_factor_backtest.data.storage import DuckDbStorage
from bist_factor_backtest.factors.ttm import add_earnings_momentum_features


ROOT = Path("/Users/kaanece/projects/TRex")
CONFIG_PATH = ROOT / "config.us_large_cap_tech_quality_earnings.yaml"
DB_PATH = ROOT / "data" / "us_large_cap_tech_backtest.duckdb"
OUTPUT_DIR = ROOT / "outputs" / "formula_research_reference"


@dataclass(frozen=True)
class CandidateSpec:
    name: str
    notes: str
    regime_mode: str | None = None
    scale_factor: float | None = None


CANDIDATES = [
    CandidateSpec(
        name="tech_quality_earnings_base",
        notes="Current broad tech winner without regime cash scaling.",
    ),
    CandidateSpec(
        name="tech_quality_earnings_cash75_below200",
        notes="Scale all weights to 75% when QQQ is below its 200d SMA before rebalance.",
        regime_mode="below_200dma_scale",
        scale_factor=0.75,
    ),
    CandidateSpec(
        name="tech_quality_earnings_cash75_double_risk_off",
        notes="Scale all weights to 75% when QQQ is below 200d SMA and 60d return is negative.",
        regime_mode="below_200dma_and_negative_60d_scale",
        scale_factor=0.75,
    ),
]


def _apply_candidate(base: BacktestConfig, spec: CandidateSpec) -> BacktestConfig:
    config = deepcopy(base)
    config.project.name = spec.name
    if spec.regime_mode is None:
        config.strategy.qqq_regime_weight_scale_mode = None
        config.strategy.qqq_regime_scale_factor = 1.0
    else:
        config.strategy.qqq_regime_weight_scale_mode = spec.regime_mode
        config.strategy.qqq_regime_scale_factor = float(spec.scale_factor or 1.0)
        config.strategy.qqq_regime_sma_lookback_days = 200
        config.strategy.qqq_regime_return_lookback_days = 60
    return config


def _max_drawdown(monthly: pd.DataFrame) -> float:
    values = pd.to_numeric(monthly["portfolio_value_end"], errors="coerce")
    return float((values / values.cummax() - 1.0).min())


def _period_multiple(monthly: pd.DataFrame, start_month: str) -> float | None:
    subset = monthly[monthly["month"] >= start_month].copy()
    if subset.empty:
        return None
    start_value = float(subset["portfolio_value_start"].iloc[0])
    end_value = float(subset["portfolio_value_end"].iloc[-1])
    if start_value <= 0:
        return None
    return end_value / start_value


def _load_qqq_prices(settings: BacktestConfig) -> pd.DataFrame:
    loader = YFinancePriceLoader()
    qqq = loader.load(
        ["QQQ"],
        settings.data.price_preload_start or settings.backtest.start_date,
        settings.backtest.end_date,
        yahoo_suffix=settings.data.price_symbol_suffix,
    )
    if qqq.empty:
        return qqq
    qqq["date"] = pd.to_datetime(qqq["date"]).dt.date
    return qqq


def _load_inputs(base: BacktestConfig) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
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
    membership = _load_membership_for_run(base)
    storage.close()

    qqq = _load_qqq_prices(base)
    if not qqq.empty:
        prices = pd.concat([prices, qqq], ignore_index=True)
        prices["date"] = pd.to_datetime(prices["date"]).dt.date
        prices = (
            prices.sort_values(["symbol", "date"])
            .drop_duplicates(["symbol", "date"], keep="last")
            .reset_index(drop=True)
        )
    return prices, financials, membership


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    base = load_config(CONFIG_PATH)
    prices, financials, membership = _load_inputs(base)

    rows: list[dict[str, object]] = []
    for spec in CANDIDATES:
        settings = _apply_candidate(base, spec)
        result = run_monthly_rotation_backtest(settings, prices, financials, membership)
        monthly = result["monthly_results"].copy()
        net = pd.to_numeric(monthly["net_return"], errors="coerce")
        rows.append(
            {
                "candidate": spec.name,
                "notes": spec.notes,
                "run_id": result["run_id"],
                "months": len(monthly),
                "multiple": float(monthly["portfolio_value_end"].iloc[-1] / settings.backtest.initial_capital),
                "final_capital": float(monthly["portfolio_value_end"].iloc[-1]),
                "win_rate": float((net > 0).mean()),
                "avg_monthly_return": float(net.mean()),
                "max_drawdown": _max_drawdown(monthly),
                "period_2025_plus": _period_multiple(monthly, "2025-01"),
            }
        )

    summary = pd.DataFrame(rows)
    baseline = summary.loc[summary["candidate"] == "tech_quality_earnings_base"].iloc[0]
    summary["strict_pass"] = (
        (summary["multiple"] > float(baseline["multiple"]))
        & (summary["win_rate"] >= float(baseline["win_rate"]))
        & (summary["max_drawdown"] >= float(baseline["max_drawdown"]))
    )
    summary = summary.sort_values(["strict_pass", "multiple", "max_drawdown"], ascending=[False, False, False]).reset_index(drop=True)
    summary.to_csv(OUTPUT_DIR / "us_large_cap_tech_regime_acceptance_summary.csv", index=False)

    lines = [
        "# US Large-Cap Tech Regime Acceptance Review",
        "",
        f"- Baseline: `{baseline['candidate']}`",
        f"- Baseline multiple: `{baseline['multiple']:.2f}x`",
        f"- Baseline win rate: `{baseline['win_rate']:.2%}`",
        f"- Baseline max drawdown: `{baseline['max_drawdown']:.2%}`",
        "",
    ]
    for row in summary.to_dict("records"):
        period_2025 = row["period_2025_plus"]
        period_2025_text = f"{period_2025:.2f}x" if pd.notna(period_2025) else "n/a"
        lines.append(
            f"- `{row['candidate']}`: `{row['multiple']:.2f}x`, win `{row['win_rate']:.2%}`, "
            f"dd `{row['max_drawdown']:.2%}`, `2025+ {period_2025_text}`, strict `{'yes' if row['strict_pass'] else 'no'}`"
        )
    (OUTPUT_DIR / "us_large_cap_tech_regime_acceptance_readout.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
