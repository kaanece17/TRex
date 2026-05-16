from __future__ import annotations

from pathlib import Path
from datetime import UTC, datetime

import pandas as pd
import requests
import typer

from bist_factor_backtest.backtest.monthly_rotation import run_monthly_rotation_backtest
from bist_factor_backtest.config import load_config
from bist_factor_backtest.data.coverage_audit import (
    build_alternative_coverage_audit,
    build_alternative_fill_queue,
    summarize_alternative_coverage,
)
from bist_factor_backtest.data.earnings_investing import InvestingEarningsLoader, merge_announcements_into_statements
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
from bist_factor_backtest.data.index_announcements import fetch_reconstructed_xusin_membership
from bist_factor_backtest.data.price_loader_yfinance import YFinancePriceLoader
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
def load_financials_kap(
    config: Path = Path("config.yaml"),
    strict: bool = False,
    only_incomplete: bool = False,
    max_retries: int = 5,
    backoff_seconds: float = 1.5,
    request_timeout_seconds: int = 20,
    min_request_interval_seconds: float = 1.0,
    rate_limit_sleep_seconds: float = 30.0,
    preflight_checks: int = 3,
) -> None:
    settings = load_config(config)
    symbols = load_static_universe(settings.universe.symbols_file, settings.universe.symbol_aliases_file)
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
            _upsert_symbol_load_status(storage, symbol, "completed", "isyatirim_loaded")
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
            _upsert_symbol_load_status(storage, symbol, "completed", "isyatirim_loaded")
    if failures:
        typer.echo(pd.concat(failures, ignore_index=True).to_string(index=False))
    storage.close()


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


def _filter_only_incomplete_symbols(symbols: list[str], duckdb_path: Path | str) -> list[str]:
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
    completed_symbols = set(
        latest_status[latest_status["status"].astype(str) == "completed"]["symbol"].astype(str).tolist()
    )
    return [symbol for symbol in symbols if symbol.upper() not in completed_symbols]


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
    snapshots = _build_financial_snapshots_from_statements(statements, items, aliases)
    snapshots = add_ttm_values(snapshots)
    storage.replace_table("financial_snapshots", snapshots)
    storage.close()


@app.command()
def run(config: Path = Path("config.yaml")) -> None:
    settings = load_config(config)
    storage = DuckDbStorage(settings.data.duckdb_path)
    storage.initialize()
    prices = storage.read_table("market_prices")
    financials = storage.read_table("financial_snapshots")
    membership = _load_membership_for_run(settings)
    result = run_monthly_rotation_backtest(settings, prices, financials, membership)
    storage.append_table("backtest_monthly_results", result["monthly_results"])
    if not result["selected_positions"].empty:
        storage.append_table("backtest_selected_positions", result["selected_positions"])
    typer.echo(result["run_id"])
    storage.close()


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


def _build_financial_snapshots_from_statements(
    statements: pd.DataFrame,
    items: pd.DataFrame,
    aliases: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if statements.empty:
        return pd.DataFrame()
    base = _ensure_statement_ids(statements)
    if aliases is not None and not aliases.empty:
        base = apply_symbol_aliases(base, aliases)
    base = base.rename(columns={"statement_id": "source_statement_id"})
    base["source_statement_id"] = base["source_statement_id"].astype(str)
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
    data["announcement_datetime"] = pd.to_datetime(data.get("announcement_datetime"), errors="coerce")
    data["announcement_date"] = pd.to_datetime(data["announcement_date"], errors="coerce").dt.date
    data["source_url"] = data.get("source_url")
    data["announcement_source_url"] = data.get("announcement_source_url")
    data["raw_hash"] = data.get("raw_hash")
    return data


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
