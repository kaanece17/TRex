from __future__ import annotations

import calendar
import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from bist_factor_backtest.backtest.monthly_rotation import (
    _apply_hold_buffer_rule,
    _apply_position_quality_guard_rule,
    _apply_technical_confirmation_rule,
    _apply_x1_soft_penalty_rule,
    _attach_note_best_fit_growth_inputs,
    _attach_universe_metadata,
    _calculate_universe_breadth_above_sma,
    _resolve_effective_top_n,
)
from bist_factor_backtest.backtest.metrics import calculate_summary
from bist_factor_backtest.backtest.portfolio import build_positions
from bist_factor_backtest.config import BacktestConfig
from bist_factor_backtest.data.calendar import get_last_trading_day
from bist_factor_backtest.data.point_in_time import get_latest_known_annual_financials, get_latest_known_financials
from bist_factor_backtest.data.universe import get_universe_for_date
from bist_factor_backtest.dashboard.profiles import DashboardProfile, active_dashboard_profiles
from bist_factor_backtest.factors.filters import FilterSettings, apply_filters, missing_financial_fields
from bist_factor_backtest.factors.firm_value import attach_market_cap_firm_value
from bist_factor_backtest.factors.liquidity import (
    attach_avg_turnover_20d,
    attach_recent_return_20d,
    attach_recent_return_60d,
)
from bist_factor_backtest.factors.scoring import calculate_scores


@dataclass(frozen=True)
class RefreshStatus:
    profile_id: str
    label: str
    config_path: str
    market_id: str
    market_label: str
    run_id: str | None
    active: bool
    last_refreshed_at: str
    latest_data_month: str | None
    refresh_status: str
    message: str | None = None


def dashboard_root(root: Path | None = None) -> Path:
    if root is not None:
        return root
    return Path("outputs/dashboard")


