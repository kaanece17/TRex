from __future__ import annotations

import math

import pandas as pd


def calculate_equity_curve(monthly_results: pd.DataFrame) -> pd.DataFrame:
    data = monthly_results[["month", "portfolio_value_end"]].copy()
    data = data.rename(columns={"portfolio_value_end": "value"})
    data["peak"] = data["value"].cummax()
    data["drawdown"] = data["value"] / data["peak"] - 1
    return data


def calculate_summary(monthly_results: pd.DataFrame, initial_capital: float) -> dict[str, float | int | str | None]:
    if monthly_results.empty:
        return {
            "initial_capital": initial_capital,
            "final_capital": initial_capital,
            "total_return": 0.0,
            "number_of_months": 0,
        }
    returns = monthly_results["net_return"]
    final_capital = float(monthly_results["portfolio_value_end"].iloc[-1])
    months = len(monthly_results)
    monthly_volatility = float(returns.std(ddof=0))
    monthly_sharpe = 0.0 if monthly_volatility == 0 else float(returns.mean() / monthly_volatility)
    equity = calculate_equity_curve(monthly_results)
    return {
        "initial_capital": initial_capital,
        "final_capital": final_capital,
        "total_return": final_capital / initial_capital - 1,
        "cagr": (final_capital / initial_capital) ** (12 / months) - 1,
        "average_monthly_return": float(returns.mean()),
        "monthly_volatility": monthly_volatility,
        "sharpe": monthly_sharpe * math.sqrt(12),
        "max_drawdown": float(equity["drawdown"].min()),
        "win_rate": float((returns > 0).mean()),
        "number_of_months": months,
        "best_month": str(monthly_results.loc[returns.idxmax(), "month"]),
        "worst_month": str(monthly_results.loc[returns.idxmin(), "month"]),
        "average_selected_stock_return": None,
        "turnover": 1.0,
    }

