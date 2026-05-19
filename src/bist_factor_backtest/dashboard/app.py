from __future__ import annotations

import hashlib
import math
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from pathlib import Path

import json

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from bist_factor_backtest.dashboard.settings import AdminSettings, load_admin_settings


FAILED_LOGINS: dict[str, deque[datetime]] = defaultdict(deque)
FAILED_LOGIN_WINDOW = timedelta(minutes=15)
FAILED_LOGIN_LIMIT = 5


def create_app(settings: AdminSettings | None = None) -> FastAPI:
    app_settings = settings or load_admin_settings()
    app = FastAPI(title="TRex Yonetim Paneli")
    app.add_middleware(
        SessionMiddleware,
        secret_key=app_settings.session_secret,
        same_site="lax",
        https_only=False,
    )

    base_dir = Path(__file__).resolve().parent
    templates = Jinja2Templates(directory=str(base_dir / "templates"))
    app.mount("/static", StaticFiles(directory=str(base_dir / "static")), name="static")
    templates.env.filters["fmt_num"] = _format_number
    templates.env.filters["fmt_pct"] = _format_percent
    templates.env.filters["fmt_month"] = _format_month
    templates.env.filters["confidence_label"] = _confidence_label

    def load_manifest() -> dict:
        manifest_path = app_settings.dashboard_data_root / "manifest.json"
        if not manifest_path.exists():
            return {"generated_at": None, "profiles": []}
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def load_profile_data(profile_id: str) -> dict[str, object]:
        profile_dir = app_settings.dashboard_data_root / profile_id
        return {
            "summary": _load_json(profile_dir / "summary.json", {}),
            "monthly_returns": _load_json(profile_dir / "monthly_returns.json", []),
            "monthly_regimes": _load_json(profile_dir / "monthly_regimes.json", []),
            "selected_positions": _load_json(profile_dir / "selected_positions.json", []),
            "next_month_preview": _load_json(profile_dir / "next_month_preview.json", []),
            "next_month_preview_alerts": _load_json(profile_dir / "next_month_preview_alerts.json", []),
            "next_month_preview_stale_bases": _load_json(profile_dir / "next_month_preview_stale_bases.json", []),
            "missing_financials": _load_json(profile_dir / "missing_financials.json", []),
            "current_month_alerts": _load_json(profile_dir / "current_month_alerts.json", []),
            "current_month_stale_bases": _load_json(profile_dir / "current_month_stale_bases.json", []),
            "symbol_confidence": _load_json(profile_dir / "symbol_confidence.json", []),
        }

    def load_refresh_status() -> dict[str, object]:
        return _load_json(app_settings.dashboard_data_root / "refresh_status.json", {})

    def ensure_auth(request: Request) -> RedirectResponse | None:
        if request.session.get("authenticated"):
            return None
        return RedirectResponse("/admin/login", status_code=302)

    def selected_profile(request: Request, manifest: dict) -> str | None:
        requested = request.query_params.get("config")
        profiles = manifest.get("profiles", [])
        valid_ids = [profile["profile_id"] for profile in profiles]
        if requested in valid_ids:
            return requested
        return valid_ids[0] if valid_ids else None

    def regime_for_month(profile_data: dict[str, object], month: str | None) -> dict[str, object]:
        if month is None:
            return {}
        for row in profile_data.get("monthly_regimes", []):
            if row.get("month") == month:
                return row
        return {}

    @app.get("/health")
    def health() -> JSONResponse:
        return JSONResponse({"ok": True})

    @app.get("/admin/login", response_class=HTMLResponse)
    def login_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": None},
        )

    @app.post("/admin/login")
    def login(request: Request, password: str = Form(...)):
        if _is_rate_limited(request.client.host if request.client else "unknown"):
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "Too many failed attempts. Try again later."},
                status_code=429,
            )
        if not _verify_password(password, app_settings):
            _record_failed_login(request.client.host if request.client else "unknown")
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "Invalid password."},
                status_code=401,
            )
        request.session["authenticated"] = True
        return RedirectResponse("/", status_code=302)

    @app.post("/admin/logout")
    def logout(request: Request) -> RedirectResponse:
        request.session.clear()
        return RedirectResponse("/admin/login", status_code=302)

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        auth = ensure_auth(request)
        if auth is not None:
            return auth
        manifest = load_manifest()
        profile_id = selected_profile(request, manifest)
        profile_data = load_profile_data(profile_id) if profile_id else {}
        preview_month = profile_data.get("summary", {}).get("preview_month")
        current_month = profile_data.get("summary", {}).get("current_month")
        display_month = preview_month or current_month
        if preview_month and profile_data.get("next_month_preview"):
            current_positions = profile_data.get("next_month_preview", [])
            current_alerts = profile_data.get("next_month_preview_alerts", [])
            current_stale_bases = profile_data.get("next_month_preview_stale_bases", [])
        else:
            current_positions = [
                row for row in profile_data.get("selected_positions", [])
                if row.get("month") == current_month
            ]
            current_positions = _dedupe_positions_for_open_month(current_positions, current_month)
            current_alerts = profile_data.get("current_month_alerts", [])
            current_stale_bases = profile_data.get("current_month_stale_bases", [])
        return templates.TemplateResponse(
            request,
            "home.html",
            {
                "manifest": manifest,
                "selected_profile": profile_id,
                "summary": profile_data.get("summary", {}),
                "current_positions": current_positions,
                "current_alerts": current_alerts,
                "current_stale_bases": current_stale_bases,
                "current_regime": regime_for_month(profile_data, display_month),
                "refresh_status": load_refresh_status(),
            },
        )

    @app.get("/positions", response_class=HTMLResponse)
    def positions(request: Request):
        auth = ensure_auth(request)
        if auth is not None:
            return auth
        manifest = load_manifest()
        profile_id = selected_profile(request, manifest)
        profile_data = load_profile_data(profile_id) if profile_id else {}
        all_positions = profile_data.get("selected_positions", [])
        preview_month = profile_data.get("summary", {}).get("preview_month")
        months = sorted({str(row.get("month")) for row in all_positions if row.get("month")})
        if preview_month:
            months = sorted(set(months + [str(preview_month)]))
        years = sorted({month[:4] for month in months})
        selected_year = request.query_params.get("year")
        selected_month_num = request.query_params.get("month")
        if selected_year and selected_month_num:
            target = f"{selected_year}-{selected_month_num.zfill(2)}"
        else:
            target = preview_month or profile_data.get("summary", {}).get("current_month")
        selected_year = selected_year or (target[:4] if target else None)
        selected_month_num = selected_month_num or (target[-2:] if target else None)
        if preview_month and target == preview_month:
            positions_for_month = profile_data.get("next_month_preview", [])
        else:
            positions_for_month = [row for row in all_positions if row.get("month") == target]
        if target == profile_data.get("summary", {}).get("current_month"):
            positions_for_month = _dedupe_positions_for_open_month(positions_for_month, target)
        latest_data_month = profile_data.get("summary", {}).get("latest_data_month") or profile_data.get("summary", {}).get("current_month")
        if preview_month and target == preview_month:
            current_alerts = profile_data.get("next_month_preview_alerts", [])
            stale_base_alerts = profile_data.get("next_month_preview_stale_bases", [])
        else:
            current_alerts = profile_data.get("current_month_alerts", []) if target == latest_data_month else []
            stale_base_alerts = profile_data.get("current_month_stale_bases", []) if target == latest_data_month else []
        month_regime = regime_for_month(profile_data, target)
        return templates.TemplateResponse(
            request,
            "positions.html",
            {
                "manifest": manifest,
                "selected_profile": profile_id,
                "summary": profile_data.get("summary", {}),
                "months": months,
                "years": years,
                "selected_year": selected_year,
                "selected_month_num": selected_month_num,
                "selected_month": target,
                "positions": positions_for_month,
                "alerts": current_alerts,
                "stale_base_alerts": stale_base_alerts,
                "month_regime": month_regime,
                "refresh_status": load_refresh_status(),
            },
        )

    @app.get("/missing-financials", response_class=HTMLResponse)
    def missing_financials(request: Request):
        auth = ensure_auth(request)
        if auth is not None:
            return auth
        manifest = load_manifest()
        profile_id = selected_profile(request, manifest)
        profile_data = load_profile_data(profile_id) if profile_id else {}
        rows = profile_data.get("missing_financials", [])
        months = sorted({str(row.get("month")) for row in profile_data.get("missing_financials", []) if row.get("month")})
        years = sorted({month[:4] for month in months})
        selected_year = request.query_params.get("year")
        selected_month_num = request.query_params.get("month")
        if selected_year and selected_month_num:
            target = f"{selected_year}-{selected_month_num.zfill(2)}"
            rows = [row for row in rows if row.get("month") == target]
        else:
            target = None
        return templates.TemplateResponse(
            request,
            "missing_financials.html",
            {
                "manifest": manifest,
                "selected_profile": profile_id,
                "months": months,
                "years": years,
                "rows": rows,
                "selected_month": target,
                "selected_year": selected_year,
                "selected_month_num": selected_month_num,
            },
        )

    return app