def write_dashboard_manifest(root: Path, statuses: list[RefreshStatus]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "profiles": [asdict(status) for status in statuses],
    }
    (root / "manifest.json").write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def build_profile_dashboard_dataset(
    output_root: Path,
    profile: DashboardProfile,
    config: BacktestConfig,
    result: dict[str, pd.DataFrame | str],
    prices: pd.DataFrame | None = None,
    membership: pd.DataFrame | None = None,
    financial_snapshots: pd.DataFrame | None = None,
) -> RefreshStatus:
    monthly_results = _normalize_dates(result["monthly_results"])
    selected_positions = _normalize_dates(result["selected_positions"])
    planned_positions = _normalize_dates(result.get("planned_positions"))
    rejected_candidates = _normalize_dates(result["rejected_candidates"])
    candidate_diagnostics = _normalize_dates(result["candidate_diagnostics"])
    monthly_regimes = build_monthly_regimes(config, monthly_results, prices, membership)
    preview = build_next_month_preview(
        config=config,
        prices=prices,
        financial_snapshots=financial_snapshots,
        membership=membership,
        planned_positions=planned_positions,
    )
    preview_positions = preview["positions"]
    preview_missing_financials = preview["missing_financials"]
    preview_month = preview["preview_month"]
    preview_basis_date = preview["basis_date"]
    preview_regime = preview["regime"]
    if not preview_regime.empty:
        monthly_regimes = pd.concat([monthly_regimes, preview_regime], ignore_index=True)
        monthly_regimes = monthly_regimes.drop_duplicates(subset=["month"], keep="last")

    profile_dir = output_root / profile.id
    profile_dir.mkdir(parents=True, exist_ok=True)

    symbol_confidence = build_symbol_confidence(selected_positions)
    if not selected_positions.empty:
        if "used_announcement_datetime" in selected_positions.columns:
            selected_positions["used_announcement_date"] = pd.to_datetime(
                selected_positions["used_announcement_datetime"], errors="coerce"
            ).dt.strftime("%Y-%m-%d")
        if "announcement_date" in selected_positions.columns:
            fallback_dates = pd.to_datetime(selected_positions["announcement_date"], errors="coerce").dt.strftime("%Y-%m-%d")
            if "used_announcement_date" not in selected_positions.columns:
                selected_positions["used_announcement_date"] = fallback_dates
            else:
                selected_positions["used_announcement_date"] = selected_positions["used_announcement_date"].fillna(fallback_dates)
    selected_with_confidence = selected_positions.merge(symbol_confidence, on="symbol", how="left")
    if "confidence_level" not in selected_with_confidence.columns:
        selected_with_confidence["confidence_level"] = "neutral"
    else:
        selected_with_confidence["confidence_level"] = selected_with_confidence["confidence_level"].fillna("neutral")
    planned_with_confidence = planned_positions.merge(symbol_confidence, on="symbol", how="left") if not planned_positions.empty else planned_positions.copy()
    if not planned_with_confidence.empty:
        if "confidence_level" not in planned_with_confidence.columns:
            planned_with_confidence["confidence_level"] = "neutral"
        else:
            planned_with_confidence["confidence_level"] = planned_with_confidence["confidence_level"].fillna("neutral")
    preview_with_confidence = preview_positions.merge(symbol_confidence, on="symbol", how="left") if not preview_positions.empty else preview_positions.copy()
    if not preview_with_confidence.empty:
        if "confidence_level" not in preview_with_confidence.columns:
            preview_with_confidence["confidence_level"] = "neutral"
        else:
            preview_with_confidence["confidence_level"] = preview_with_confidence["confidence_level"].fillna("neutral")
        preview_with_confidence = _finalize_display_positions(preview_with_confidence)
    rejected_with_rank = _attach_provisional_rank(rejected_candidates, candidate_diagnostics)
    display_positions = build_display_positions(
        planned_with_confidence,
        selected_with_confidence,
        rejected_with_rank,
        str(monthly_results["month"].iloc[-1]) if not monthly_results.empty else None,
    )
    display_positions = _attach_monthly_regimes(display_positions, monthly_regimes)
    missing_financials = build_missing_financials(rejected_with_rank)
    summary = build_summary(
        config,
        monthly_results,
        display_positions,
        selected_with_confidence,
        monthly_regimes,
        preview_available=bool(preview_month),
        preview_positions=preview_with_confidence,
    )
    current_month_alerts = build_current_month_alerts(missing_financials, summary["current_month"])
    summary["profile_id"] = profile.id
    summary["profile_label"] = profile.label
    summary["config_path"] = str(profile.config_path)
    summary["run_id"] = str(result["run_id"])
    summary["generated_at"] = datetime.now(UTC).isoformat()
    summary["preview_month"] = preview_month
    summary["preview_basis_date"] = preview_basis_date
    summary["current_display_month"] = preview_month or summary["current_month"]
    summary["current_display_mode"] = "preview" if preview_month else "current"

    files = {
        "summary.json": summary,
        "monthly_returns.json": _records(monthly_results),
        "monthly_regimes.json": _records(monthly_regimes),
        "selected_positions.json": _records(display_positions),
        "next_month_preview.json": _records(preview_with_confidence),
        "next_month_preview_alerts.json": _records(preview_missing_financials),
        "next_month_preview_stale_bases.json": _records(
            build_stale_financial_base_alerts(preview_with_confidence, preview_month)
        ),
        "missing_financials.json": _records(missing_financials),
        "current_month_alerts.json": _records(current_month_alerts),
        "current_month_stale_bases.json": _records(build_stale_financial_base_alerts(display_positions, summary["current_month"])),
        "symbol_confidence.json": _records(symbol_confidence),
    }
    for filename, payload in files.items():
        (profile_dir / filename).write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    return RefreshStatus(
        profile_id=profile.id,
        label=profile.label,
        config_path=str(profile.config_path),
        market_id=profile.market_id,
        market_label=profile.market_label,
        run_id=str(result["run_id"]),
        active=profile.active,
        last_refreshed_at=datetime.now(UTC).isoformat(),
        latest_data_month=str(monthly_results["month"].iloc[-1]) if not monthly_results.empty else None,
        refresh_status="success",
    )


