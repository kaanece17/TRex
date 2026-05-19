from __future__ import annotations

import sys
from pathlib import Path

import uvicorn


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "app" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bist_factor_backtest.dashboard.app import create_app  # noqa: E402
from bist_factor_backtest.dashboard.settings import load_admin_settings  # noqa: E402


if __name__ == "__main__":
    settings = load_admin_settings()
    uvicorn.run(create_app(settings), host="0.0.0.0", port=settings.port)
