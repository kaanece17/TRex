from __future__ import annotations

import shutil
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist" / "dashboard_vps_bundle"
APP_ROOT = OUTPUT / "app" / "src" / "bist_factor_backtest"
DATA_ROOT = OUTPUT / "data" / "dashboard"
DEPLOY_ROOT = ROOT / "deploy" / "dashboard_minimal"


def copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def build_bundle() -> tuple[Path, Path]:
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir(parents=True, exist_ok=True)

    copy_file(ROOT / "src" / "bist_factor_backtest" / "__init__.py", APP_ROOT / "__init__.py")
    copy_file(ROOT / "src" / "bist_factor_backtest" / "config.py", APP_ROOT / "config.py")
    copy_tree(ROOT / "src" / "bist_factor_backtest" / "dashboard", APP_ROOT / "dashboard")
    copy_tree(ROOT / "outputs" / "dashboard", DATA_ROOT)

    copy_file(DEPLOY_ROOT / "requirements-dashboard.txt", OUTPUT / "requirements-dashboard.txt")
    copy_file(DEPLOY_ROOT / "run_dashboard.py", OUTPUT / "run_dashboard.py")
    copy_file(DEPLOY_ROOT / "trex-dashboard.service.example", OUTPUT / "trex-dashboard.service.example")

    env_example = OUTPUT / ".env.example"
    env_example.write_text(
        "\n".join(
            [
                "PORT=8011",
                "SESSION_SECRET=change-me-session-secret",
                "ADMIN_PASSWORD=change-me-admin-password",
                "DASHBOARD_DATA_ROOT=/opt/trex-dashboard/data/dashboard",
                "",
            ]
        ),
        encoding="utf-8",
    )

    readme = OUTPUT / "README.md"
    readme.write_text(
        "\n".join(
            [
                "# TRex Dashboard Minimal Bundle",
                "",
                "This bundle contains only the files needed to serve the static dashboard.",
                "",
                "Contents:",
                "- app/src/bist_factor_backtest/__init__.py",
                "- app/src/bist_factor_backtest/config.py",
                "- app/src/bist_factor_backtest/dashboard/*",
                "- data/dashboard/*",
                "- run_dashboard.py",
                "- requirements-dashboard.txt",
                "- trex-dashboard.service.example",
                "",
            ]
        ),
        encoding="utf-8",
    )

    archive = ROOT / "dist" / "dashboard_vps_bundle.tar.gz"
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        archive.unlink()
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(OUTPUT, arcname="dashboard_vps_bundle")
    return OUTPUT, archive


if __name__ == "__main__":
    bundle_dir, archive_path = build_bundle()
    print(bundle_dir)
    print(archive_path)