def build_summary(
    config: BacktestConfig,
    monthly_results: pd.DataFrame,
    display_positions: pd.DataFrame,
    realized_positions: pd.DataFrame,
    monthly_regimes: pd.DataFrame,
    preview_available: bool = False,
    preview_positions: pd.DataFrame | None = None,
) -> dict[str, object]:
    latest_data_month = str(monthly_results["month"].iloc[-1]) if not monthly_results.empty else None
    all_months = (
        sorted(monthly_results["month"].dropna().astype(str).unique().tolist())
        if not monthly_results.empty and "month" in monthly_results.columns
        else []
    )
    latest_selected_month = all_months[-2] if len(all_months) >= 2 else (all_months[-1] if all_months else None)
    if preview_available:
        latest_selected_month = latest_data_month or latest_selected_month
        realized_monthly_results = monthly_results.copy()
    else:
        realized_monthly_results = (
            monthly_results[monthly_results["month"].astype(str) != latest_data_month].copy()
            if latest_data_month is not None and len(all_months) >= 2
            else monthly_results
        )
    summary = calculate_summary(realized_monthly_results, config.backtest.initial_capital)
    current_month = latest_data_month or latest_selected_month
    current_positions = (
        preview_positions
        if preview_available and preview_positions is not None
        else (
            display_positions[display_positions["month"] == current_month]
            if current_month is not None and not display_positions.empty
            else display_positions.iloc[0:0]
        )
    )
    current_regime = _monthly_regime_lookup(monthly_regimes, current_month)
    return {
        **summary,
        "current_month": current_month,
        "latest_data_month": latest_data_month,
        "latest_selected_month": latest_selected_month,
        "metrics_through_month": latest_selected_month or latest_data_month,
        "open_month_excluded_from_metrics": False if preview_available else bool(latest_data_month is not None and len(all_months) >= 2),
        "position_count": int(len(display_positions)),
        "current_month_position_count": int(len(current_positions)),
        "unique_symbol_count": int(display_positions["symbol"].nunique()) if not display_positions.empty else 0,
        "current_regime_label": current_regime.get("regime_label"),
        "current_regime_risk": current_regime.get("regime_risk"),
        "current_regime_note": current_regime.get("regime_note"),
        "current_regime_breadth_200d": current_regime.get("breadth_200d"),
    }


