from __future__ import annotations

from pathlib import Path
from datetime import UTC, date, datetime
import hashlib
import json
import re
import unicodedata
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import typer
import uvicorn

from bist_factor_backtest.backtest.monthly_rotation import run_monthly_rotation_backtest
from bist_factor_backtest.config import load_config
from bist_factor_backtest.dashboard.app import create_app
from bist_factor_backtest.dashboard.datasets import (
    build_profile_dashboard_dataset,
    dashboard_root,
    empty_status,
    write_dashboard_manifest,
)
from bist_factor_backtest.dashboard.profiles import active_dashboard_profiles
from bist_factor_backtest.dashboard.settings import load_admin_settings
from bist_factor_backtest.data.coverage_audit import (
    build_alternative_coverage_audit,
    build_alternative_fill_queue,
    summarize_alternative_coverage,
)
from bist_factor_backtest.data.earnings_investing import InvestingEarningsLoader, merge_announcements_into_statements
from bist_factor_backtest.data.financials_fallback_registry import (
    FinancialFallbackRegistryLoader,
    load_financial_fallback_registry,
    record_to_statement_rows,
)
from bist_factor_backtest.data.issuer_ir_announcements import ISSUER_IR_SOURCES, IssuerIRAnnouncementsLoader
from bist_factor_backtest.data.financials_isyatirim import IsYatirimFinancialLoader
from bist_factor_backtest.data.investing_registry import (
    build_registry_urls,
    bootstrap_investing_registry,
    load_investing_registry,
    validate_investing_registry,
)
from bist_factor_backtest.data.mkk_esirket_announcements import MKK_ESIR_SOURCES, MkkEsirketAnnouncementsLoader
from bist_factor_backtest.data.listing_gap_audit import build_listing_gap_audit, load_listing_dates
from bist_factor_backtest.data.kap_loader import KapFinancialLoader, KapNameResolutionError
from bist_factor_backtest.data.open_price_capture_yfinance import YFinanceOpenPriceCaptureLoader
from bist_factor_backtest.data.index_announcements import fetch_reconstructed_xusin_membership
from bist_factor_backtest.data.price_loader_yfinance import YFinancePriceLoader
from bist_factor_backtest.data.queenstocks import (
    QueenStocksAnnouncementLoader,
    QueenStocksClient,
    QueenStocksFinancialLoader,
    derive_company_card_statement_probe,
)
from bist_factor_backtest.data.symbol_aliases import apply_symbol_aliases, load_symbol_aliases
from bist_factor_backtest.data.storage import DuckDbStorage
from bist_factor_backtest.data.universe import (
    build_current_static_membership,
    fetch_current_static_xusin_membership,
    load_static_universe,
    load_universe_membership,
)
from bist_factor_backtest.factors.ttm import add_ttm_values
from bist_factor_backtest.reports.excel_export import export_excel_report

app = typer.Typer()


@app.command()
def init_data() -> None:
    Path("data/universe").mkdir(parents=True, exist_ok=True)
    symbols = Path("data/universe/bist_sanayi_symbols.csv")
    membership = Path("data/universe/bist_sanayi_membership.csv")
    if not symbols.exists():
        symbols.write_text("symbol\n", encoding="utf-8")
    if not membership.exists():
        membership.write_text("symbol,universe_name,start_date,end_date,source_type,source_url,confidence\n", encoding="utf-8")


@app.command()
def load_prices(config: Path = Path("config.yaml")) -> None:
    settings = load_config(config)
    storage = DuckDbStorage(settings.data.duckdb_path)
    storage.initialize()
    symbols = load_static_universe(settings.universe.symbols_file, settings.universe.symbol_aliases_file)
    start_date = settings.data.price_preload_start or settings.backtest.start_date
    prices = YFinancePriceLoader().load(symbols, start_date, settings.backtest.end_date)
    storage.replace_table("market_prices", prices)
    storage.close()


@app.command()
def capture_first_open_prices(
    config: Path = Path("config.yaml"),
    trade_date: str | None = None,
    interval: str = "1m",
) -> None:
    settings = load_config(config)
    capture_date = (
        date.fromisoformat(trade_date)
        if trade_date is not None
        else datetime.now(ZoneInfo(settings.project.timezone)).date()
    )
    storage = DuckDbStorage(settings.data.duckdb_path)
    storage.initialize()
    symbols = load_static_universe(settings.universe.symbols_file, settings.universe.symbol_aliases_file)
    captures = YFinanceOpenPriceCaptureLoader().load(
        symbols,
        capture_date,
        market_open_time=settings.strategy.market_open_time,
        timezone=settings.project.timezone,
        interval=interval,
    )
    storage.connection.execute(
        "DELETE FROM market_open_captures WHERE trade_date = ? AND source = ? AND interval = ?",
        [capture_date, "yfinance_intraday", interval],
    )
    if not captures.empty:
        storage.append_table("market_open_captures", captures)
        _upsert_captured_open_prices_into_market_prices(storage, captures, capture_date)
    storage.close()
    typer.echo(
        f"captured={int((captures['source_status'] == 'captured').sum()) if not captures.empty else 0} "
        f"missing={int((captures['source_status'] != 'captured').sum()) if not captures.empty else 0} "
        f"trade_date={capture_date.isoformat()} interval={interval}"
    )


@app.command()
def load_financials_kap(
    config: Path = Path("config.yaml"),
    strict: bool = False,
    only_incomplete: bool = False,
    symbols_override: list[str] | None = None,
    max_retries: int = 5,
    backoff_seconds: float = 1.5,
    request_timeout_seconds: int = 20,
    min_request_interval_seconds: float = 1.0,
    rate_limit_sleep_seconds: float = 30.0,
    preflight_checks: int = 3,
) -> None:
    settings = load_config(config)
    symbols = symbols_override or load_static_universe(
        settings.universe.symbols_file, settings.universe.symbol_aliases_file
    )
    if only_incomplete:
        symbols = _filter_only_incomplete_symbols(symbols, settings.data.duckdb_path)
    start_date = settings.data.financial_preload_start or settings.backtest.start_date
    typer.echo(f"KAP load start: total={len(symbols)}")

    storage = DuckDbStorage(settings.data.duckdb_path)
    storage.initialize()

    loader = KapFinancialLoader(
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        request_timeout_seconds=request_timeout_seconds,
        min_request_interval_seconds=min_request_interval_seconds,
        rate_limit_sleep_seconds=rate_limit_sleep_seconds,
    )
    _run_kap_preflight(
        retries=preflight_checks,
        request_timeout_seconds=request_timeout_seconds,
    )
    completed = 0
    skipped_complete = 0
    incomplete_retried = 0
    failed = 0
    failed_symbols: list[str] = []

    for index, symbol in enumerate(symbols, start=1):
        typer.echo(f"[{index}/{len(symbols)}] loading {symbol}")
        try:
            disclosures = loader.list_disclosures(symbol, start_date, settings.backtest.end_date)
        except KapNameResolutionError as error:
            storage.close()
            raise typer.BadParameter(f"NameResolutionError on symbol={symbol}: {error}") from error
        except Exception as error:
            failed += 1
            failed_symbols.append(symbol)
            _upsert_symbol_load_status(storage, symbol, "failed", "kap_fetch_failed")
            typer.echo(
                pd.DataFrame(
                    [{"symbol": symbol, "reason": "kap_fetch_failed", "detail": str(error)}]
                ).to_string(index=False)
            )
            if strict:
                storage.close()
                raise typer.BadParameter(f"Strict mode failure on symbol={symbol}: ['kap_fetch_failed']") from error
            continue

        target_statement_ids = {
            f"{symbol.upper()}-{disclosure.get('disclosureIndex')}"
            for disclosure in disclosures
            if disclosure.get("disclosureIndex") is not None
        }
        if not target_statement_ids:
            failed += 1
            failed_symbols.append(symbol)
            _upsert_symbol_load_status(storage, symbol, "failed", "missing_financial_disclosures")
            typer.echo(
                pd.DataFrame(
                    [{"symbol": symbol, "reason": "missing_financial_disclosures", "detail": ""}]
                ).to_string(index=False)
            )
            if strict:
                storage.close()
                raise typer.BadParameter(f"Strict mode failure on symbol={symbol}: ['missing_financial_disclosures']")
            continue

        completeness = _symbol_completeness(storage, symbol, target_statement_ids)
        typer.echo(
            f"  disclosures={len(target_statement_ids)} complete={completeness['is_complete']} "
            f"missing_or_incomplete={len(completeness['missing_or_incomplete_statement_ids'])} "
            f"(missing_statement={len(completeness['missing_statement_ids'])}, "
            f"missing_items={len(completeness['incomplete_item_ids'])}, "
            f"missing_shares={len(completeness['shares_missing_ids'])})"
        )
        if completeness["is_complete"]:
            skipped_complete += 1
            _upsert_symbol_load_status(storage, symbol, "completed", "already_complete")
            continue
        incomplete_retried += 1

        disclosures_to_build = [
            disclosure
            for disclosure in disclosures
            if f"{symbol.upper()}-{disclosure.get('disclosureIndex')}" in completeness["missing_or_incomplete_statement_ids"]
        ]
        result = loader.build_from_disclosures(symbol, disclosures_to_build)

        if not result.statements.empty:
            _upsert_statements(storage, result.statements)
        if not result.items.empty:
            _replace_items_for_statements(storage, result.items)

        if not result.failures.empty:
            hard_failures = set(result.failures["reason"].tolist())
            typer.echo(result.failures.to_string(index=False))
            failed += 1
            failed_symbols.append(symbol)
            _upsert_symbol_load_status(storage, symbol, "failed", ",".join(sorted(hard_failures)))
            if strict:
                storage.close()
                raise typer.BadParameter(f"Strict mode failure on symbol={symbol}: {sorted(hard_failures)}")
            continue

        post = _symbol_completeness(storage, symbol, target_statement_ids)
        if post["is_complete"]:
            typer.echo("  status=completed_after_retry")
            completed += 1
            _upsert_symbol_load_status(storage, symbol, "completed", "completed_after_retry")
        else:
            legacy_ids = _mark_legacy_nonfinancial_if_needed(
                storage,
                symbol,
                set(post["missing_or_incomplete_statement_ids"]),
            )
            if legacy_ids:
                post = _symbol_completeness(storage, symbol, target_statement_ids)
            if post["is_complete"]:
                typer.echo(f"  status=completed_after_legacy_skip skipped_legacy={len(legacy_ids)}")
                completed += 1
                _upsert_symbol_load_status(storage, symbol, "completed", "completed_after_legacy_skip")
                continue
            missing_sample = sorted(list(post["missing_or_incomplete_statement_ids"]))[:5]
            missing_statement_sample = sorted(list(post["missing_statement_ids"]))[:3]
            missing_items_sample = sorted(list(post["incomplete_item_ids"]))[:3]
            missing_shares_sample = sorted(list(post["shares_missing_ids"]))[:3]
            typer.echo(
                f"  status=still_incomplete missing_or_incomplete={len(post['missing_or_incomplete_statement_ids'])} "
                f"sample={missing_sample} "
                f"missing_statement_sample={missing_statement_sample} "
                f"missing_items_sample={missing_items_sample} "
                f"missing_shares_sample={missing_shares_sample}"
            )
            failed += 1
            failed_symbols.append(symbol)
            _upsert_symbol_load_status(storage, symbol, "incomplete", "still_incomplete")
            if strict:
                storage.close()
                raise typer.BadParameter(f"Strict mode incomplete symbol={symbol}")

    typer.echo(
        "KAP load finished: "
        f"completed={completed} "
        f"skipped_complete={skipped_complete} "
        f"incomplete_retried={incomplete_retried} "
        f"failed={failed}"
    )
    if failed_symbols:
        typer.echo(f"Failed symbols: {', '.join(failed_symbols)}")
    if strict and failed > 0:
        storage.close()
        raise typer.BadParameter("Strict mode detected incomplete/failed symbols")
    storage.close()


