from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AdminSettings:
    dashboard_data_root: Path
    admin_password: str | None
    admin_password_hash: str | None
    session_secret: str
    port: int


def load_admin_settings() -> AdminSettings:
    dashboard_root = Path(os.environ.get("DASHBOARD_DATA_ROOT", "outputs/dashboard"))
    admin_password = os.environ.get("ADMIN_PASSWORD")
    admin_password_hash = os.environ.get("ADMIN_PASSWORD_HASH")
    session_secret = os.environ.get("SESSION_SECRET", "change-me-session-secret")
    port = int(os.environ.get("PORT", "8000"))
    return AdminSettings(
        dashboard_data_root=dashboard_root,
        admin_password=admin_password,
        admin_password_hash=admin_password_hash,
        session_secret=session_secret,
        port=port,
    )