def build_next_month_preview(
    *,
    config: BacktestConfig,
    prices: pd.DataFrame | None,
    financial_snapshots: pd.DataFrame | None,
    membership: pd.DataFrame | None,
    planned_positions: pd.DataFrame,
) -> dict[str, object]:
    empty_positions = pd.DataFrame()
    empty_missing = pd.DataFrame(
        columns=["month", "symbol", "score", "selection_score", "provisional_rank", "missing_fields", "rejection_reason"]
    )
    empty_regime = pd.DataFrame(
        columns=["month", "buy_date", "breadth_200d", "regime_key", "regime_label", "regime_risk", "regime_note"]
    )
    if (
        prices is None
        or financial_snapshots is None
        or membership is None
        or prices.empty
        or financial_snapshots.empty
        or membership.empty
    ):
        return {"positions": empty_positions, "missing_financials": empty_missing, "preview_month": None, "basis_date": None, "regime": empty_regime}

    price_dates = pd.to_datetime(prices["date"], errors="coerce").dropna()
    if price_dates.empty:
        return {"positions": empty_positions, "missing_financials": empty_missing, "preview_month": None, "basis_date": None, "regime": empty_regime}

    normalized_prices = prices.copy()
    normalized_prices["date"] = pd.to_datetime(normalized_prices["date"], errors="coerce").dt.date
    normalized_prices = normalized_prices[normalized_prices["date"].notna()].copy()
    if normalized_prices.empty:
        return {"positions": empty_positions, "missing_financials": empty_missing, "preview_month": None, "basis_date": None, "regime": empty_regime}

    latest_month = price_dates.dt.strftime("%Y-%m").max()
    today_local = datetime.now(ZoneInfo(config.project.timezone)).date()
    current_month = today_local.strftime("%Y-%m")
    latest_month_is_closed = latest_month < current_month
    if latest_month == current_month:
        latest_month_is_closed = today_local.day == calendar.monthrange(today_local.year, today_local.month)[1]
    if not latest_month_is_closed:
        return {"positions": empty_positions, "missing_financials": empty_missing, "preview_month": None, "basis_date": None, "regime": empty_regime}

    basis_date = get_last_trading_day(normalized_prices, latest_month)
    preview_reference_date = (basis_date.replace(day=1) + timedelta(days=32)).replace(day=1)
    preview_month = preview_reference_date.strftime("%Y-%m")
    cutoff_dt = datetime.combine(basis_date, time(23, 59), tzinfo=ZoneInfo(config.project.timezone))
    preview_rebalance_dt = datetime.combine(preview_reference_date, time(0, 0), tzinfo=ZoneInfo(config.project.timezone))

    if config.scoring.formula in {"note_exact", "note_best_fit"}:
        known = get_latest_known_annual_financials(financial_snapshots, cutoff_dt, preview_reference_date)
        if config.scoring.formula == "note_best_fit" and not known.empty:
            known = _attach_note_best_fit_growth_inputs(known, financial_snapshots, cutoff_dt, preview_reference_date)
    else:
        known = get_latest_known_financials(financial_snapshots, cutoff_dt, preview_reference_date)

    universe = get_universe_for_date(membership, config.universe.name, preview_reference_date)
    candidates = known[known["symbol"].isin(universe)].copy()
    candidates = _attach_universe_metadata(candidates, membership, config.universe.name, preview_reference_date)
    if candidates.empty:
        return {
            "positions": empty_positions,
            "missing_financials": empty_missing,
            "preview_month": preview_month,
            "basis_date": basis_date.isoformat(),
            "regime": _build_preview_regime(config, normalized_prices, membership, preview_month, preview_reference_date),
        }

    candidates = attach_avg_turnover_20d(candidates, normalized_prices, preview_reference_date)
    candidates = attach_recent_return_20d(candidates, normalized_prices, preview_reference_date)
    candidates = attach_recent_return_60d(candidates, normalized_prices, preview_reference_date)
    candidates = attach_market_cap_firm_value(candidates, normalized_prices, preview_rebalance_dt)
    candidates = calculate_scores(candidates, config.scoring)
    candidates = _apply_x1_soft_penalty_rule(candidates, config)

    effective_top_n = _resolve_effective_top_n(config, normalized_prices, universe, preview_reference_date)
    ranked_all = candidates.sort_values(["selection_score", "score"], ascending=False).reset_index(drop=True)
    ranked_all["month"] = preview_month
    ranked_all["provisional_rank"] = ranked_all.index + 1
    ranked_all["effective_top_n"] = effective_top_n

    filter_settings = FilterSettings(**config.filters.model_dump())
    filtered, rejected = apply_filters(candidates, filter_settings)
    rejected["month"] = preview_month
    rejected = rejected.merge(
        ranked_all[["month", "symbol", "selection_score", "score", "provisional_rank", "effective_top_n"]],
        on=["month", "symbol", "selection_score", "score"],
        how="left",
    )
    missing_financials = build_missing_financials(rejected)

    ranked = filtered.sort_values(["selection_score", "score"], ascending=False)
    previous_symbols = set()
    if not planned_positions.empty and "month" in planned_positions.columns:
        latest_planned_month = str(planned_positions["month"].dropna().astype(str).max())
        previous_symbols = set(
            planned_positions[planned_positions["month"].astype(str) == latest_planned_month]["symbol"].astype(str).tolist()
        )
    selected = _apply_hold_buffer_rule(
        ranked,
        previous_symbols,
        effective_top_n,
        config.strategy.hold_buffer_rank,
    )
    positions = build_positions(
        selected,
        weighting=config.strategy.weighting,
        score_weight_cap=config.strategy.score_weight_cap,
    )
    positions = _apply_technical_confirmation_rule(positions, config)
    positions = _apply_position_quality_guard_rule(positions, config)

    preview_regime = _build_preview_regime(config, normalized_prices, membership, preview_month, preview_reference_date)
    if positions.empty:
        return {
            "positions": empty_positions,
            "missing_financials": missing_financials,
            "preview_month": preview_month,
            "basis_date": basis_date.isoformat(),
            "regime": preview_regime,
        }

    positions = positions.copy()
    positions["month"] = preview_month
    positions["buy_date"] = None
    positions["sell_date"] = None
    positions["used_period_end"] = positions["period_end"]
    positions["used_announcement_date"] = pd.to_datetime(
        positions.get("announcement_datetime"), errors="coerce"
    ).dt.strftime("%Y-%m-%d")
    if "announcement_date" in positions.columns:
        fallback_dates = pd.to_datetime(positions["announcement_date"], errors="coerce").dt.strftime("%Y-%m-%d")
        positions["used_announcement_date"] = positions["used_announcement_date"].fillna(fallback_dates)
    positions["position_status"] = "preview"
    positions["position_status_detail"] = "Sonraki ay preview listesi (ay sonu kapanisina gore)"
    positions["gross_return"] = None
    positions["net_return"] = None
    positions["buy_price"] = None
    positions["sell_price"] = None
    positions["preview_basis_date"] = basis_date.isoformat()
    positions = _finalize_display_positions(positions)
    positions = _attach_monthly_regimes(positions, preview_regime)

    return {
        "positions": positions,
        "missing_financials": missing_financials,
        "preview_month": preview_month,
        "basis_date": basis_date.isoformat(),
        "regime": preview_regime,
    }


