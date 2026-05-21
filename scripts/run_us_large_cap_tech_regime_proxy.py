from __future__ import annotations

from pathlib import Path

import pandas as pd

from bist_factor_backtest.backtest.monthly_rotation import run_monthly_rotation_backtest
from bist_factor_backtest.cli import _load_membership_for_run
from bist_factor_backtest.config import load_config
from bist_factor_backtest.data.calendar import get_first_trading_day
from bist_factor_backtest.data.price_loader_yfinance import YFinancePriceLoader
from bist_factor_backtest.data.storage import DuckDbStorage
from bist_factor_backtest.factors.ttm import add_earnings_momentum_features


ROOT = Path("/Users/kaanece/projects/TRex")
CONFIG_PATH = ROOT / "config.us_large_cap_tech_quality_earnings.yaml"
DB_PATH = ROOT / "data" / "us_large_cap_tech_backtest.duckdb"
OUTPUT_DIR = ROOT / "outputs" / "formula_research_reference"


def _max_drawdown(returns: pd.Series) -> float:
    curve = (1 + returns).cumprod()
    return float((curve / curve.cummax() - 1).min())


def _load_inputs():
    settings = load_config(CONFIG_PATH)
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
    membership = _load_membership_for_run(settings)
    storage.close()
    return settings, prices, financials, membership


def _load_qqq_prices(settings) -> pd.DataFrame:
    loader = YFinancePriceLoader()
    qqq = loader.load(
        ["QQQ"],
        settings.data.price_preload_start or settings.backtest.start_date,
        settings.backtest.end_date,
        yahoo_suffix=settings.data.price_symbol_suffix,
    )
    qqq["date"] = pd.to_datetime(qqq["date"]).dt.date
    qqq = qqq.sort_values("date").reset_index(drop=True)
    close_col = "adjusted_close" if "adjusted_close" in qqq.columns else "close"
    qqq["sma_200"] = qqq[close_col].rolling(200, min_periods=200).mean()
    qqq["ret_60d"] = qqq[close_col] / qqq[close_col].shift(60) - 1
    return qqq


def _qqq_state(qqq: pd.DataFrame, buy_date) -> dict[str, bool | float | None]:
    subset = qqq[qqq["date"] < buy_date].copy()
    if subset.empty:
        return {
            "qqq_below_200dma": False,
            "qqq_ret60_negative": False,
            "qqq_double_risk_off": False,
            "qqq_ret60": None,
        }
    latest = subset.iloc[-1]
    close_col = "adjusted_close" if "adjusted_close" in subset.columns else "close"
    below_200 = bool(pd.notna(latest["sma_200"]) and latest[close_col] < latest["sma_200"])
    ret60_neg = bool(pd.notna(latest["ret_60d"]) and latest["ret_60d"] < 0)
    return {
        "qqq_below_200dma": below_200,
        "qqq_ret60_negative": ret60_neg,
        "qqq_double_risk_off": below_200 and ret60_neg,
        "qqq_ret60": float(latest["ret_60d"]) if pd.notna(latest["ret_60d"]) else None,
    }