@app.command()
def load_financials_isyatirim(
    source_file: Path,
    config: Path = Path("config.yaml"),
) -> None:
    settings = load_config(config)
    records = _read_records_file(source_file)
    if "symbol" not in records.columns:
        raise typer.BadParameter("source_file must include a symbol column")
    storage = DuckDbStorage(settings.data.duckdb_path)
    storage.initialize()
    loader = IsYatirimFinancialLoader()
    failures: list[pd.DataFrame] = []
    for symbol, group in records.groupby(records["symbol"].astype(str).str.upper()):
        result = loader.build_from_records(symbol, group.to_dict(orient="records"))
        if not result.statements.empty:
            _upsert_statements(storage, result.statements)
        if not result.items.empty:
            _replace_items_for_statements(storage, result.items)
        if not result.failures.empty:
            failures.append(result.failures)
            _upsert_symbol_load_status(storage, symbol, "incomplete", "isyatirim_missing_records")
        else:
            status, reason = _derive_isyatirim_symbol_status(result.statements)
            _upsert_symbol_load_status(storage, symbol, status, reason)
    if failures:
        typer.echo(pd.concat(failures, ignore_index=True).to_string(index=False))
    storage.close()


@app.command()
def load_financials_isyatirim_live(
    config: Path = Path("config.yaml"),
    max_symbols: int | None = None,
    request_timeout_seconds: int = 20,
) -> None:
    settings = load_config(config)
    symbols = load_static_universe(settings.universe.symbols_file, settings.universe.symbol_aliases_file)
    if max_symbols is not None:
        symbols = symbols[:max_symbols]
    storage = DuckDbStorage(settings.data.duckdb_path)
    storage.initialize()
    loader = IsYatirimFinancialLoader(request_timeout_seconds=request_timeout_seconds)
    failures: list[pd.DataFrame] = []
    for index, symbol in enumerate(symbols, start=1):
        typer.echo(f"[{index}/{len(symbols)}] fetching İş Yatırım financials for {symbol}")
        try:
            records = loader.fetch_records(symbol)
            result = loader.build_from_records(symbol, records)
        except Exception as error:
            _upsert_symbol_load_status(storage, symbol, "failed", "isyatirim_fetch_failed")
            failures.append(pd.DataFrame([{"symbol": symbol, "reason": "isyatirim_fetch_failed", "detail": str(error)}]))
            continue
        if not result.statements.empty:
            _upsert_statements(storage, result.statements)
        if not result.items.empty:
            _replace_items_for_statements(storage, result.items)
        if not result.failures.empty:
            failures.append(result.failures)
            _upsert_symbol_load_status(storage, symbol, "incomplete", "isyatirim_missing_records")
        else:
            status, reason = _derive_isyatirim_symbol_status(result.statements)
            _upsert_symbol_load_status(storage, symbol, status, reason)
    if failures:
        typer.echo(pd.concat(failures, ignore_index=True).to_string(index=False))
    storage.close()


@app.command()
def load_financials_queenstocks_live(
    config: Path = Path("config.yaml"),
    symbols: str | None = None,
    max_symbols: int | None = None,
    start_index: int = 0,
    batch_size: int | None = None,
) -> None:
    settings = load_config(config)
    target_symbols = _resolve_queenstocks_target_symbols(
        settings,
        symbols=symbols,
        max_symbols=max_symbols,
        start_index=start_index,
        batch_size=batch_size,
    )
    storage = DuckDbStorage(settings.data.duckdb_path)
    storage.initialize()
    client = _build_queenstocks_client(settings)
    loader = QueenStocksFinancialLoader(client, timezone=settings.project.timezone)
    failures: list[pd.DataFrame] = []
    for index, symbol in enumerate(target_symbols, start=1):
        typer.echo(f"[{index}/{len(target_symbols)}] fetching QueenStocks financials for {symbol}")
        try:
            records = loader.fetch_records(symbol)
            result = loader.build_from_records(symbol, records)
        except Exception as error:
            _upsert_symbol_load_status(storage, symbol, "failed", "queenstocks_fetch_failed")
            failures.append(
                pd.DataFrame([{"symbol": symbol, "reason": "queenstocks_fetch_failed", "detail": str(error)}])
            )
            continue
        if not result.statements.empty:
            if "shares_outstanding" in result.statements.columns:
                missing_shares = result.statements["shares_outstanding"].isna()
                if missing_shares.any():
                    replacement = result.statements.loc[
                        missing_shares, "symbol"
                    ].map(lambda ticker: _latest_known_shares_outstanding(storage, str(ticker)))
                    replacement = replacement[replacement.notna()].astype(float)
                    if not replacement.empty:
                        result.statements.loc[replacement.index, "shares_outstanding"] = replacement
            _upsert_statements(storage, result.statements)
        if not result.items.empty:
            _replace_items_for_statements(storage, result.items)
        if not result.failures.empty:
            failures.append(result.failures)
            _upsert_symbol_load_status(storage, symbol, "incomplete", "queenstocks_missing_records")
        elif result.statements.empty:
            _upsert_symbol_load_status(storage, symbol, "incomplete", "queenstocks_no_financial_reports")
        else:
            _upsert_symbol_load_status(storage, symbol, "completed", "queenstocks_loaded")
    if failures:
        typer.echo(pd.concat(failures, ignore_index=True).to_string(index=False))
    storage.close()


@app.command()
def load_financials_fallback_registry(
    config: Path = Path("config.yaml"),
    registry_file: Path = Path("data/universe/financial_fallback_registry.csv"),
    only_stale: bool = True,
    symbols: list[str] | None = None,
    request_timeout_seconds: int = 25,
) -> None:
    settings = load_config(config)
    if not registry_file.exists():
        typer.echo(f"fallback registry not found: {registry_file}")
        return

    entries = [entry for entry in load_financial_fallback_registry(str(registry_file)) if entry.is_active]
    if symbols:
        target_symbols = {symbol.upper() for symbol in symbols}
        entries = [entry for entry in entries if entry.symbol in target_symbols]
    if only_stale:
        stale_symbols = set(
            _filter_symbols_by_latest_status(
                sorted({entry.symbol for entry in entries}),
                settings.data.duckdb_path,
                include_statuses={"stale"},
            )
        )
        entries = [entry for entry in entries if entry.symbol in stale_symbols]

    storage = DuckDbStorage(settings.data.duckdb_path)
    storage.initialize()
    loader = FinancialFallbackRegistryLoader(request_timeout_seconds=request_timeout_seconds)
    failures: list[dict] = []
    for index, entry in enumerate(entries, start=1):
        typer.echo(f"[{index}/{len(entries)}] loading fallback financials for {entry.symbol} {entry.period_end}")
        try:
            record = loader.build_record(entry)
            if record.get("shares_outstanding") is None:
                record["shares_outstanding"] = _latest_known_shares_outstanding(storage, entry.symbol)
                if record.get("shares_outstanding") is None:
                    raise ValueError("shares_outstanding_missing_after_fallback_parse")
            statements, items = record_to_statement_rows(record)
            _upsert_statements(storage, statements)
            _replace_items_for_statements(storage, items)
            _upsert_symbol_load_status(storage, entry.symbol, "completed", "fallback_registry_loaded")
        except Exception as error:
            failures.append(
                {
                    "symbol": entry.symbol,
                    "period_end": entry.period_end.isoformat(),
                    "reason": "fallback_registry_failed",
                    "detail": str(error),
                }
            )
    storage.close()
    if failures:
        typer.echo(pd.DataFrame(failures).to_string(index=False))


@app.command()
def refresh_isyatirim_load_status(
    config: Path = Path("config.yaml"),
) -> None:
    settings = load_config(config)
    storage = DuckDbStorage(settings.data.duckdb_path)
    storage.initialize()
    statements = storage.read_table("financial_statements")
    if statements.empty:
        storage.close()
        raise typer.BadParameter("financial_statements is empty; load statement data first")

    normalized = statements.copy()
    normalized["symbol"] = normalized["symbol"].astype(str).str.upper()
    source_url = normalized.get("source_url", pd.Series(index=normalized.index, dtype="object")).astype(str)
    statement_id = normalized.get("statement_id", pd.Series(index=normalized.index, dtype="object")).astype(str)
    isyatirim_rows = normalized[
        source_url.str.contains("isyatirim|Data\\.aspx/MaliTablo", case=False, regex=True, na=False)
        | statement_id.str.startswith("ISYATIRIM-", na=False)
    ].copy()
    if isyatirim_rows.empty:
        storage.close()
        typer.echo("No İş Yatırım statements found")
        return

    updated = 0
    for symbol, group in isyatirim_rows.groupby("symbol"):
        status, reason = _derive_isyatirim_symbol_status(group)
        _upsert_symbol_load_status(storage, symbol, status, reason)
        updated += 1

    storage.close()
    typer.echo(f"updated_isyatirim_symbol_statuses={updated}")


@app.command()
def cleanup_invalid_kap_periods(
    config: Path = Path("config.yaml"),
) -> None:
    settings = load_config(config)
    storage = DuckDbStorage(settings.data.duckdb_path)
    storage.initialize()
    invalid_ids = storage.connection.execute(
        """
        select statement_id
        from financial_statements
        where source_url like 'https://www.kap.org.tr/tr/Bildirim/%'
          and announcement_date is not null
          and period_end is not null
          and period_end > announcement_date
        """
    ).df()
    if invalid_ids.empty:
        storage.close()
        typer.echo("invalid_kap_statement_ids=0")
        return

    ids = invalid_ids["statement_id"].astype(str).tolist()
    placeholders = ", ".join(["?"] * len(ids))
    storage.connection.execute(
        f"DELETE FROM financial_statement_items WHERE statement_id IN ({placeholders})",
        ids,
    )
    storage.connection.execute(
        f"DELETE FROM financial_statements WHERE statement_id IN ({placeholders})",
        ids,
    )
    storage.close()
    typer.echo(f"invalid_kap_statement_ids={len(ids)}")


@app.command()
def load_announcement_dates_investing(
    source_file: Path,
    config: Path = Path("config.yaml"),
) -> None:
    settings = load_config(config)
    records = _read_records_file(source_file)
    if "symbol" not in records.columns:
        raise typer.BadParameter("source_file must include a symbol column")
    storage = DuckDbStorage(settings.data.duckdb_path)
    storage.initialize()
    statements = storage.read_table("financial_statements")
    if statements.empty:
        storage.close()
        raise typer.BadParameter("financial_statements is empty; load statement data first")
    loader = InvestingEarningsLoader()
    failures: list[pd.DataFrame] = []
    for symbol, group in records.groupby(records["symbol"].astype(str).str.upper()):
        result = loader.build_from_records(symbol, group.to_dict(orient="records"))
        if not result.announcements.empty:
            statements = merge_announcements_into_statements(
                statements,
                result.announcements,
                overwrite_existing=False,
            )
            changed = statements[
                (statements["symbol"].astype(str).str.upper() == symbol)
                & statements["announcement_date"].notna()
            ].copy()
            if not changed.empty:
                _upsert_statements(storage, changed)
        if not result.failures.empty:
            failures.append(result.failures)
    if failures:
        typer.echo(pd.concat(failures, ignore_index=True).to_string(index=False))
    storage.close()