def _build_preview_regime(
    config: BacktestConfig,
    prices: pd.DataFrame,
    membership: pd.DataFrame,
    preview_month: str,
    preview_reference_date: date,
) -> pd.DataFrame:
    universe = get_universe_for_date(membership, config.universe.name, preview_reference_date)
    breadth = _calculate_universe_breadth_above_sma(
        prices=prices,
        symbols=universe,
        as_of_date=preview_reference_date,
        lookback_days=200,
    )
    regime = _classify_regime(breadth)
    return pd.DataFrame(
        [
            {
                "month": preview_month,
                "buy_date": preview_reference_date.isoformat(),
                "breadth_200d": breadth,
                **regime,
            }
        ]
    )


def build_display_positions(
    planned_positions: pd.DataFrame,
    realized_positions: pd.DataFrame,
    rejected_candidates: pd.DataFrame,
    latest_data_month: str | None,
) -> pd.DataFrame:
    realized = realized_positions.copy()
    if not realized.empty:
        realized["position_status"] = "realized"
        realized["position_status_detail"] = "Gerceklesti"

    if planned_positions.empty:
        return realized
    if realized.empty:
        display = planned_positions.copy()
        if latest_data_month is not None:
            display["position_status"] = display["month"].map(
                lambda month: "open" if str(month) == latest_data_month else "carried_forward"
            )
            display["position_status_detail"] = display["position_status"].map(
                {
                    "open": "Acik pozisyon, henuz realize olmadi",
                    "carried_forward": "Satis fiyati eksik, bir sonraki aya sarkti",
                }
            )
        return _finalize_display_positions(display)

    latest_planned_month = str(planned_positions["month"].dropna().astype(str).max())
    latest_realized_month = (
        str(realized["month"].dropna().astype(str).max())
        if not realized.empty and "month" in realized.columns
        else None
    )
    historical = realized[
        realized["month"].astype(str) != latest_data_month
    ].copy() if latest_data_month is not None else realized.copy()
    current = planned_positions[planned_positions["month"].astype(str) == latest_planned_month].copy()
    if not current.empty:
        current["position_status"] = "open"
        if latest_realized_month is not None and latest_data_month == latest_realized_month == latest_planned_month:
            current["position_status_detail"] = "Acik ay, dashboardda realize edilmez"
        else:
            current["position_status_detail"] = "Acik pozisyon, henuz realize olmadi"
    carry_rows = planned_positions.iloc[0:0].copy()
    missing_price = rejected_candidates[
        (rejected_candidates.get("reason") == "missing_price")
        if "reason" in rejected_candidates.columns
        else pd.Series(False, index=rejected_candidates.index)
    ].copy()
    if not missing_price.empty:
        carry_rows = planned_positions.merge(
            missing_price[["month", "symbol", "reason"]].drop_duplicates(),
            on=["month", "symbol"],
            how="inner",
        )
        if not carry_rows.empty:
            carry_rows["position_status"] = "carried_forward"
            carry_rows["position_status_detail"] = "Satis fiyati eksik, bir sonraki aya sarkti"
    display = pd.concat([historical, current], ignore_index=True, sort=False)
    if not carry_rows.empty:
        existing_pairs = set(zip(display["month"].astype(str), display["symbol"].astype(str), strict=False))
        carry_rows = carry_rows[
            carry_rows.apply(
                lambda row: (str(row["month"]), str(row["symbol"])) not in existing_pairs,
                axis=1,
            )
        ].copy()
        display = pd.concat([display, carry_rows], ignore_index=True, sort=False)
    display = display.sort_values(["month", "symbol"]).reset_index(drop=True)
    return _finalize_display_positions(display)