def _load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _verify_password(password: str, settings: AdminSettings) -> bool:
    if settings.admin_password is not None:
        return password == settings.admin_password
    if settings.admin_password_hash is not None:
        raw_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        candidate = settings.admin_password_hash.removeprefix("sha256:")
        return raw_hash == candidate
    return False


def _record_failed_login(client_id: str) -> None:
    now = datetime.now(UTC)
    attempts = FAILED_LOGINS[client_id]
    attempts.append(now)
    _prune_attempts(attempts, now)


def _is_rate_limited(client_id: str) -> bool:
    now = datetime.now(UTC)
    attempts = FAILED_LOGINS[client_id]
    _prune_attempts(attempts, now)
    return len(attempts) >= FAILED_LOGIN_LIMIT


def _prune_attempts(attempts: deque[datetime], now: datetime) -> None:
    while attempts and now - attempts[0] > FAILED_LOGIN_WINDOW:
        attempts.popleft()


def _format_number(value: object) -> str:
    if value is None or value == "":
        return "-"
    try:
        number = float(value)
    except Exception:
        return str(value)
    if math.isnan(number) or math.isinf(number):
        return "-"
    formatted = f"{number:,.2f}"
    return formatted.rstrip("0").rstrip(".")


def _format_percent(value: object) -> str:
    if value is None or value == "":
        return "-"
    try:
        number = float(value)
    except Exception:
        return str(value)
    if math.isnan(number) or math.isinf(number):
        return "-"
    return f"{number * 100:,.2f}%"


def _format_month(value: object) -> str:
    if value is None:
        return "-"
    raw = str(value)
    if len(raw) == 7 and raw[4] == "-":
        return f"{raw[:4]} / {raw[-2:]}"
    return raw


def _dedupe_positions_for_open_month(rows: list[dict], month: str | None) -> list[dict]:
    if not rows or month is None:
        return rows
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("symbol"))].append(row)

    resolved: list[dict] = []
    for symbol_rows in grouped.values():
        preferred = next((row for row in symbol_rows if row.get("position_status") == "open"), None)
        chosen = dict(preferred or symbol_rows[0])
        chosen["position_status"] = "open"
        chosen["position_status_detail"] = "Acik pozisyon, henuz realize olmadi"
        chosen["net_return"] = None
        chosen["gross_return"] = None
        chosen["sell_price"] = None
        resolved.append(chosen)
    return sorted(resolved, key=lambda row: (-float(row.get("score") or 0), str(row.get("symbol") or "")))


def _confidence_label(value: object) -> str:
    mapping = {
        "winner": "kazandiran",
        "neutral": "notr",
        "loser": "kaybettiren",
    }
    return mapping.get(str(value), str(value))