@app.command()
def load_announcement_dates_investing_live(
    source_file: Path,
    config: Path = Path("config.yaml"),
    max_symbols: int | None = None,
    request_timeout_seconds: int = 20,
    min_request_interval_seconds: float = 0.2,
    only_missing: bool = True,
) -> None:
    settings = load_config(config)
    url_records = build_registry_urls(load_investing_registry(source_file, settings.universe.symbol_aliases_file))
    issues = validate_investing_registry(url_records)
    if issues:
        raise typer.BadParameter(f"invalid investing registry: {issues[0]}")
    if max_symbols is not None:
        url_records = url_records.head(max_symbols)
    storage = DuckDbStorage(settings.data.duckdb_path)
    storage.initialize()
    statements = storage.read_table("financial_statements")
    if statements.empty:
        storage.close()
        raise typer.BadParameter("financial_statements is empty; load statement data first")
    if only_missing:
        missing_symbols = set(
            statements[statements["announcement_date"].isna()]["symbol"].astype(str).str.upper().tolist()
        )
        url_records = url_records[url_records["symbol"].astype(str).str.upper().isin(missing_symbols)].reset_index(drop=True)
    loader = InvestingEarningsLoader(
        request_timeout_seconds=request_timeout_seconds,
        min_request_interval_seconds=min_request_interval_seconds,
    )
    failures: list[pd.DataFrame] = []
    for index, row in enumerate(url_records.to_dict(orient="records"), start=1):
        symbol = str(row["symbol"]).upper()
        earnings_url = _build_investing_earnings_url(row)
        typer.echo(f"[{index}/{len(url_records)}] fetching Investing earnings dates for {symbol}")
        try:
            records = loader.fetch_records(symbol, earnings_url)
            result = loader.build_from_records(symbol, records)
        except Exception as error:
            failures.append(pd.DataFrame([{"symbol": symbol, "reason": "investing_fetch_failed", "detail": str(error)}]))
            continue
        if not result.announcements.empty:
            statements = merge_announcements_into_statements(
                statements,
                result.announcements,
                overwrite_existing=False,
            )
            changed = statements[
                (statements["symbol"].astype(str).str.upper() == symbol)
                & statements["announcement_date"].notna()
            ].copy()
            if not changed.empty:
                _upsert_statements(storage, changed)
        if not result.failures.empty:
            failures.append(result.failures)
    if failures:
        typer.echo(pd.concat(failures, ignore_index=True).to_string(index=False))
    storage.close()


@app.command()
def load_announcement_dates_queenstocks_live(
    config: Path = Path("config.yaml"),
    symbols: str | None = None,
    max_symbols: int | None = None,
    start_index: int = 0,
    batch_size: int | None = None,
) -> None:
    settings = load_config(config)
    target_symbols = _resolve_queenstocks_target_symbols(
        settings,
        symbols=symbols,
        max_symbols=max_symbols,
        start_index=start_index,
        batch_size=batch_size,
    )
    storage = DuckDbStorage(settings.data.duckdb_path)
    storage.initialize()
    statements = storage.read_table("financial_statements")
    if statements.empty:
        storage.close()
        raise typer.BadParameter("financial_statements is empty; load statement data first")
    client = _build_queenstocks_client(settings)
    loader = QueenStocksAnnouncementLoader(client, timezone=settings.project.timezone)
    normalizer = InvestingEarningsLoader()
    failures: list[pd.DataFrame] = []
    for index, symbol in enumerate(target_symbols, start=1):
        typer.echo(f"[{index}/{len(target_symbols)}] fetching QueenStocks announcement dates for {symbol}")
        try:
            records = loader.fetch_records(symbol)
            result = normalizer.build_from_records(symbol, records)
            if not result.announcements.empty:
                result.announcements["announcement_source_system"] = "queenstocks_kap_news"
        except Exception as error:
            failures.append(
                pd.DataFrame([{"symbol": symbol, "reason": "queenstocks_announcement_fetch_failed", "detail": str(error)}])
            )
            continue
        if not result.announcements.empty:
            statements = merge_announcements_into_statements(
                statements,
                result.announcements,
                overwrite_existing=False,
            )
            changed = statements[
                (statements["symbol"].astype(str).str.upper() == symbol)
                & statements["announcement_date"].notna()
            ].copy()
            if not changed.empty:
                _upsert_statements(storage, changed)
        if not result.failures.empty:
            failures.append(result.failures)
    if failures:
        typer.echo(pd.concat(failures, ignore_index=True).to_string(index=False))
    storage.close()


@app.command()
def backfill_queenstocks_shadow_batches(
    config: Path = Path("config.formula_research_momentum_queenstocks_shadow.yaml"),
    batch_size: int = 10,
    start_batch: int = 0,
    max_batches: int | None = None,
    symbols: str | None = None,
    fill_queue_file: Path = Path("reports/queenstocks_coverage_shadow/fill_queue.csv"),
    only_fill_queue: bool = True,
    audit_output_dir: Path = Path("reports/queenstocks_coverage_shadow"),
    rebuild_dashboard_after: bool = False,
    dashboard_output_dir: Path = Path("outputs/dashboard"),
) -> None:
    if batch_size <= 0:
        raise typer.BadParameter("batch_size must be positive")
    if start_batch < 0:
        raise typer.BadParameter("start_batch must be non-negative")

    settings = load_config(config)
    target_symbols = _resolve_queenstocks_backfill_targets(
        settings,
        symbols=symbols,
        fill_queue_file=fill_queue_file,
        only_fill_queue=only_fill_queue,
    )
    if not target_symbols:
        typer.echo("queenstocks_backfill no target symbols")
        return

    total_batches = (len(target_symbols) + batch_size - 1) // batch_size
    if start_batch >= total_batches:
        raise typer.BadParameter(
            f"start_batch={start_batch} is out of range for total_batches={total_batches}"
        )
    end_batch = total_batches if max_batches is None else min(total_batches, start_batch + max_batches)
    processed_symbols = 0

    for batch_number in range(start_batch, end_batch):
        batch_start = batch_number * batch_size
        batch_symbols = target_symbols[batch_start : batch_start + batch_size]
        if not batch_symbols:
            break
        processed_symbols += len(batch_symbols)
        typer.echo(
            f"[queenstocks-batch {batch_number + 1}/{total_batches}] "
            f"symbols={','.join(batch_symbols)} db={settings.data.duckdb_path}"
        )
        batch_csv = ",".join(batch_symbols)
        load_financials_queenstocks_live(config=config, symbols=batch_csv)
        load_announcement_dates_queenstocks_live(config=config, symbols=batch_csv)
        build_snapshots(config=config)

    audit_queenstocks_coverage(config=config, output_dir=audit_output_dir)
    if rebuild_dashboard_after:
        build_dashboard(output_dir=dashboard_output_dir)
    typer.echo(
        f"queenstocks_backfill completed batches={end_batch - start_batch} "
        f"processed_symbols={processed_symbols} total_target_symbols={len(target_symbols)} "
        f"audit_output_dir={audit_output_dir}"
    )


@app.command()
def load_announcement_dates_issuer_ir_fallback(
    config: Path = Path("config.yaml"),
    symbols: str | None = None,
    max_symbols: int | None = None,
    only_missing: bool = True,
    request_timeout_seconds: int = 20,
    min_request_interval_seconds: float = 0.2,
) -> None:
    settings = load_config(config)
    requested_symbols = [symbol.strip().upper() for symbol in (symbols or "").split(",") if symbol.strip()]
    target_symbols = requested_symbols or sorted(ISSUER_IR_SOURCES.keys())
    if max_symbols is not None:
        target_symbols = target_symbols[:max_symbols]
    storage = DuckDbStorage(settings.data.duckdb_path)
    storage.initialize()
    statements = storage.read_table("financial_statements")
    if statements.empty:
        storage.close()
        raise typer.BadParameter("financial_statements is empty; load statement data first")
    if only_missing:
        missing_symbols = set(
            statements[statements["announcement_date"].isna()]["symbol"].astype(str).str.upper().tolist()
        )
        target_symbols = [symbol for symbol in target_symbols if symbol in missing_symbols]
    loader = IssuerIRAnnouncementsLoader(
        request_timeout_seconds=request_timeout_seconds,
        min_request_interval_seconds=min_request_interval_seconds,
    )
    normalizer = InvestingEarningsLoader()
    failures: list[pd.DataFrame] = []
    for index, symbol in enumerate(target_symbols, start=1):
        typer.echo(f"[{index}/{len(target_symbols)}] fetching issuer IR fallback announcement dates for {symbol}")
        try:
            records = loader.fetch_records(symbol)
            result = normalizer.build_from_records(symbol, records)
            if not result.announcements.empty:
                result.announcements["announcement_source_system"] = "issuer_ir"
        except Exception as error:
            failures.append(
                pd.DataFrame([{"symbol": symbol, "reason": "issuer_ir_fetch_failed", "detail": str(error)}])
            )
            continue
        if not result.announcements.empty:
            statements = merge_announcements_into_statements(
                statements,
                result.announcements,
                overwrite_existing=False,
            )
            changed = statements[
                (statements["symbol"].astype(str).str.upper() == symbol)
                & statements["announcement_date"].notna()
            ].copy()
            if not changed.empty:
                _upsert_statements(storage, changed)
        if not result.failures.empty:
            failures.append(result.failures)
    if failures:
        typer.echo(pd.concat(failures, ignore_index=True).to_string(index=False))
    storage.close()


@app.command()
def load_announcement_dates_mkk_esirket_fallback(
    config: Path = Path("config.yaml"),
    symbols: str | None = None,
    max_symbols: int | None = None,
    only_missing: bool = True,
    request_timeout_seconds: int = 30,
) -> None:
    settings = load_config(config)
    requested_symbols = [symbol.strip().upper() for symbol in (symbols or "").split(",") if symbol.strip()]
    target_symbols = requested_symbols or sorted(MKK_ESIR_SOURCES.keys())
    if max_symbols is not None:
        target_symbols = target_symbols[:max_symbols]
    storage = DuckDbStorage(settings.data.duckdb_path)
    storage.initialize()
    statements = storage.read_table("financial_statements")
    if statements.empty:
        storage.close()
        raise typer.BadParameter("financial_statements is empty; load statement data first")
    if only_missing:
        missing_symbols = set(
            statements[statements["announcement_date"].isna()]["symbol"].astype(str).str.upper().tolist()
        )
        target_symbols = [symbol for symbol in target_symbols if symbol in missing_symbols]
    loader = MkkEsirketAnnouncementsLoader(request_timeout_seconds=request_timeout_seconds)
    normalizer = InvestingEarningsLoader()
    failures: list[pd.DataFrame] = []
    for index, symbol in enumerate(target_symbols, start=1):
        typer.echo(f"[{index}/{len(target_symbols)}] fetching MKK e-Sirket fallback announcement dates for {symbol}")
        try:
            records = loader.fetch_records(symbol)
            result = normalizer.build_from_records(symbol, records)
            if not result.announcements.empty:
                result.announcements["announcement_source_system"] = "mkk_esirket"
        except Exception as error:
            failures.append(
                pd.DataFrame([{"symbol": symbol, "reason": "mkk_esirket_fetch_failed", "detail": str(error)}])
            )
            continue
        if not result.announcements.empty:
            statements = merge_announcements_into_statements(
                statements,
                result.announcements,
                overwrite_existing=False,
            )
            changed = statements[
                (statements["symbol"].astype(str).str.upper() == symbol)
                & statements["announcement_date"].notna()
            ].copy()
            if not changed.empty:
                _upsert_statements(storage, changed)
        if not result.failures.empty:
            failures.append(result.failures)
    if failures:
        typer.echo(pd.concat(failures, ignore_index=True).to_string(index=False))
    storage.close()


