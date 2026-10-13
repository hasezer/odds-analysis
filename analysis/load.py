"""Shared loader for analysis: only seasons whose backfill is complete."""
from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parents[1] / "data"

# Complete seasons (README backfill table, 2026-10-13). 2026/27 and 2026 are in progress (finished matches only).
SEASONS = ["2024-25", "2025-26", "2026-27", "2024", "2025", "2026"]


def _read(table: str, seasons=SEASONS) -> pd.DataFrame:
    frames = []
    for s in seasons:
        root = DATA / table / f"season={s}"
        if not root.exists():
            continue
        for f in sorted(root.glob("league=*/**/*.parquet")):
            df = pd.read_parquet(f)
            frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    # TUR-1 placeholder fixtures (empty entries, not real matches)
    return out[~out["match_id"].str.startswith("macko")].reset_index(drop=True)


def matches(seasons=SEASONS) -> pd.DataFrame:
    return _read("matches", seasons)


def flat(seasons=SEASONS) -> pd.DataFrame:
    return _read("analysis_flat", seasons)