def _run_variants(selected: pd.DataFrame, monthly: pd.DataFrame, qqq: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    variants = [
        ("baseline", None),
        ("cash75_on_below200", "cash75_on_below200"),
        ("cash75_on_double_risk_off", "cash75_on_double_risk_off"),
        ("top3_on_below200", "top3_on_below200"),
        ("top3_on_double_risk_off", "top3_on_double_risk_off"),
    ]
    summary_rows: list[dict[str, object]] = []
    monthly_frames: list[pd.DataFrame] = []

    for variant_name, mode in variants:
        rows: list[dict[str, object]] = []
        for month_row in monthly.to_dict("records"):
            month = str(month_row["month"])
            buy_date = pd.to_datetime(month_row["buy_date"]).date()
            month_positions = selected[selected["month"].astype(str) == month].copy()
            month_positions["weight"] = pd.to_numeric(month_positions["weight"], errors="coerce")
            month_positions["net_return"] = pd.to_numeric(month_positions["net_return"], errors="coerce")
            state = _qqq_state(qqq, buy_date)
            adjusted_return = float(month_positions["weight"].mul(month_positions["net_return"]).sum()) if not month_positions.empty else 0.0

            if mode == "cash75_on_below200" and state["qqq_below_200dma"]:
                adjusted_return = adjusted_return * 0.75
            elif mode == "cash75_on_double_risk_off" and state["qqq_double_risk_off"]:
                adjusted_return = adjusted_return * 0.75
            elif mode == "top3_on_below200" and state["qqq_below_200dma"] and not month_positions.empty:
                top3 = month_positions.sort_values(["selection_score", "score"], ascending=False).head(3).copy()
                top3["weight"] = top3["weight"] / top3["weight"].sum()
                adjusted_return = float(top3["weight"].mul(top3["net_return"]).sum())
            elif mode == "top3_on_double_risk_off" and state["qqq_double_risk_off"] and not month_positions.empty:
                top3 = month_positions.sort_values(["selection_score", "score"], ascending=False).head(3).copy()
                top3["weight"] = top3["weight"] / top3["weight"].sum()
                adjusted_return = float(top3["weight"].mul(top3["net_return"]).sum())

            rows.append(
                {
                    "month": month,
                    "variant": variant_name,
                    "net_return": adjusted_return,
                    "qqq_below_200dma": state["qqq_below_200dma"],
                    "qqq_ret60_negative": state["qqq_ret60_negative"],
                    "qqq_double_risk_off": state["qqq_double_risk_off"],
                    "qqq_ret60": state["qqq_ret60"],
                }
            )
        frame = pd.DataFrame(rows).sort_values("month").reset_index(drop=True)
        curve = (1 + frame["net_return"]).cumprod()
        summary_rows.append(
            {
                "variant": variant_name,
                "multiple": float(curve.iloc[-1]),
                "win_rate": float((frame["net_return"] > 0).mean()),
                "max_drawdown": _max_drawdown(frame["net_return"]),
                "risk_off_month_share": float(frame["qqq_double_risk_off"].mean()),
                "below200_month_share": float(frame["qqq_below_200dma"].mean()),
            }
        )
        monthly_frames.append(frame)

    summary = pd.DataFrame(summary_rows)
    baseline = summary.loc[summary["variant"] == "baseline"].iloc[0]
    summary["strict_pass"] = (
        (summary["multiple"] > float(baseline["multiple"]))
        & (summary["win_rate"] >= float(baseline["win_rate"]))
        & (summary["max_drawdown"] >= float(baseline["max_drawdown"]))
    )
    return summary.sort_values(["strict_pass", "multiple", "max_drawdown"], ascending=[False, False, False]).reset_index(drop=True), pd.concat(monthly_frames, ignore_index=True)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    settings, prices, financials, membership = _load_inputs()
    result = run_monthly_rotation_backtest(settings, prices, financials, membership)
    selected = result["selected_positions"].copy()
    monthly = result["monthly_results"].copy()
    monthly["month"] = monthly["month"].astype(str)
    qqq = _load_qqq_prices(settings)

    summary, monthly_all = _run_variants(selected, monthly, qqq)
    summary.to_csv(OUTPUT_DIR / "us_large_cap_tech_regime_proxy_summary.csv", index=False)
    monthly_all.to_csv(OUTPUT_DIR / "us_large_cap_tech_regime_proxy_monthly.csv", index=False)

    lines = [
        "# US Large-Cap Tech Regime Proxy",
        "",
        "Ex-ante QQQ regime proxies:",
        "- `below200`: QQQ latest close before rebalance is below 200d SMA",
        "- `double_risk_off`: below 200d SMA and 60d return < 0",
        "",
    ]
    for row in summary.to_dict("records"):
        lines.append(
            f"- {row['variant']}: multiple={row['multiple']:.2f}x, win={row['win_rate']:.2%}, "
            f"dd={row['max_drawdown']:.2%}, strict={'yes' if row['strict_pass'] else 'no'}"
        )
    (OUTPUT_DIR / "us_large_cap_tech_regime_proxy_readout.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