@app.command()
def load_announcement_dates_fallback_registry(
    registry_file: Path = Path("data/universe/announcement_fallback_registry.csv"),
    config: Path = Path("config.yaml"),
    only_missing: bool = True,
) -> None:
    if not registry_file.exists():
        typer.echo(f"announcement fallback registry not found: {registry_file}")
        return

    settings = load_config(config)
    storage = DuckDbStorage(settings.data.duckdb_path)
    storage.initialize()
    statements = storage.read_table("financial_statements")
    if statements.empty:
        storage.close()
        raise typer.BadParameter("financial_statements is empty; load statement data first")

    registry = pd.read_csv(registry_file)
    if registry.empty:
        storage.close()
        typer.echo("announcement fallback registry is empty")
        return

    if "is_active" in registry.columns:
        registry = registry[registry["is_active"].fillna(False).astype(bool)].copy()
    registry["symbol"] = registry["symbol"].astype(str).str.upper()
    registry["period_end"] = pd.to_datetime(registry["period_end"], errors="coerce").dt.date
    registry["announcement_date"] = pd.to_datetime(registry["announcement_date"], errors="coerce").dt.date
    registry = registry[registry["symbol"].notna() & registry["period_end"].notna() & registry["announcement_date"].notna()].copy()
    if registry.empty:
        storage.close()
        typer.echo("announcement fallback registry has no usable active rows")
        return

    updates = registry.rename(columns={"source_url": "announcement_source_url"}).copy()
    updates["statement_id"] = None
    updates["announcement_datetime"] = pd.NaT
    updates["announcement_source_system"] = "announcement_fallback_registry"
    updates = updates[
        [
            "statement_id",
            "symbol",
            "period_end",
            "announcement_date",
            "announcement_datetime",
            "announcement_source_url",
            "announcement_source_system",
        ]
    ]

    before = statements.copy()
    merged = merge_announcements_into_statements(statements, updates, overwrite_existing=False)
    before_dates = pd.to_datetime(before.get("announcement_date"), errors="coerce")
    after_dates = pd.to_datetime(merged.get("announcement_date"), errors="coerce")
    changed_mask = after_dates.notna() & (before_dates.isna() | (before_dates != after_dates))
    if only_missing:
        changed_mask = changed_mask & before_dates.isna()
    changed = merged[changed_mask].copy()
    if not changed.empty:
        _upsert_statements(storage, changed)
        typer.echo(changed[["symbol", "period_end", "announcement_date"]].to_string(index=False))
    else:
        typer.echo("announcement fallback registry produced no statement updates")
    storage.close()


