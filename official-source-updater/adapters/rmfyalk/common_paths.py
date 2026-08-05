from __future__ import annotations

import os
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPT_PACKAGE_DIR = SCRIPT_DIR.parent


def _project_root() -> Path:
    configured = os.environ.get("RMCAL_PROJECT_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if SCRIPT_PACKAGE_DIR.name == "脚本":
        return SCRIPT_PACKAGE_DIR.parent
    return SCRIPT_PACKAGE_DIR


PROJECT_ROOT = _project_root()
CONFIG_DIR = Path(os.environ.get("RMCAL_CONFIG_DIR", SCRIPT_PACKAGE_DIR / "config")).expanduser().resolve()
DATA_DIR = Path(os.environ.get("RMCAL_DATA_DIR", PROJECT_ROOT / "data")).expanduser().resolve()
REPORT_DIR = Path(os.environ.get("RMCAL_REPORT_DIR", PROJECT_ROOT / "reports")).expanduser().resolve()
CLEAN_DIR = Path(os.environ.get("RMCAL_CLEAN_DIR", PROJECT_ROOT / "整理")).expanduser().resolve()


def latest_official_index() -> Path:
    files = sorted(DATA_DIR.glob("official_index_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise SystemExit(f"未找到官方索引 CSV：{DATA_DIR / 'official_index_*.csv'}")
    return files[0]
