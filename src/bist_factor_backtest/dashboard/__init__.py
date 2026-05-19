from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    current = Path(__file__).resolve()
    for candidate in current.parents:
        if (candidate / "config.formula_research.yaml").exists():
            return candidate
        if (
            (candidate / "app").is_dir()
            and (candidate / "app" / "config.formula_research.yaml").exists()
        ):
            return candidate / "app"
    return current.parents[3]