def _finalize_display_positions(display: pd.DataFrame) -> pd.DataFrame:
    if "fiscal_year" in display.columns and "fiscal_quarter" in display.columns:
        fiscal_year = pd.to_numeric(display["fiscal_year"], errors="coerce")
        fiscal_quarter = pd.to_numeric(display["fiscal_quarter"], errors="coerce")
        display["used_period_label"] = [
            f"{int(year)}/Q{int(quarter)}" if pd.notna(year) and pd.notna(quarter) else None
            for year, quarter in zip(fiscal_year, fiscal_quarter, strict=False)
        ]
    elif "used_period_end" in display.columns:
        used_period_end = pd.to_datetime(display["used_period_end"], errors="coerce")
        display["used_period_label"] = [
            f"{value.year}/Q{((value.month - 1) // 3) + 1}" if pd.notna(value) else None
            for value in used_period_end
        ]
    if "used_announcement_date" not in display.columns and "announcement_date" in display.columns:
        display["used_announcement_date"] = display["announcement_date"]
    elif "announcement_date" in display.columns:
        display["used_announcement_date"] = display["used_announcement_date"].fillna(display["announcement_date"])
    if "confidence_level" not in display.columns:
        display["confidence_level"] = "neutral"
    else:
        display["confidence_level"] = display["confidence_level"].fillna("neutral")
    if "position_status" not in display.columns:
        display["position_status"] = "realized"
    if "position_status_detail" not in display.columns:
        display["position_status_detail"] = "Gerceklesti"
    for column in ("repeat_count", "avg_net_return", "win_rate"):
        if column not in display.columns:
            display[column] = None
    display = _annotate_financial_base_freshness(display)
    return display


