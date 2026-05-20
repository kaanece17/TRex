from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from bist_factor_backtest.data.storage import DuckDbStorage


ROOT = Path("/Users/kaanece/projects/TRex")
POSITIONS_PATH = ROOT / "outputs/dashboard/momentum_watchlist/selected_positions.json"
DB_PATH = ROOT / "data/bist_backtest.duckdb"
OUTPUT_DIR = ROOT / "outputs/formula_research_reference"
SUMMARY_CSV = OUTPUT_DIR / "bist_operational_execution_summary.csv"
MONTHLY_CSV = OUTPUT_DIR / "bist_operational_execution_monthly.csv"
README_MD = OUTPUT_DIR / "bist_operational_execution_readout.md"
INITIAL_CAPITAL = 100000.0


@dataclass(frozen=True)
class Variant:
    name: str
    notes: str
    buy_day_index: int
    buy_field: str
    sell_day_index: int
    sell_field: str


VARIANTS = [
    Variant(
        "next_open_open",
        "Signal at month-end, trade next first trading day open to next first trading day open.",
        0,
        "open",
        0,
        "open",
    ),
    Variant(
        "second_open_open",
        "Delayed-open proxy: trade second trading day open to next second trading day open.",
        1,
        "open",
        1,
        "open",
    ),
    Variant(
        "next_close_close",
        "If the open cannot be captured, trade next first trading day close to next first trading day close.",
        0,
        "close",
        0,
        "close",
    ),
    Variant(
        "next_oc2_oc2",
        "VWAP proxy 1: use (open + close) / 2 on the first trading day for both entry and exit.",
        0,
        "oc2",
        0,
        "oc2",
    ),
    Variant(
        "next_hlc3_hlc3",
        "VWAP proxy 2: use (high + low + close) / 3 on the first trading day for both entry and exit.",
        0,
        "hlc3",
        0,
        "hlc3",
    ),
]


def _load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    positions = pd.DataFrame(json.loads(POSITIONS_PATH.read_text()))
    storage = DuckDbStorage(DB_PATH)
    storage.initialize()
    prices = storage.read_table("market_prices")
    storage.close()
    prices["date"] = pd.to_datetime(prices["date"]).dt.date
    positions["weight"] = pd.to_numeric(positions["weight"], errors="coerce")
    positions["month"] = positions["month"].astype(str)
    return positions, prices


def _month_offset(month: str, steps: int = 1) -> str:
    period = pd.Period(month, freq="M") + steps
    return str(period)