@app.command()
def audit_listing_gap_classification(
    config: Path = Path("config.yaml"),
    listing_dates_file: Path = Path("data/universe/bist_sanayi_listing_dates.csv"),
    output: Path = Path("reports/missing_announcement_2019_plus_listing_gap_audit.csv"),
    start_date: str = "2019-01-01",
) -> None:
    settings = load_config(config)
    audit_start_date = pd.to_datetime(start_date).date()
    storage = DuckDbStorage(settings.data.duckdb_path)
    storage.initialize()
    snapshots = storage.read_table("financial_snapshots")
    storage.close()
    if snapshots.empty:
        raise typer.BadParameter("financial_snapshots is empty; build snapshots first")
    listing_dates = load_listing_dates(listing_dates_file)
    audit = build_listing_gap_audit(
        snapshots=snapshots,
        listing_dates=listing_dates,
        audit_start_date=audit_start_date,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    audit.to_csv(output, index=False)
    typer.echo(
        f"listing_gap_rows={len(audit)} "
        f"post_listing_fetch_gap_rows={int((audit['post_listing_fetch_gap_count'] > 0).sum()) if not audit.empty else 0} "
        f"pre_listing_expected_rows={int((audit['pre_listing_expected_gap_count'] > 0).sum()) if not audit.empty else 0} "
        f"unknown_rows={int((audit['unknown_gap_count'] > 0).sum()) if not audit.empty else 0}"
    )


@app.command()
def validate_investing_registry_file(
    source_file: Path,
    config: Path = Path("config.yaml"),
) -> None:
    settings = load_config(config)
    registry = load_investing_registry(source_file, settings.universe.symbol_aliases_file)
    issues = validate_investing_registry(registry)
    if issues:
        typer.echo(pd.DataFrame([{"issue": issue} for issue in issues]).to_string(index=False))
        raise typer.BadParameter("investing registry validation failed")
    typer.echo(f"registry_ok rows={len(registry)}")


@app.command()
def bootstrap_investing_registry_file(
    config: Path = Path("config.yaml"),
    registry_file: Path = Path("data/universe/bist_sanayi_investing_registry.csv"),
) -> None:
    settings = load_config(config)
    symbols = load_static_universe(settings.universe.symbols_file, settings.universe.symbol_aliases_file)
    existing_registry = (
        load_investing_registry(registry_file, settings.universe.symbol_aliases_file)
        if registry_file.exists() and registry_file.stat().st_size > 0
        else pd.DataFrame(columns=["symbol", "investing_slug", "earnings_url", "is_active", "notes"])
    )
    registry = bootstrap_investing_registry(symbols, existing_registry)
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    registry.to_csv(registry_file, index=False)
    typer.echo(f"bootstrapped_registry rows={len(registry)} path={registry_file}")


@app.command()
def audit_alternative_coverage(
    config: Path = Path("config.yaml"),
    registry_file: Path = Path("data/universe/bist_sanayi_investing_registry.csv"),
    output: Path = Path("reports/alternative_coverage_audit.csv"),
    queue_output: Path = Path("reports/alternative_coverage_fill_queue.csv"),
    start_date: str = "2019-01-01",
) -> None:
    settings = load_config(config)
    symbols = load_static_universe(settings.universe.symbols_file, settings.universe.symbol_aliases_file)
    storage = DuckDbStorage(settings.data.duckdb_path)
    storage.initialize()
    statements = storage.read_table("financial_statements")
    storage.close()
    registry = (
        build_registry_urls(load_investing_registry(registry_file, settings.universe.symbol_aliases_file))
        if registry_file.exists()
        else pd.DataFrame(columns=["symbol", "investing_slug", "earnings_url", "is_active"])
    )
    aliases = (
        load_symbol_aliases(settings.universe.symbol_aliases_file)
        if settings.universe.symbol_aliases_file is not None and settings.universe.symbol_aliases_file.exists()
        else pd.DataFrame(columns=["canonical_symbol", "symbol"])
    )
    audit = build_alternative_coverage_audit(
        symbols=symbols,
        statements=statements,
        registry=registry,
        aliases=aliases,
        audit_start_date=pd.Timestamp(start_date).date(),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    audit.to_csv(output, index=False)
    fill_queue = build_alternative_fill_queue(audit)
    queue_output.parent.mkdir(parents=True, exist_ok=True)
    fill_queue.to_csv(queue_output, index=False)
    typer.echo(summarize_alternative_coverage(audit).to_string(index=False))
    typer.echo(f"audit_path={output}")
    typer.echo(f"fill_queue_path={queue_output}")


@app.command()
def load_financials_kap_incomplete(
    config: Path = Path("config.yaml"),
    strict: bool = False,
    max_retries: int = 5,
    backoff_seconds: float = 1.5,
    request_timeout_seconds: int = 20,
    min_request_interval_seconds: float = 1.0,
    rate_limit_sleep_seconds: float = 30.0,
    preflight_checks: int = 3,
) -> None:
    load_financials_kap(
        config=config,
        strict=strict,
        only_incomplete=True,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        request_timeout_seconds=request_timeout_seconds,
        min_request_interval_seconds=min_request_interval_seconds,
        rate_limit_sleep_seconds=rate_limit_sleep_seconds,
        preflight_checks=preflight_checks,
    )


@app.command()
def load_financials_kap_stale(
    config: Path = Path("config.yaml"),
    strict: bool = False,
    max_retries: int = 5,
    backoff_seconds: float = 1.5,
    request_timeout_seconds: int = 20,
    min_request_interval_seconds: float = 1.0,
    rate_limit_sleep_seconds: float = 30.0,
    preflight_checks: int = 3,
) -> None:
    settings = load_config(config)
    symbols = load_static_universe(settings.universe.symbols_file, settings.universe.symbol_aliases_file)
    symbols = _filter_symbols_by_latest_status(
        symbols,
        settings.data.duckdb_path,
        include_statuses={"stale"},
    )
    if not symbols:
        typer.echo("No stale symbols to refresh from KAP")
        return
    load_financials_kap(
        config=config,
        strict=strict,
        only_incomplete=False,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        request_timeout_seconds=request_timeout_seconds,
        min_request_interval_seconds=min_request_interval_seconds,
        rate_limit_sleep_seconds=rate_limit_sleep_seconds,
        preflight_checks=preflight_checks,
        symbols_override=symbols,
    )


def _filter_only_incomplete_symbols(symbols: list[str], duckdb_path: Path | str) -> list[str]:
    return _filter_symbols_by_latest_status(
        symbols,
        duckdb_path,
        exclude_statuses={"completed"},
    )


def _filter_symbols_by_latest_status(
    symbols: list[str],
    duckdb_path: Path | str,
    *,
    include_statuses: set[str] | None = None,
    exclude_statuses: set[str] | None = None,
) -> list[str]:
    storage = DuckDbStorage(duckdb_path)
    storage.initialize()
    if not _table_exists(storage, "statement_load_status"):
        storage.close()
        return symbols
    status_df = storage.connection.execute(
        """
        SELECT symbol, status, updated_at, statement_id
        FROM statement_load_status
        """
    ).df()
    storage.close()
    if status_df.empty:
        return symbols
    normalized = status_df.copy()
    normalized = normalized[normalized["statement_id"].astype(str) == "__SYMBOL__"]
    if normalized.empty:
        return symbols
    normalized["symbol"] = normalized["symbol"].astype(str).str.upper()
    normalized["updated_at"] = pd.to_datetime(normalized["updated_at"], errors="coerce")
    normalized = normalized.sort_values(["symbol", "updated_at"])
    latest_status = normalized.groupby("symbol").tail(1)
    latest_status["status"] = latest_status["status"].astype(str)
    status_map = dict(zip(latest_status["symbol"].astype(str), latest_status["status"]))
    filtered: list[str] = []
    for symbol in symbols:
        status = status_map.get(symbol.upper())
        if include_statuses is not None and status not in include_statuses:
            continue
        if exclude_statuses is not None and status in exclude_statuses:
            continue
        filtered.append(symbol)
    return filtered


def _upsert_symbol_load_status(storage: DuckDbStorage, symbol: str, status: str, reason: str) -> None:
    storage.connection.execute(
        "DELETE FROM statement_load_status WHERE symbol = ? AND statement_id = '__SYMBOL__'",
        [symbol.upper()],
    )
    storage.append_table(
        "statement_load_status",
        pd.DataFrame(
            [
                {
                    "statement_id": "__SYMBOL__",
                    "symbol": symbol.upper(),
                    "status": status,
                    "reason": reason,
                    "updated_at": datetime.now(UTC),
                }
            ]
        ),
    )


def _derive_isyatirim_symbol_status(
    statements: pd.DataFrame,
    *,
    as_of_date: date | None = None,
) -> tuple[str, str]:
    if statements.empty or "period_end" not in statements.columns:
        return ("incomplete", "isyatirim_missing_records")
    period_end = pd.to_datetime(statements["period_end"], errors="coerce").dropna()
    if period_end.empty:
        return ("incomplete", "isyatirim_missing_records")
    latest_period = period_end.max().date()
    expected_period = _expected_latest_reported_period(as_of_date or datetime.now(UTC).date())
    if latest_period < expected_period:
        return ("stale", "isyatirim_stale_source")
    return ("completed", "isyatirim_loaded")


def _expected_latest_reported_period(as_of_date: date) -> date:
    year = as_of_date.year
    month = as_of_date.month
    if month <= 3:
        return date(year - 1, 9, 1)
    if month <= 5:
        return date(year - 1, 12, 1)
    if month <= 8:
        return date(year, 3, 1)
    if month <= 11:
        return date(year, 6, 1)
    return date(year, 9, 1)


def _append_backtest_run(storage: DuckDbStorage, settings, result: dict, config_path: Path) -> None:
    config_hash = _config_hash(settings)
    storage.append_table(
        "backtest_runs",
        pd.DataFrame(
            [
                {
                    "run_id": result["run_id"],
                    "created_at": pd.to_datetime(result["created_at"]),
                    "config_hash": config_hash,
                    "start_date": settings.backtest.start_date,
                    "end_date": settings.backtest.end_date,
                    "initial_capital": settings.backtest.initial_capital,
                    "notes": str(config_path),
                }
            ]
        ),
    )


def _upsert_captured_open_prices_into_market_prices(
    storage: DuckDbStorage,
    captures: pd.DataFrame,
    trade_date: date,
) -> None:
    captured = captures[captures["source_status"] == "captured"].copy()
    if captured.empty:
        return
    current_prices = storage.read_table("market_prices")
    if not current_prices.empty:
        current_prices["date"] = pd.to_datetime(current_prices["date"]).dt.date
        captured_symbols = set(captured["symbol"].astype(str))
        current_prices = current_prices[
            ~(
                (current_prices["date"] == trade_date)
                & (current_prices["symbol"].astype(str).isin(captured_symbols))
            )
        ].copy()
    pseudo_prices = pd.DataFrame(
        {
            "symbol": captured["symbol"].astype(str),
            "date": trade_date,
            "open": pd.to_numeric(captured["open_price"], errors="coerce"),
            "high": pd.to_numeric(captured["open_price"], errors="coerce"),
            "low": pd.to_numeric(captured["open_price"], errors="coerce"),
            "close": pd.to_numeric(captured["open_price"], errors="coerce"),
            "adjusted_close": pd.to_numeric(captured["open_price"], errors="coerce"),
            "volume": 0.0,
        }
    )
    merged_prices = pd.concat([current_prices, pseudo_prices], ignore_index=True)
    storage.replace_table("market_prices", merged_prices)


def _config_hash(settings) -> str:
    return hashlib.sha256(
        json.dumps(settings.model_dump(mode="json"), sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _load_existing_dashboard_run_id(root: Path, profile_id: str) -> str | None:
    summary_path = root / profile_id / "summary.json"
    if not summary_path.exists():
        return None
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    run_id = payload.get("run_id")
    return str(run_id) if run_id else None


def _load_artifact_backtest_result(root: Path, profile_id: str) -> dict | None:
    profile_root = root / profile_id
    summary_path = profile_root / "summary.json"
    monthly_returns_path = profile_root / "monthly_returns.json"
    selected_positions_path = profile_root / "selected_positions.json"
    if not (summary_path.exists() and monthly_returns_path.exists() and selected_positions_path.exists()):
        return None
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        monthly_results = pd.DataFrame(json.loads(monthly_returns_path.read_text(encoding="utf-8")))
        selected_positions = pd.DataFrame(json.loads(selected_positions_path.read_text(encoding="utf-8")))
    except Exception:
        return None
    if monthly_results.empty or selected_positions.empty:
        return None
    created_at = pd.to_datetime(summary.get("generated_at"), errors="coerce")
    if pd.isna(created_at):
        created_at = pd.Timestamp(datetime.now(UTC))
    run_id = summary.get("run_id")
    if not run_id:
        run_id = str(monthly_results["run_id"].iloc[0]) if "run_id" in monthly_results.columns and not monthly_results.empty else None
    if not run_id:
        return None
    return {
        "run_id": str(run_id),
        "created_at": created_at.to_pydatetime(),
        "monthly_results": monthly_results,
        "selected_positions": selected_positions,
        "planned_positions": pd.DataFrame(),
        "rejected_candidates": pd.DataFrame(),
        "candidate_diagnostics": pd.DataFrame(),
        "open_month": str(summary.get("current_month")) if summary.get("open_month_excluded_from_metrics") else None,
    }


def _load_backtest_result_for_run(storage: DuckDbStorage, run_id: str) -> dict | None:
    run_meta = storage.connection.execute(
        """
        SELECT run_id, created_at
        FROM backtest_runs
        WHERE run_id = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        [run_id],
    ).df()
    monthly_results = storage.connection.execute(
        """
        SELECT *
        FROM backtest_monthly_results
        WHERE run_id = ?
        ORDER BY month
        """,
        [run_id],
    ).df()
    selected_positions = storage.connection.execute(
        """
        SELECT *
        FROM backtest_selected_positions
        WHERE run_id = ?
        ORDER BY month, symbol
        """,
        [run_id],
    ).df()
    if monthly_results.empty or selected_positions.empty:
        return None
    created_at = datetime.now(UTC)
    if not run_meta.empty and pd.notna(run_meta.loc[0, "created_at"]):
        created_at = pd.to_datetime(run_meta.loc[0, "created_at"]).to_pydatetime()
    return {
        "run_id": run_id,
        "created_at": created_at,
        "monthly_results": monthly_results,
        "selected_positions": selected_positions,
        "planned_positions": pd.DataFrame(),
        "rejected_candidates": pd.DataFrame(),
        "candidate_diagnostics": pd.DataFrame(),
        "open_month": None,
    }


def _compose_dashboard_result(
    historical_result: dict | None,
    preview_result: dict,
) -> dict:
    if historical_result is None:
        return preview_result
    composed = dict(preview_result)
    composed["run_id"] = historical_result["run_id"]
    composed["created_at"] = historical_result["created_at"]
    open_month = historical_result.get("open_month")
    if open_month is not None:
        historical_monthly = historical_result["monthly_results"].copy()
        preview_monthly = preview_result["monthly_results"].copy()
        historical_selected = historical_result["selected_positions"].copy()
        preview_selected = preview_result["selected_positions"].copy()
        historical_monthly = historical_monthly[historical_monthly["month"].astype(str) < str(open_month)].copy()
        preview_monthly = preview_monthly[preview_monthly["month"].astype(str) >= str(open_month)].copy()
        historical_selected = historical_selected[historical_selected["month"].astype(str) < str(open_month)].copy()
        preview_selected = preview_selected[preview_selected["month"].astype(str) >= str(open_month)].copy()
        composed["monthly_results"] = pd.concat([historical_monthly, preview_monthly], ignore_index=True, sort=False)
        composed["selected_positions"] = pd.concat([historical_selected, preview_selected], ignore_index=True, sort=False)
    else:
        composed["monthly_results"] = historical_result["monthly_results"]
        composed["selected_positions"] = historical_result["selected_positions"]
    return composed


def _run_kap_preflight(retries: int, request_timeout_seconds: int) -> None:
    errors = []
    url = "https://www.kap.org.tr/tr/bildirim-sorgu-sonuc?member=4028e4a140f2ed71014106890fae0138&disclosureClass=FR"
    for _ in range(max(retries, 1)):
        try:
            response = requests.get(url, timeout=request_timeout_seconds)
            response.raise_for_status()
            return
        except Exception as error:
            errors.append(str(error))
    raise typer.BadParameter(f"KAP preflight failed after {max(retries,1)} checks: {errors[-1]}")


@app.command()
def build_snapshots(config: Path = Path("config.yaml")) -> None:
    settings = load_config(config)
    storage = DuckDbStorage(settings.data.duckdb_path)
    storage.initialize()
    statements = storage.read_table("financial_statements")
    items = storage.read_table("financial_statement_items")
    aliases = (
        load_symbol_aliases(settings.universe.symbol_aliases_file)
        if settings.universe.symbol_aliases_file is not None and settings.universe.symbol_aliases_file.exists()
        else pd.DataFrame()
    )
    snapshots = _build_financial_snapshots_from_statements(statements, items, aliases, settings.data)
    snapshots = add_ttm_values(snapshots)
    storage.replace_table("financial_snapshots", snapshots)
    storage.close()


@app.command()
def audit_queenstocks_coverage(
    config: Path = Path("config.yaml"),
    output_dir: Path = Path("reports/queenstocks_coverage"),
) -> None:
    settings = load_config(config)
    storage = DuckDbStorage(settings.data.duckdb_path)
    storage.initialize()
    statements = storage.read_table("financial_statements")
    items = storage.read_table("financial_statement_items")
    storage.close()
    aliases = (
        load_symbol_aliases(settings.universe.symbol_aliases_file)
        if settings.universe.symbol_aliases_file is not None and settings.universe.symbol_aliases_file.exists()
        else pd.DataFrame()
    )
    candidates = _prepare_financial_snapshot_candidates(statements, items, aliases)
    if candidates.empty:
        raise typer.BadParameter("financial_statements is empty; load statement data first")
    candidates = candidates[candidates["period_end"].notna()].copy()
    candidates = candidates[candidates["period_end"] >= date(2019, 1, 1)].copy()
    output_dir.mkdir(parents=True, exist_ok=True)

    universe_symbols = sorted(
        set(load_static_universe(settings.universe.symbols_file, settings.universe.symbol_aliases_file))
        | set(candidates["symbol"].astype(str).str.upper().tolist())
    )
    expected_periods = candidates.groupby("symbol")["period_end"].apply(lambda values: sorted(set(values.tolist()))).to_dict()
    queen_candidates = candidates[candidates["source_system"] == "queenstocks"].copy()
    queen_periods = queen_candidates.groupby("symbol")["period_end"].apply(lambda values: sorted(set(values.tolist()))).to_dict()

    fully_covered: list[dict] = []
    partial_history: list[dict] = []
    needs_manual_mapping: list[dict] = []
    fill_queue: list[dict] = []

    for symbol in universe_symbols:
        all_periods = expected_periods.get(symbol, [])
        qs_periods = queen_periods.get(symbol, [])
        if not qs_periods:
            needs_manual_mapping.append(
                {
                    "symbol": symbol,
                    "expected_period_count": len(all_periods),
                    "queenstocks_period_count": 0,
                    "missing_periods": ",".join(period.isoformat() for period in all_periods),
                }
            )
            fill_queue.append(
                {
                    "symbol": symbol,
                    "status": "needs_manual_mapping",
                    "missing_period_count": len(all_periods),
                    "missing_periods": ",".join(period.isoformat() for period in all_periods),
                }
            )
            continue
        missing_periods = sorted(set(all_periods) - set(qs_periods))
        row = {
            "symbol": symbol,
            "expected_period_count": len(all_periods),
            "queenstocks_period_count": len(qs_periods),
            "missing_period_count": len(missing_periods),
            "missing_periods": ",".join(period.isoformat() for period in missing_periods),
        }
        if missing_periods:
            partial_history.append(row)
            fill_queue.append({**row, "status": "partial_history"})
        else:
            fully_covered.append(row)

    period_level_diff = _build_queenstocks_period_level_diff(candidates)
    statement_value_mismatch = _build_queenstocks_statement_value_mismatch(candidates)
    announcement_date_mismatch = _build_queenstocks_announcement_date_mismatch(candidates)

    pd.DataFrame(fully_covered).to_csv(output_dir / "fully_covered.csv", index=False)
    pd.DataFrame(partial_history).to_csv(output_dir / "partial_history.csv", index=False)
    pd.DataFrame(needs_manual_mapping).to_csv(output_dir / "needs_manual_mapping.csv", index=False)
    pd.DataFrame(fill_queue).to_csv(output_dir / "fill_queue.csv", index=False)
    period_level_diff.to_csv(output_dir / "period_level_diff.csv", index=False)
    statement_value_mismatch.to_csv(output_dir / "statement_value_mismatch.csv", index=False)
    announcement_date_mismatch.to_csv(output_dir / "announcement_date_mismatch.csv", index=False)

    typer.echo(
        f"queenstocks_audit fully_covered={len(fully_covered)} "
        f"partial_history={len(partial_history)} needs_manual_mapping={len(needs_manual_mapping)} "
        f"output_dir={output_dir}"
    )


@app.command()
def audit_queenstocks_rapor_tablo_feasibility(
    config: Path = Path("config.formula_research_momentum_queenstocks_shadow.yaml"),
    symbols: str | None = None,
    fill_queue_file: Path = Path("reports/queenstocks_coverage_shadow/fill_queue.csv"),
    output_dir: Path = Path("reports/queenstocks_coverage_shadow"),
) -> None:
    settings = load_config(config)
    target_symbols = _resolve_queenstocks_backfill_targets(
        settings,
        symbols=symbols,
        fill_queue_file=fill_queue_file,
        only_fill_queue=True,
    )
    if not target_symbols:
        raise typer.BadParameter("no target symbols for RaporTablo feasibility audit")

    client = _build_queenstocks_client(settings)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    failures: list[dict] = []
    for index, symbol in enumerate(target_symbols, start=1):
        typer.echo(f"[{index}/{len(target_symbols)}] probing QueenStocks company-card tables for {symbol}")
        try:
            balance_format = client.fetch_balance_format(symbol)
            if not balance_format:
                raise ValueError("missing_balance_format")
            slug_prefix = _queenstocks_balance_format_slug(balance_format)
            payloads = {
                "hisse": client.fetch_report_table(f"qps-{slug_prefix}-hisse", symbol),
                "onemligtverileri": client.fetch_report_table(f"qps-{slug_prefix}-onemligtverileri", symbol),
                "piyasacarpanlari": client.fetch_report_table(f"qps-{slug_prefix}-piyasacarpanlari", symbol),
                "yatirimharcamalari": client.fetch_report_table(f"qps-{slug_prefix}-yatirimharcamalari", symbol),
            }
            probe = derive_company_card_statement_probe(
                symbol,
                balance_format=balance_format,
                hisse_payload=payloads["hisse"],
                onemli_gt_payload=payloads["onemligtverileri"],
                piyasacarpan_payload=payloads["piyasacarpanlari"],
                yatirimharcamalari_payload=payloads["yatirimharcamalari"],
            )
            rows.append(probe)
        except Exception as error:
            failures.append(
                {
                    "symbol": symbol.upper(),
                    "reason": "rapor_tablo_probe_failed",
                    "detail": str(error),
                }
            )

    result = pd.DataFrame(rows)
    if not result.empty:
        result["missing_fields"] = result.apply(_queenstocks_probe_missing_fields, axis=1)
    result.to_csv(output_dir / "rapor_tablo_feasibility.csv", index=False)
    pd.DataFrame(failures).to_csv(output_dir / "rapor_tablo_feasibility_failures.csv", index=False)
    summary = (
        result.groupby("can_derive_required_fields", dropna=False)
        .size()
        .reset_index(name="count")
        if not result.empty
        else pd.DataFrame(columns=["can_derive_required_fields", "count"])
    )
    summary.to_csv(output_dir / "rapor_tablo_feasibility_summary.csv", index=False)
    typer.echo(
        f"queenstocks_rapor_tablo_feasibility "
        f"targets={len(target_symbols)} derived_all={int(result['can_derive_required_fields'].sum()) if not result.empty else 0} "
        f"failures={len(failures)} output_dir={output_dir}"
    )


@app.command()
def run(config: Path = Path("config.yaml")) -> None:
    settings = load_config(config)
    storage = DuckDbStorage(settings.data.duckdb_path)
    storage.initialize()
    prices = storage.read_table("market_prices")
    financials = storage.read_table("financial_snapshots")
    membership = _load_membership_for_run(settings)
    result = run_monthly_rotation_backtest(settings, prices, financials, membership)
    _append_backtest_run(storage, settings, result, config)
    storage.append_table("backtest_monthly_results", result["monthly_results"])
    if not result["selected_positions"].empty:
        storage.append_table("backtest_selected_positions", result["selected_positions"])
    typer.echo(result["run_id"])
    storage.close()


@app.command()
def build_dashboard(
    output_dir: Path = Path("outputs/dashboard"),
) -> None:
    statuses = []
    root = dashboard_root(output_dir)
    for profile in active_dashboard_profiles():
        try:
            settings = load_config(profile.config_path)
            storage = DuckDbStorage(settings.data.duckdb_path)
            storage.initialize()
            prices = storage.read_table("market_prices")
            financials = storage.read_table("financial_snapshots")
            membership = _load_membership_for_run(settings)
            existing_run_id = _load_existing_dashboard_run_id(root, profile.id)
            historical_result = (
                _load_backtest_result_for_run(storage, existing_run_id)
                if existing_run_id is not None
                else None
            )
            if historical_result is None:
                historical_result = _load_artifact_backtest_result(root, profile.id)
            preview_result = run_monthly_rotation_backtest(settings, prices, financials, membership)
            result = _compose_dashboard_result(historical_result, preview_result)
            storage.close()
            statuses.append(
                build_profile_dashboard_dataset(
                    root,
                    profile,
                    settings,
                    result,
                    prices=prices,
                    membership=membership,
                    financial_snapshots=financials,
                )
            )
        except Exception as error:
            statuses.append(empty_status(profile, str(error)))
    write_dashboard_manifest(root, statuses)
    typer.echo(str(root / "manifest.json"))


@app.command()
def refresh_dashboard(
    output_dir: Path = Path("outputs/dashboard"),
    registry_file: Path = Path("data/universe/bist_sanayi_investing_registry.csv"),
    skip_price_load: bool = False,
    skip_network_loaders: bool = False,
) -> None:
    for group in _group_active_profiles_by_refresh_group():
        _run_refresh_group(
            group["settings"],
            group["config_path"],
            registry_file=registry_file,
            skip_price_load=skip_price_load,
            skip_network_loaders=skip_network_loaders,
        )
    build_dashboard(output_dir=output_dir)


@app.command()
def serve_admin() -> None:
    settings = load_admin_settings()
    uvicorn.run(create_app(settings), host="0.0.0.0", port=settings.port)


@app.command()
def load_current_xusin_universe(config: Path = Path("config.yaml")) -> None:
    settings = load_config(config)
    membership = fetch_current_static_xusin_membership(start_date=settings.backtest.start_date)
    symbols = membership[["symbol"]].drop_duplicates()
    settings.universe.symbols_file.parent.mkdir(parents=True, exist_ok=True)
    symbols.to_csv(settings.universe.symbols_file, index=False)
    if settings.universe.membership_file is not None:
        membership.to_csv(settings.universe.membership_file, index=False)
    storage = DuckDbStorage(settings.data.duckdb_path)
    storage.initialize()
    storage.replace_table("universe_membership", membership)
    storage.close()


@app.command()
def reconstruct_xusin_universe(config: Path = Path("config.yaml")) -> None:
    settings = load_config(config)
    current_symbols = load_static_universe(settings.universe.symbols_file)
    membership, changes = fetch_reconstructed_xusin_membership(
        current_symbols=current_symbols,
        start_date=settings.backtest.start_date,
        today=settings.backtest.end_date,
        universe_name=settings.universe.name,
    )
    if settings.universe.membership_file is None:
        raise typer.BadParameter("reconstructed_historical universe requires universe.membership_file")
    settings.universe.membership_file.parent.mkdir(parents=True, exist_ok=True)
    membership.to_csv(settings.universe.membership_file, index=False)
    changes.to_csv(settings.universe.membership_file.with_name("bist_sanayi_reconstruction_changes.csv"), index=False)
    storage = DuckDbStorage(settings.data.duckdb_path)
    storage.initialize()
    storage.replace_table("universe_membership", membership)
    storage.close()


@app.command()
def export_report(
    config: Path = Path("config.yaml"),
    output: Path = Path("reports/backtest_report.xlsx"),
) -> None:
    settings = load_config(config)
    storage = DuckDbStorage(settings.data.duckdb_path)
    storage.initialize()
    monthly_results = storage.read_table("backtest_monthly_results")
    selected_positions = storage.read_table("backtest_selected_positions")
    rejected_candidates = pd.DataFrame()
    export_excel_report(output, settings, monthly_results, selected_positions, rejected_candidates)
    storage.close()


def _load_membership_for_run(settings):
    if settings.universe.mode == "current_static":
        symbols = load_static_universe(settings.universe.symbols_file, settings.universe.symbol_aliases_file)
        return build_current_static_membership(symbols, settings.backtest.start_date, str(settings.universe.symbols_file))
    if settings.universe.mode == "reconstructed_historical":
        if settings.universe.membership_file is None or not settings.universe.membership_file.exists():
            raise typer.BadParameter("reconstructed_historical universe requires an explicit reconstructed membership_file")
        return load_universe_membership(settings.universe.membership_file, settings.universe.symbol_aliases_file)
    raise typer.BadParameter(f"Unsupported universe mode: {settings.universe.mode}")


def _symbol_completeness(storage: DuckDbStorage, symbol: str, target_statement_ids: set[str]) -> dict:
    ignored_ids = _get_ignored_statement_ids(storage, symbol)
    effective_target_ids = target_statement_ids - ignored_ids
    statement_df = storage.connection.execute(
        """
        SELECT statement_id, shares_outstanding, announcement_datetime
        FROM financial_statements
        WHERE symbol = ?
        """,
        [symbol.upper()],
    ).df()
    item_df = storage.connection.execute(
        """
        SELECT statement_id, item_code
        FROM financial_statement_items
        WHERE symbol = ?
        """,
        [symbol.upper()],
    ).df()
    statement_ids_in_db = set(statement_df["statement_id"].astype(str).tolist()) if not statement_df.empty else set()
    missing_statement_ids = effective_target_ids - statement_ids_in_db

    required_items = {"net_income", "equity", "operating_profit"}
    items_grouped = (
        item_df.groupby("statement_id")["item_code"].apply(lambda values: set(values.astype(str).tolist())).to_dict()
        if not item_df.empty
        else {}
    )
    incomplete_item_ids = {
        statement_id
        for statement_id in target_statement_ids.intersection(statement_ids_in_db)
        if not required_items.issubset(items_grouped.get(statement_id, set()))
    }
    shares_missing_ids = set()
    if not statement_df.empty:
        shares_missing_ids = set(
            statement_df[
                statement_df["statement_id"].astype(str).isin(effective_target_ids)
                & statement_df["shares_outstanding"].isna()
            ]["statement_id"].astype(str).tolist()
        )
    missing_or_incomplete = missing_statement_ids.union(incomplete_item_ids).union(shares_missing_ids)
    return {
        "is_complete": len(missing_or_incomplete) == 0,
        "missing_or_incomplete_statement_ids": missing_or_incomplete,
        "missing_statement_ids": missing_statement_ids,
        "incomplete_item_ids": incomplete_item_ids,
        "shares_missing_ids": shares_missing_ids,
        "ignored_statement_ids": ignored_ids,
    }


def _get_ignored_statement_ids(storage: DuckDbStorage, symbol: str) -> set[str]:
    if not _table_exists(storage, "statement_load_status"):
        return set()
    df = storage.connection.execute(
        """
        SELECT statement_id
        FROM statement_load_status
        WHERE symbol = ? AND status = 'legacy_nonfinancial'
        """,
        [symbol.upper()],
    ).df()
    if df.empty:
        return set()
    return set(df["statement_id"].astype(str).tolist())


def _table_exists(storage: DuckDbStorage, table_name: str) -> bool:
    row = storage.connection.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
        [table_name],
    ).fetchone()
    return row is not None and int(row[0]) > 0


def _mark_legacy_nonfinancial_if_needed(storage: DuckDbStorage, symbol: str, statement_ids: set[str]) -> set[str]:
    if not statement_ids:
        return set()
    placeholders = ", ".join(["?"] * len(statement_ids))
    coverage = storage.connection.execute(
        f"""
        WITH item AS (
            SELECT
                statement_id,
                max(CASE WHEN item_code='net_income' THEN 1 ELSE 0 END) AS has_net_income,
                max(CASE WHEN item_code='operating_profit' THEN 1 ELSE 0 END) AS has_operating_profit,
                max(CASE WHEN item_code='equity' THEN 1 ELSE 0 END) AS has_equity,
                max(CASE WHEN item_code='shares_outstanding' THEN 1 ELSE 0 END) AS has_shares,
                max(CASE WHEN item_code='total_debt' THEN 1 ELSE 0 END) AS has_debt
            FROM financial_statement_items
            WHERE symbol = ? AND statement_id IN ({placeholders})
            GROUP BY statement_id
        )
        SELECT
            s.statement_id,
            s.announcement_datetime,
            coalesce(i.has_net_income,0) has_net_income,
            coalesce(i.has_operating_profit,0) has_operating_profit,
            coalesce(i.has_equity,0) has_equity,
            coalesce(i.has_shares,0) has_shares,
            coalesce(i.has_debt,0) has_debt
        FROM financial_statements s
        LEFT JOIN item i ON i.statement_id = s.statement_id
        WHERE s.symbol = ? AND s.statement_id IN ({placeholders})
        """,
        [symbol.upper(), *statement_ids, symbol.upper(), *statement_ids],
    ).df()
    if coverage.empty:
        return set()
    legacy = coverage[
        (pd.to_datetime(coverage["announcement_datetime"], errors="coerce") < pd.Timestamp("2024-01-01"))
        & (coverage["has_debt"] == 1)
        & (coverage["has_net_income"] == 0)
        & (coverage["has_operating_profit"] == 0)
        & (coverage["has_equity"] == 0)
        & (coverage["has_shares"] == 0)
    ]
    legacy_ids = set(legacy["statement_id"].astype(str).tolist())
    if not legacy_ids:
        return set()
    status_rows = pd.DataFrame(
        [
            {
                "statement_id": statement_id,
                "symbol": symbol.upper(),
                "status": "legacy_nonfinancial",
                "reason": "only_total_debt_no_core_items_before_2024",
                "updated_at": datetime.utcnow(),
            }
            for statement_id in sorted(legacy_ids)
        ]
    )
    placeholders2 = ", ".join(["?"] * len(legacy_ids))
    storage.connection.execute(
        f"DELETE FROM statement_load_status WHERE statement_id IN ({placeholders2})",
        list(legacy_ids),
    )
    storage.append_table("statement_load_status", status_rows)
    return legacy_ids


def _upsert_statements(storage: DuckDbStorage, statements: pd.DataFrame) -> None:
    if statements.empty:
        return
    statements = _ensure_statement_ids(statements)
    statement_ids = statements["statement_id"].astype(str).tolist()
    placeholders = ", ".join(["?"] * len(statement_ids))
    storage.connection.execute(
        f"DELETE FROM financial_statements WHERE statement_id IN ({placeholders})",
        statement_ids,
    )
    storage.append_table("financial_statements", statements)


def _build_queenstocks_client(settings) -> QueenStocksClient:
    return QueenStocksClient.from_env(
        username_env=settings.data.queenstocks_username_env,
        password_env=settings.data.queenstocks_password_env,
        request_timeout_seconds=settings.data.queenstocks_request_timeout_seconds,
        min_request_interval_seconds=settings.data.queenstocks_min_request_interval_seconds,
    )


def _resolve_queenstocks_target_symbols(
    settings,
    *,
    symbols: str | None,
    max_symbols: int | None,
    start_index: int,
    batch_size: int | None,
) -> list[str]:
    target_symbols = (
        _parse_symbol_csv(symbols)
        if symbols is not None and symbols.strip()
        else load_static_universe(settings.universe.symbols_file, settings.universe.symbol_aliases_file)
    )
    if start_index < 0:
        raise typer.BadParameter("start_index must be non-negative")
    if batch_size is not None and batch_size <= 0:
        raise typer.BadParameter("batch_size must be positive when provided")
    if max_symbols is not None and max_symbols <= 0:
        raise typer.BadParameter("max_symbols must be positive when provided")
    if start_index:
        target_symbols = target_symbols[start_index:]
    if batch_size is not None:
        target_symbols = target_symbols[:batch_size]
    elif max_symbols is not None:
        target_symbols = target_symbols[:max_symbols]
    return target_symbols


def _resolve_queenstocks_backfill_targets(
    settings,
    *,
    symbols: str | None,
    fill_queue_file: Path,
    only_fill_queue: bool,
) -> list[str]:
    explicit_symbols = _parse_symbol_csv(symbols)
    if explicit_symbols:
        return explicit_symbols
    if only_fill_queue and fill_queue_file.exists():
        fill_queue = pd.read_csv(fill_queue_file)
        if "symbol" not in fill_queue.columns:
            raise typer.BadParameter(f"fill_queue_file is missing symbol column: {fill_queue_file}")
        queued_symbols = sorted(
            {
                str(value).strip().upper()
                for value in fill_queue["symbol"].tolist()
                if str(value).strip()
            }
        )
        if queued_symbols:
            return queued_symbols
    return load_static_universe(settings.universe.symbols_file, settings.universe.symbol_aliases_file)


def _parse_symbol_csv(symbols: str | None) -> list[str]:
    if symbols is None:
        return []
    parsed = [symbol.strip().upper() for symbol in symbols.split(",") if symbol.strip()]
    unique: list[str] = []
    seen: set[str] = set()
    for symbol in parsed:
        if symbol in seen:
            continue
        seen.add(symbol)
        unique.append(symbol)
    return unique


def _queenstocks_balance_format_slug(balance_format: str | None) -> str:
    if balance_format is None or not str(balance_format).strip():
        raise ValueError("missing_balance_format")
    text = (
        str(balance_format)
        .strip()
        .lower()
        .replace("ı", "i")
        .replace("ş", "s")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ö", "o")
        .replace("ç", "c")
    )
    normalized = unicodedata.normalize("NFKD", text)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")
    if not slug:
        raise ValueError(f"unsupported_balance_format:{balance_format}")
    return slug


def _queenstocks_probe_missing_fields(row: pd.Series) -> str:
    required_fields = (
        "shares_outstanding",
        "equity",
        "net_income",
        "operating_profit_est",
    )
    missing = [field for field in required_fields if pd.isna(row.get(field))]
    return ",".join(missing)


def _latest_known_shares_outstanding(storage: DuckDbStorage, symbol: str) -> float | None:
    row = storage.connection.execute(
        """
        SELECT shares_outstanding
        FROM financial_statements
        WHERE symbol = ?
          AND shares_outstanding IS NOT NULL
        ORDER BY announcement_date DESC NULLS LAST, period_end DESC NULLS LAST
        LIMIT 1
        """,
        [symbol.upper()],
    ).fetchone()
    if row is None:
        return None
    try:
        return float(row[0])
    except (TypeError, ValueError):
        return None


def _replace_items_for_statements(storage: DuckDbStorage, items: pd.DataFrame) -> None:
    if items.empty:
        return
    statement_ids = sorted(set(items["statement_id"].astype(str).tolist()))
    placeholders = ", ".join(["?"] * len(statement_ids))
    storage.connection.execute(
        f"DELETE FROM financial_statement_items WHERE statement_id IN ({placeholders})",
        statement_ids,
    )
    storage.append_table("financial_statement_items", items)


def _prepare_financial_snapshot_candidates(
    statements: pd.DataFrame,
    items: pd.DataFrame,
    aliases: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if statements.empty:
        return pd.DataFrame()
    base = _ensure_statement_ids(statements)
    if aliases is not None and not aliases.empty:
        base = apply_symbol_aliases(base, aliases)
    base = base.copy()
    base["source_statement_id"] = base["statement_id"].astype(str)
    required_item_codes = ["net_income", "equity", "operating_profit", "cash", "total_debt"]
    if items.empty:
        pivot = pd.DataFrame(columns=["source_statement_id", *required_item_codes])
    else:
        filtered_items = items[items["item_code"].isin(required_item_codes)].copy()
        if aliases is not None and not aliases.empty:
            filtered_items = apply_symbol_aliases(filtered_items, aliases)
        pivot = (
            filtered_items.pivot_table(
                index="statement_id",
                columns="item_code",
                values="value",
                aggfunc="first",
            )
            .reset_index()
            .rename(columns={"statement_id": "source_statement_id"})
        )
        pivot["source_statement_id"] = pivot["source_statement_id"].astype(str)
    data = base.merge(pivot, on="source_statement_id", how="left")
    fiscal_period = data.get("fiscal_period", pd.Series(index=data.index, dtype="object")).astype(str)
    quarter = pd.to_numeric(fiscal_period.str.extract(r"Q([1-4])", expand=False), errors="coerce")
    period_end = pd.to_datetime(data["period_end"], errors="coerce")
    inferred_quarter = pd.to_numeric(((period_end.dt.month - 1) // 3) + 1, errors="coerce")
    data["fiscal_quarter"] = quarter.fillna(inferred_quarter)
    data["period_end"] = period_end.dt.date
    data["announcement_datetime"] = pd.to_datetime(data.get("announcement_datetime"), errors="coerce", utc=True)
    data["announcement_date"] = pd.to_datetime(data.get("announcement_date"), errors="coerce").dt.date
    data["shares_announcement_datetime"] = pd.to_datetime(
        data.get("shares_announcement_datetime"),
        errors="coerce",
        utc=True,
    )
    data["source_url"] = data.get("source_url")
    data["announcement_source_url"] = data.get("announcement_source_url")
    data["raw_hash"] = data.get("raw_hash")
    data["source_system"] = data.apply(_infer_statement_source_system, axis=1)
    data["announcement_source_system"] = data.apply(_infer_announcement_source_system, axis=1)
    return data


def _build_financial_snapshots_from_statements(
    statements: pd.DataFrame,
    items: pd.DataFrame,
    aliases: pd.DataFrame | None = None,
    data_config=None,
) -> pd.DataFrame:
    data = _prepare_financial_snapshot_candidates(statements, items, aliases)
    if data.empty:
        return data
    statement_order = _statement_source_order(data_config)
    announcement_order = _announcement_source_order(data_config)
    resolved_rows: list[dict] = []
    for _, group in data.groupby(["symbol", "period_end"], dropna=False, sort=True):
        resolved_rows.append(_resolve_snapshot_group(group, statement_order, announcement_order))
    return pd.DataFrame(resolved_rows)


def _resolve_snapshot_group(
    group: pd.DataFrame,
    statement_order: list[str],
    announcement_order: list[str],
) -> dict:
    statement_row = _pick_statement_row(group, statement_order)
    announcement_row = _pick_announcement_row(group, announcement_order)
    resolved = statement_row.to_dict()
    if announcement_row is not None:
        resolved["announcement_datetime"] = announcement_row.get("announcement_datetime")
        resolved["announcement_date"] = announcement_row.get("announcement_date")
        resolved["announcement_source_url"] = announcement_row.get("announcement_source_url")
        resolved["announcement_source_system"] = announcement_row.get("announcement_source_system")
    return resolved


def _pick_statement_row(group: pd.DataFrame, statement_order: list[str]) -> pd.Series:
    ordered_sources = _ordered_sources(group["source_system"], statement_order)
    for source in ordered_sources:
        candidates = group[group["source_system"] == source].copy()
        complete = candidates[candidates.apply(_row_has_complete_statement, axis=1)]
        if not complete.empty:
            return _pick_most_recent_row(complete)
    for source in ordered_sources:
        candidates = group[group["source_system"] == source].copy()
        if not candidates.empty:
            return _pick_most_recent_row(candidates)
    return _pick_most_recent_row(group)


def _pick_announcement_row(group: pd.DataFrame, announcement_order: list[str]) -> pd.Series | None:
    valid = group[group["announcement_date"].notna() | group["announcement_datetime"].notna()].copy()
    if valid.empty:
        return None
    ordered_sources = _ordered_sources(valid["announcement_source_system"], announcement_order)
    for source in ordered_sources:
        candidates = valid[valid["announcement_source_system"] == source].copy()
        if not candidates.empty:
            return _pick_most_recent_row(candidates)
    return _pick_most_recent_row(valid)


def _pick_most_recent_row(frame: pd.DataFrame) -> pd.Series:
    sortable = frame.copy()
    sortable["__announcement_dt_sort"] = pd.to_datetime(
        sortable.get("announcement_datetime"),
        errors="coerce",
        utc=True,
    )
    sortable["__announcement_date_sort"] = pd.to_datetime(
        sortable.get("announcement_date"),
        errors="coerce",
    )
    sortable = sortable.sort_values(
        ["__announcement_dt_sort", "__announcement_date_sort", "source_statement_id"],
        ascending=[False, False, True],
        na_position="last",
    )
    return sortable.iloc[0].drop(labels=["__announcement_dt_sort", "__announcement_date_sort"], errors="ignore")


def _row_has_complete_statement(row: pd.Series) -> bool:
    return bool(
        pd.notna(row.get("net_income"))
        and pd.notna(row.get("equity"))
        and pd.notna(row.get("operating_profit"))
        and pd.notna(row.get("shares_outstanding"))
    )


def _ordered_sources(source_values: pd.Series, preferred_order: list[str]) -> list[str]:
    present = [str(value) for value in source_values.dropna().astype(str).tolist() if str(value).strip()]
    ordered = [source for source in preferred_order if source in present]
    ordered.extend(source for source in present if source not in ordered)
    unique: list[str] = []
    seen: set[str] = set()
    for source in ordered:
        if source in seen:
            continue
        seen.add(source)
        unique.append(source)
    return unique


def _statement_source_order(data_config) -> list[str]:
    if data_config is None:
        return []
    return _dedupe_sources(
        [_normalize_statement_source_name(data_config.primary_statement_source)]
        + [_normalize_statement_source_name(source) for source in data_config.statement_fallback_sources]
    )


def _announcement_source_order(data_config) -> list[str]:
    if data_config is None:
        return []
    return _dedupe_sources(
        [_normalize_announcement_source_name(data_config.primary_announcement_source)]
        + [_normalize_announcement_source_name(source) for source in data_config.announcement_fallback_sources]
    )


def _dedupe_sources(sources: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for source in sources:
        normalized = str(source or "").strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def _normalize_statement_source_name(source: str | None) -> str:
    if source is None or (not isinstance(source, str) and pd.isna(source)):
        return ""
    normalized = str(source).strip().lower()
    if normalized in {"", "nan", "none"}:
        return ""
    if normalized in {"fallback_registry", "financials_fallback_registry"}:
        return "financial_fallback_registry"
    return normalized


def _normalize_announcement_source_name(source: str | None) -> str:
    if source is None or (not isinstance(source, str) and pd.isna(source)):
        return ""
    normalized = str(source).strip().lower()
    if normalized in {"", "nan", "none"}:
        return ""
    if normalized == "queenstocks":
        return "queenstocks_kap_news"
    if normalized in {"fallback_registry", "announcement_fallbacks_registry"}:
        return "announcement_fallback_registry"
    return normalized


def _infer_statement_source_system(row: pd.Series) -> str:
    explicit = _normalize_statement_source_name(row.get("source_system"))
    if explicit:
        return explicit
    statement_id = str(row.get("statement_id") or row.get("source_statement_id") or "").upper()
    source_url = str(row.get("source_url") or "").lower()
    if statement_id.startswith("QUEENSTOCKS-") or "queenstocks.com" in source_url:
        return "queenstocks"
    if statement_id.startswith("ISYATIRIM-") or "isyatirim" in source_url or "data.aspx/malitablo" in source_url:
        return "isyatirim"
    if "kap.org.tr" in source_url:
        return "kap"
    if source_url:
        return "financial_fallback_registry"
    return "unknown"


def _infer_announcement_source_system(row: pd.Series) -> str:
    explicit = _normalize_announcement_source_name(row.get("announcement_source_system"))
    if explicit:
        return explicit
    announcement_url = str(row.get("announcement_source_url") or "").lower()
    if "queenstocks.com" in announcement_url:
        return "queenstocks_kap_news"
    if "investing.com" in announcement_url:
        return "investing"
    if "e-sirket.mkk.com.tr" in announcement_url:
        return "mkk_esirket"
    statement_source = _infer_statement_source_system(row)
    if statement_source == "financial_fallback_registry":
        return "financial_fallback_registry"
    if announcement_url:
        return "issuer_ir"
    return "unknown"


def _group_active_profiles_by_refresh_group() -> list[dict]:
    groups: dict[str, dict] = {}
    for profile in active_dashboard_profiles():
        settings = load_config(profile.config_path)
        refresh_group = str(settings.data.refresh_group or "current")
        signature = (
            settings.data.duckdb_path,
            settings.universe.symbols_file,
            settings.universe.membership_file,
            tuple(_statement_source_order(settings.data)),
            tuple(_announcement_source_order(settings.data)),
        )
        if refresh_group not in groups:
            groups[refresh_group] = {
                "settings": settings,
                "config_path": profile.config_path,
                "profiles": [profile],
                "signature": signature,
            }
            continue
        if groups[refresh_group]["signature"] != signature:
            raise typer.BadParameter(
                f"refresh_group={refresh_group} uses inconsistent data settings across dashboard profiles"
            )
        groups[refresh_group]["profiles"].append(profile)
    return list(groups.values())


def _run_refresh_group(
    settings,
    config_path: Path,
    *,
    registry_file: Path,
    skip_price_load: bool,
    skip_network_loaders: bool,
) -> None:
    typer.echo(
        f"[refresh-group:{settings.data.refresh_group}] "
        f"db={settings.data.duckdb_path} sources={','.join(_statement_source_order(settings.data))} "
        f"announcements={','.join(_announcement_source_order(settings.data))}"
    )
    if not skip_price_load:
        load_prices(config_path)
    if not skip_network_loaders:
        for source in _statement_source_order(settings.data):
            try:
                _run_statement_source_refresh(source, config_path)
                typer.echo(f"[refresh-group:{settings.data.refresh_group}] statement_source_ok={source}")
            except Exception as error:
                typer.echo(f"[refresh-group:{settings.data.refresh_group}] statement_source_failed={source} error={error}")
        for source in _announcement_source_order(settings.data):
            try:
                _run_announcement_source_refresh(source, config_path, registry_file)
                typer.echo(f"[refresh-group:{settings.data.refresh_group}] announcement_source_ok={source}")
            except Exception as error:
                typer.echo(
                    f"[refresh-group:{settings.data.refresh_group}] announcement_source_failed={source} error={error}"
                )
    build_snapshots(config_path)


def _run_statement_source_refresh(source: str, config_path: Path) -> None:
    normalized = _normalize_statement_source_name(source)
    if normalized == "isyatirim":
        load_financials_isyatirim_live(config=config_path)
        refresh_isyatirim_load_status(config=config_path)
        return
    if normalized == "queenstocks":
        load_financials_queenstocks_live(config=config_path)
        return
    if normalized == "financial_fallback_registry":
        load_financials_fallback_registry(config=config_path)
        return
    if normalized == "kap":
        load_financials_kap(config=config_path)
        return
    raise typer.BadParameter(f"unsupported statement source: {source}")


def _run_announcement_source_refresh(source: str, config_path: Path, registry_file: Path) -> None:
    normalized = _normalize_announcement_source_name(source)
    if normalized == "investing":
        if not registry_file.exists():
            typer.echo(f"investing registry not found, skipping: {registry_file}")
            return
        load_announcement_dates_investing_live(registry_file, config=config_path, only_missing=True)
        return
    if normalized == "queenstocks_kap_news":
        load_announcement_dates_queenstocks_live(config=config_path)
        return
    if normalized == "issuer_ir":
        load_announcement_dates_issuer_ir_fallback(config=config_path, only_missing=True)
        return
    if normalized == "mkk_esirket":
        load_announcement_dates_mkk_esirket_fallback(config=config_path, only_missing=True)
        return
    if normalized in {"announcement_fallback_registry", "financial_fallback_registry"}:
        load_announcement_dates_fallback_registry(config=config_path, only_missing=True)
        return
    raise typer.BadParameter(f"unsupported announcement source: {source}")


def _build_queenstocks_period_level_diff(candidates: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for (symbol, period_end), group in candidates.groupby(["symbol", "period_end"], dropna=False, sort=True):
        sources = sorted(set(group["source_system"].dropna().astype(str).tolist()))
        has_queenstocks = "queenstocks" in sources
        has_non_queenstocks = any(source != "queenstocks" for source in sources)
        if has_queenstocks and has_non_queenstocks:
            continue
        rows.append(
            {
                "symbol": symbol,
                "period_end": period_end,
                "queenstocks_present": has_queenstocks,
                "other_sources_present": has_non_queenstocks,
                "sources": ",".join(sources),
            }
        )
    return pd.DataFrame(rows)


def _build_queenstocks_statement_value_mismatch(candidates: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for (symbol, period_end), group in candidates.groupby(["symbol", "period_end"], dropna=False, sort=True):
        queen = group[group["source_system"] == "queenstocks"].copy()
        other = group[group["source_system"] != "queenstocks"].copy()
        if queen.empty or other.empty:
            continue
        queen_row = _pick_most_recent_row(queen)
        other_row = _pick_statement_row(other, ["isyatirim", "financial_fallback_registry", "kap"])
        for field in ["net_income", "equity", "operating_profit", "cash", "total_debt", "shares_outstanding"]:
            queen_value = queen_row.get(field)
            other_value = other_row.get(field)
            if pd.isna(queen_value) or pd.isna(other_value):
                continue
            if abs(float(queen_value) - float(other_value)) <= 1e-9:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "period_end": period_end,
                    "field": field,
                    "queenstocks_value": queen_value,
                    "other_value": other_value,
                    "other_source_system": other_row.get("source_system"),
                    "queenstocks_statement_id": queen_row.get("source_statement_id"),
                    "other_statement_id": other_row.get("source_statement_id"),
                }
            )
    return pd.DataFrame(rows)


def _build_queenstocks_announcement_date_mismatch(candidates: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for (symbol, period_end), group in candidates.groupby(["symbol", "period_end"], dropna=False, sort=True):
        queen = group[group["announcement_source_system"] == "queenstocks_kap_news"].copy()
        other = group[group["announcement_source_system"] != "queenstocks_kap_news"].copy()
        if queen.empty or other.empty:
            continue
        queen_row = _pick_announcement_row(queen, ["queenstocks_kap_news"])
        other_row = _pick_announcement_row(
            other,
            ["investing", "issuer_ir", "mkk_esirket", "announcement_fallback_registry", "financial_fallback_registry"],
        )
        if queen_row is None or other_row is None:
            continue
        queen_date = queen_row.get("announcement_date")
        other_date = other_row.get("announcement_date")
        if pd.isna(queen_date) or pd.isna(other_date) or queen_date == other_date:
            continue
        rows.append(
            {
                "symbol": symbol,
                "period_end": period_end,
                "queenstocks_announcement_date": queen_date,
                "other_announcement_date": other_date,
                "other_announcement_source_system": other_row.get("announcement_source_system"),
                "queenstocks_source_url": queen_row.get("announcement_source_url"),
                "other_source_url": other_row.get("announcement_source_url"),
            }
        )
    return pd.DataFrame(rows)


def _ensure_statement_ids(statements: pd.DataFrame) -> pd.DataFrame:
    repaired = statements.copy()
    if "statement_id" not in repaired.columns:
        repaired["statement_id"] = None
    repaired["statement_id"] = repaired["statement_id"].astype("object")
    missing_mask = repaired["statement_id"].isna() | (repaired["statement_id"].astype(str).str.strip() == "")
    if not missing_mask.any():
        return repaired
    period_end = pd.to_datetime(repaired.loc[missing_mask, "period_end"], errors="coerce")
    repaired.loc[missing_mask, "statement_id"] = (
        "ISYATIRIM-"
        + repaired.loc[missing_mask, "symbol"].astype(str).str.upper()
        + "-"
        + period_end.dt.strftime("%Y%m%d")
    )
    return repaired


def _read_records_file(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix == ".json":
        return pd.DataFrame(pd.read_json(path))
    raise typer.BadParameter(f"Unsupported source file format: {path.suffix}")


def _build_investing_earnings_url(record: dict) -> str:
    if record.get("earnings_url"):
        return str(record["earnings_url"])
    slug = record.get("investing_slug")
    if slug:
        return f"https://tr.investing.com/equities/{slug}-earnings"
    raise typer.BadParameter("record is missing earnings_url and investing_slug")


if __name__ == "__main__":
    app()