def _annotate_financial_base_freshness(display: pd.DataFrame) -> pd.DataFrame:
    if display.empty:
        return display
    result = display.copy()
    fiscal_year = pd.to_numeric(result.get("fiscal_year"), errors="coerce")
    fiscal_quarter = pd.to_numeric(result.get("fiscal_quarter"), errors="coerce")
    if fiscal_year.isna().all() or fiscal_quarter.isna().all():
        used_period_end = pd.to_datetime(result.get("used_period_end"), errors="coerce")
        fiscal_year = used_period_end.dt.year
        fiscal_quarter = ((used_period_end.dt.month - 1) // 3) + 1

    buy_dt = pd.to_datetime(result.get("buy_date"), errors="coerce")
    buy_year = buy_dt.dt.year
    buy_quarter = ((buy_dt.dt.month - 1) // 3) + 1
    lag = ((buy_year - fiscal_year) * 4) + (buy_quarter - fiscal_quarter)
    result["financial_base_quarter_lag"] = lag.where(pd.notna(lag), None)
    result["stale_financial_base"] = lag.ge(5).fillna(False)
    result["financial_base_warning"] = result["stale_financial_base"].map(
        lambda is_stale: "Annual baz eski" if is_stale else None
    )
    return result


def build_symbol_confidence(selected_positions: pd.DataFrame) -> pd.DataFrame:
    if selected_positions.empty:
        return pd.DataFrame(
            columns=["symbol", "repeat_count", "avg_net_return", "win_rate", "confidence_level"]
        )
    grouped = (
        selected_positions.groupby("symbol", dropna=False)
        .agg(
            repeat_count=("symbol", "count"),
            avg_net_return=("net_return", "mean"),
            win_rate=("net_return", lambda s: float((pd.to_numeric(s, errors="coerce") > 0).mean())),
        )
        .reset_index()
    )
    grouped["confidence_level"] = grouped.apply(_classify_confidence, axis=1)
    return grouped


def build_missing_financials(rejected_candidates: pd.DataFrame) -> pd.DataFrame:
    if rejected_candidates.empty:
        return pd.DataFrame(
            columns=["month", "symbol", "score", "selection_score", "provisional_rank", "missing_fields", "rejection_reason"]
        )
    rows: list[dict[str, object]] = []
    for _, row in rejected_candidates.iterrows():
        missing_fields = missing_financial_fields(row)
        if not missing_fields:
            continue
        rows.append(
            {
                "month": row.get("month"),
                "symbol": row.get("symbol"),
                "score": row.get("score"),
                "selection_score": row.get("selection_score"),
                "provisional_rank": row.get("provisional_rank"),
                "effective_top_n": row.get("effective_top_n"),
                "missing_fields": missing_fields,
                "rejection_reason": row.get("reason"),
                "announcement_date_missing": "announcement_date" in missing_fields,
            }
        )
    return pd.DataFrame(rows)


def build_current_month_alerts(missing_financials: pd.DataFrame, target_month: str | None) -> pd.DataFrame:
    if missing_financials.empty:
        return missing_financials.copy()
    current_month = target_month or str(missing_financials["month"].dropna().astype(str).max())
    alerts = missing_financials[missing_financials["month"].astype(str) == current_month].copy()
    if alerts.empty:
        return alerts
    top_n_mask = alerts["provisional_rank"].notna() & alerts["effective_top_n"].notna()
    alerts = alerts[top_n_mask & (alerts["provisional_rank"] <= alerts["effective_top_n"])].copy()
    return alerts.sort_values(["provisional_rank", "symbol"]).reset_index(drop=True)


def build_stale_financial_base_alerts(display_positions: pd.DataFrame, target_month: str | None) -> pd.DataFrame:
    if display_positions.empty or "stale_financial_base" not in display_positions.columns:
        return pd.DataFrame(
            columns=[
                "month",
                "symbol",
                "used_period_label",
                "buy_date",
                "financial_base_quarter_lag",
                "financial_base_warning",
            ]
        )
    current_month = target_month or str(display_positions["month"].dropna().astype(str).max())
    alerts = display_positions[
        (display_positions["month"].astype(str) == current_month)
        & (display_positions["stale_financial_base"] == True)
    ].copy()
    if alerts.empty:
        return alerts
    columns = [
        "month",
        "symbol",
        "used_period_label",
        "buy_date",
        "financial_base_quarter_lag",
        "financial_base_warning",
    ]
    existing = [column for column in columns if column in alerts.columns]
    return alerts[existing].sort_values(["financial_base_quarter_lag", "symbol"], ascending=[False, True]).reset_index(drop=True)


def build_monthly_regimes(
    config: BacktestConfig,
    monthly_results: pd.DataFrame,
    prices: pd.DataFrame | None,
    membership: pd.DataFrame | None,
) -> pd.DataFrame:
    columns = [
        "month",
        "buy_date",
        "breadth_200d",
        "regime_key",
        "regime_label",
        "regime_risk",
        "regime_note",
    ]
    if (
        monthly_results.empty
        or prices is None
        or membership is None
        or prices.empty
        or membership.empty
        or "buy_date" not in monthly_results.columns
    ):
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, object]] = []
    for row in monthly_results.to_dict("records"):
        buy_date = _coerce_date(row.get("buy_date"))
        buy_timestamp = pd.to_datetime(row.get("buy_date"), errors="coerce")
        month = row.get("month")
        if buy_date is None or month is None or pd.isna(buy_timestamp):
            continue
        universe = get_universe_for_date(membership, config.universe.name, buy_date)
        breadth = _calculate_universe_breadth_above_sma(
            prices=prices,
            symbols=universe,
            as_of_date=buy_timestamp,
            lookback_days=200,
        )
        regime = _classify_regime(breadth)
        rows.append(
            {
                "month": str(month),
                "buy_date": buy_date.isoformat(),
                "breadth_200d": breadth,
                **regime,
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _attach_monthly_regimes(display_positions: pd.DataFrame, monthly_regimes: pd.DataFrame) -> pd.DataFrame:
    if display_positions.empty or monthly_regimes.empty:
        return display_positions
    available = [
        column
        for column in [
            "month",
            "breadth_200d",
            "regime_key",
            "regime_label",
            "regime_risk",
            "regime_note",
        ]
        if column in monthly_regimes.columns
    ]
    if "month" not in available:
        return display_positions
    return display_positions.merge(monthly_regimes[available].drop_duplicates(subset=["month"]), on="month", how="left")


def _monthly_regime_lookup(monthly_regimes: pd.DataFrame, month: str | None) -> dict[str, object]:
    if monthly_regimes.empty or month is None or "month" not in monthly_regimes.columns:
        return {}
    matches = monthly_regimes[monthly_regimes["month"].astype(str) == str(month)]
    if matches.empty:
        return {}
    return matches.iloc[0].to_dict()


def _coerce_date(value: object) -> date | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def _classify_regime(breadth: float | None) -> dict[str, str | None]:
    if breadth is None:
        return {
            "regime_key": "unknown",
            "regime_label": "Rejim bilinmiyor",
            "regime_risk": "unknown",
            "regime_note": "Yeterli fiyat gecmisi olmadigi icin breadth hesaplanamadi.",
        }
    if breadth < 0.25:
        return {
            "regime_key": "riskli",
            "regime_label": "Riskli Rejim",
            "regime_risk": "high",
            "regime_note": "Genis satis riski yuksek, piyasa breadth'i zayif.",
        }
    if breadth < 0.40:
        return {
            "regime_key": "karisik",
            "regime_label": "Karisik Rejim",
            "regime_risk": "medium",
            "regime_note": "Piyasa destegi zayif, secicilik onemli.",
        }
    return {
        "regime_key": "destekleyici",
        "regime_label": "Destekleyici Rejim",
        "regime_risk": "low",
        "regime_note": "Breadth saglikli, piyasa destegi gorece guclu.",
    }


def _attach_provisional_rank(
    rejected_candidates: pd.DataFrame,
    candidate_diagnostics: pd.DataFrame,
) -> pd.DataFrame:
    if rejected_candidates.empty or candidate_diagnostics.empty:
        enriched = rejected_candidates.copy()
        if "provisional_rank" not in enriched.columns:
            enriched["provisional_rank"] = pd.Series(dtype=float)
        if "effective_top_n" not in enriched.columns:
            enriched["effective_top_n"] = pd.Series(dtype=float)
        return enriched
    merge_columns = ["month", "symbol", "selection_score", "score", "provisional_rank", "effective_top_n"]
    ranked = candidate_diagnostics[merge_columns].copy()
    enriched = rejected_candidates.merge(
        ranked,
        on=["month", "symbol", "selection_score", "score"],
        how="left",
    )
    return enriched


def _classify_confidence(row: pd.Series) -> str:
    repeat_count = int(row.get("repeat_count", 0) or 0)
    avg_net_return = float(row.get("avg_net_return", 0.0) or 0.0)
    win_rate = float(row.get("win_rate", 0.0) or 0.0)
    if repeat_count < 3:
        return "neutral"
    if avg_net_return > 0 and win_rate >= 0.60:
        return "winner"
    if avg_net_return < 0 and win_rate <= 0.40:
        return "loser"
    return "neutral"


def _normalize_dates(frame: pd.DataFrame | object) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        return pd.DataFrame()
    result = frame.copy()
    for column in result.columns:
        if "date" in column or "datetime" in column or column.endswith("_at"):
            try:
                result[column] = pd.to_datetime(result[column], errors="ignore")
            except Exception:
                continue
    return result


def _records(df: pd.DataFrame) -> list[dict[str, object]]:
    if df.empty:
        return []
    clean = df.copy()
    for column in clean.columns:
        if pd.api.types.is_datetime64_any_dtype(clean[column]):
            clean[column] = clean[column].dt.strftime("%Y-%m-%d %H:%M:%S")
        elif clean[column].dtype == object:
            clean[column] = clean[column].map(
                lambda value: value.isoformat() if hasattr(value, "isoformat") and value is not None else value
            )
    clean = clean.astype(object).where(pd.notnull(clean), None)
    return clean.to_dict(orient="records")


def empty_status(profile: DashboardProfile, message: str) -> RefreshStatus:
    return RefreshStatus(
        profile_id=profile.id,
        label=profile.label,
        config_path=str(profile.config_path),
        market_id=profile.market_id,
        market_label=profile.market_label,
        run_id=None,
        active=profile.active,
        last_refreshed_at=datetime.now(UTC).isoformat(),
        latest_data_month=None,
        refresh_status="failed",
        message=message,
    )


def active_profile_manifest() -> list[dict[str, object]]:
    return [
        {
            "id": profile.id,
            "label": profile.label,
            "config_path": str(profile.config_path),
            "market_id": profile.market_id,
            "market_label": profile.market_label,
            "active": profile.active,
        }
        for profile in active_dashboard_profiles()
    ]
