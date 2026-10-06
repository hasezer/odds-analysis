"""Paths, timezones and YAML config."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("ODDS_DATA_DIR", ROOT / "data"))
CONFIG = ROOT / "config"
EXPORTS = Path(os.environ.get("ODDS_EXPORTS_DIR", ROOT / "exports"))
REPORTS = Path(os.environ.get("ODDS_REPORTS_DIR", ROOT / "reports"))

TR = timezone(timedelta(hours=3))  # Turkey has no DST since 2016
UTC = timezone.utc


@lru_cache
def load(name: str) -> dict:
    return yaml.safe_load((CONFIG / f"{name}.yaml").read_text(encoding="utf-8")) or {}


def now_utc() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def kickoff_utc(date_iso: str, hhmm: str) -> datetime:
    """Mackolik list date (Turkey) + 'HH:MM' (Turkey) -> aware UTC datetime."""
    local = datetime.fromisoformat(f"{date_iso}T{hhmm}:00").replace(tzinfo=TR)
    return local.astimezone(UTC)