def _build_trading_day_lookup(prices: pd.DataFrame) -> dict[str, list[object]]:
    frame = prices[["symbol", "date", "volume"]].copy()
    frame["month"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m")
    volume = pd.to_numeric(frame["volume"], errors="coerce").fillna(0)
    positive_volume = frame[volume > 0]
    breadth_source = positive_volume if not positive_volume.empty else frame
    breadth = breadth_source.groupby(["month", "date"])["symbol"].nunique().reset_index(name="count")
    lookup: dict[str, list[object]] = {}
    for month, month_frame in breadth.groupby("month"):
        max_breadth = int(month_frame["count"].max())
        min_breadth = max(3, int(max_breadth * 0.1))
        valid = month_frame[month_frame["count"] >= min_breadth]
        if valid.empty:
            valid = month_frame
        lookup[str(month)] = sorted(valid["date"].tolist())
    return lookup


def _variant_dates(trading_day_lookup: dict[str, list[object]], month: str, variant: Variant) -> tuple[object | None, object | None]:
    current_days = trading_day_lookup.get(month, [])
    next_days = trading_day_lookup.get(_month_offset(month, 1), [])
    if len(current_days) <= variant.buy_day_index or len(next_days) <= variant.sell_day_index:
        return None, None
    return current_days[variant.buy_day_index], next_days[variant.sell_day_index]


def _build_price_lookup(prices: pd.DataFrame) -> dict[tuple[str, object], dict[str, float | None]]:
    frame = prices[["symbol", "date", "open", "high", "low", "close"]].copy()
    for field in ("open", "high", "low", "close"):
        frame[field] = pd.to_numeric(frame[field], errors="coerce")
    frame["oc2"] = (frame["open"] + frame["close"]) / 2.0
    frame["hlc3"] = (frame["high"] + frame["low"] + frame["close"]) / 3.0

    lookup: dict[tuple[str, object], dict[str, float | None]] = {}
    for row in frame.itertuples(index=False):
        values = {}
        for field in ("open", "close", "oc2", "hlc3"):
            value = getattr(row, field)
            values[field] = None if pd.isna(value) else float(value)
        lookup[(row.symbol, row.date)] = values
    return lookup


def _build_month_trade_dates(prices: pd.DataFrame, variant: Variant, months: list[str]) -> dict[str, tuple[object | None, object | None]]:
    trading_day_lookup = _build_trading_day_lookup(prices)
    return {month: _variant_dates(trading_day_lookup, month, variant) for month in months}


def _period_multiple(monthly: pd.DataFrame, start_month: str) -> float | None:
    subset = monthly[monthly["month"] >= start_month].copy()
    if subset.empty:
        return None
    start_value = float(subset["portfolio_value_start"].iloc[0])
    end_value = float(subset["portfolio_value_end"].iloc[-1])
    if start_value <= 0:
        return None
    return end_value / start_value


def _run_variant(positions: pd.DataFrame, prices: pd.DataFrame, variant: Variant) -> tuple[pd.DataFrame, dict[str, object]]:
    price_lookup = _build_price_lookup(prices)
    months = sorted(positions["month"].dropna().unique().tolist())
    month_trade_dates = _build_month_trade_dates(prices, variant, months)
    month_rows = []
    portfolio_value = INITIAL_CAPITAL
    for month, frame in positions.groupby("month"):
        buy_date, sell_date = month_trade_dates.get(month, (None, None))
        if buy_date is None or sell_date is None:
            continue
        realized = []
        for row in frame.to_dict("records"):
            buy_price = price_lookup.get((row["symbol"], buy_date), {}).get(variant.buy_field)
            sell_price = price_lookup.get((row["symbol"], sell_date), {}).get(variant.sell_field)
            if buy_price is None or sell_price is None or buy_price <= 0:
                continue
            gross_return = sell_price / buy_price - 1.0
            buy_commission = float(row.get("buy_commission_rate") or 0.0)
            sell_commission = float(row.get("sell_commission_rate") or 0.0)
            net_return = gross_return - buy_commission - sell_commission
            realized.append({"symbol": row["symbol"], "weight": float(row["weight"]), "net_return": net_return})
        if not realized:
            net = 0.0
        else:
            realized_df = pd.DataFrame(realized)
            net = float((realized_df["weight"] * realized_df["net_return"]).sum())
        start_value = portfolio_value
        portfolio_value = portfolio_value * (1 + net)
        month_rows.append(
            {
                "variant": variant.name,
                "month": month,
                "buy_date": buy_date,
                "sell_date": sell_date,
                "net_return": net,
                "portfolio_value_start": start_value,
                "portfolio_value_end": portfolio_value,
            }
        )
    monthly = pd.DataFrame(month_rows)
    curve = monthly["portfolio_value_end"].astype(float)
    summary = {
        "variant": variant.name,
        "notes": variant.notes,
        "months": len(monthly),
        "final_capital": float(curve.iloc[-1]),
        "multiple": float(curve.iloc[-1] / INITIAL_CAPITAL),
        "win_rate": float((monthly["net_return"] > 0).mean()),
        "max_drawdown": float(((curve / curve.cummax()) - 1).min()),
        "avg_monthly_return": float(monthly["net_return"].mean()),
        "period_2024_plus": _period_multiple(monthly, "2024-01"),
    }
    return monthly, summary


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    positions, prices = _load_inputs()
    summary_rows = []
    monthly_frames = []
    for variant in VARIANTS:
        monthly, summary = _run_variant(positions, prices, variant)
        summary_rows.append(summary)
        monthly_frames.append(monthly)

    summary_df = pd.DataFrame(summary_rows)
    base = summary_df.set_index("variant").loc["next_open_open"]
    summary_df["strict_gate_pass"] = (
        (summary_df["multiple"] > float(base["multiple"]))
        & (summary_df["win_rate"] >= float(base["win_rate"]))
        & (summary_df["max_drawdown"] >= float(base["max_drawdown"]))
    )
    summary_df = summary_df.sort_values(["strict_gate_pass", "multiple", "max_drawdown"], ascending=[False, False, False]).reset_index(drop=True)
    monthly_df = pd.concat(monthly_frames, ignore_index=True)
    summary_df.to_csv(SUMMARY_CSV, index=False)
    monthly_df.to_csv(MONTHLY_CSV, index=False)

    lines = [
        "# BIST Operational Execution Research",
        "",
        "## Strict Gate",
        "",
        "- Baseline is `next_open_open` because this is the closest match to the live workflow.",
        "- A variant passes only if it has:",
        "  - higher total multiple",
        "  - win rate not lower",
        "  - max drawdown not worse",
        "",
        "## Ranking",
        "",
    ]
    for row in summary_df.to_dict("records"):
        period_text = f"{row['period_2024_plus']:.2f}x" if pd.notna(row["period_2024_plus"]) else "n/a"
        lines.append(
            f"- `{row['variant']}`: `{row['multiple']:.2f}x`, `2024+ {period_text}`, "
            f"win `{row['win_rate']:.2%}`, max DD `{row['max_drawdown']:.2%}`, strict_pass=`{str(bool(row['strict_gate_pass'])).lower()}`"
        )
    passes = summary_df[summary_df["strict_gate_pass"]]
    lines += ["", "## Decision", ""]
    if passes.empty:
        lines.append("- No operational execution variant passes the strict gate.")
        lines.append("- Keep `next_open_open` as the accepted live execution assumption.")
    else:
        lines.append(f"- Promote `{passes.iloc[0]['variant']}` over `next_open_open`.")
    README_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(summary_df.to_string(index=False))


if __name__ == "__main__":
    main()
