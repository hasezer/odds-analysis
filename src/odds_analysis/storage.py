"""Daily partitioned CSV.gz tables under data/<table>/YYYY-MM-DD.csv.gz plus small append-only logs.

Writes are deterministic (gzip mtime=0, stable sort) so unchanged data produces no git diff.
"""

from __future__ import annotations

import csv
import gzip
import io
from pathlib import Path
from typing import Iterable

import pandas as pd

from .config import DATA

MAX_FILE_BYTES = 50 * 1024 * 1024

# Primary keys per table: later writes win on the same key.
KEYS: dict[str, list[str]] = {
    "matches": ["match_id"],
    "odds": ["event_code", "market_id", "selection_tr", "snapshot_utc"],
    "snapshots": ["snapshot_utc", "event_code"],
    "results": ["match_id"],
    "events": ["match_id", "seq"],
    "stats": ["match_id", "source", "stat"],
    "official": ["event_code", "market_id", "selection_tr"],
    "settled": ["match_id", "market_id", "selection_tr"],
}


def partition_path(table: str, date: str, root: Path = DATA) -> Path:
    return root / table / f"{date}.csv.gz"


def read_partition(table: str, date: str, root: Path = DATA) -> pd.DataFrame:
    path = partition_path(table, date, root)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])


def read_table(table: str, dates: Iterable[str] | None = None, root: Path = DATA) -> pd.DataFrame:
    folder = root / table
    if not folder.exists():
        return pd.DataFrame()
    paths = sorted(folder.glob("*.csv.gz"))
    if dates is not None:
        wanted = set(dates)
        paths = [p for p in paths if p.name[:10] in wanted]
    frames = [pd.read_csv(p, dtype=str, keep_default_na=False, na_values=[""]) for p in paths]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def write_partition(table: str, date: str, df: pd.DataFrame, root: Path = DATA) -> Path:
    path = partition_path(table, date, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        gz.write(df.to_csv(index=False, lineterminator="\n").encode("utf-8"))
    data = buf.getvalue()
    if len(data) > MAX_FILE_BYTES:
        raise RuntimeError(f"{path} would be {len(data) / 1e6:.1f} MB (> 50 MB limit)")
    if not path.exists() or path.read_bytes() != data:
        path.write_bytes(data)
    return path


def upsert_partition(table: str, date: str, new: pd.DataFrame, root: Path = DATA) -> int:
    """Merge rows into a partition (later rows win per primary key). Returns rows added/changed."""
    if new.empty:
        return 0
    keys = KEYS[table]
    new = new.astype(object).map(_cell)
    old = read_partition(table, date, root)
    if not old.empty:
        old = old.fillna("")
        merged = pd.concat([old, new], ignore_index=True)
        cols = list(dict.fromkeys(list(old.columns) + list(new.columns)))
    else:
        merged, cols = new, list(new.columns)
    merged = merged.reindex(columns=cols).fillna("")
    merged = merged.drop_duplicates(subset=keys, keep="last").sort_values(keys, kind="stable")
    write_partition(table, date, merged.reset_index(drop=True), root)
    return len(new)


def frame(rows: list[dict]) -> pd.DataFrame:
    """Rows -> object DataFrame (keeps ints as ints; avoids 1 -> 1.0 when a column has gaps)."""
    return pd.DataFrame(rows, dtype=object)


def _cell(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    return str(v)


def append_log(name: str, rows: list[dict], root: Path = DATA) -> None:
    """Append rows to data/<name>.csv (small human-readable logs)."""
    if not rows:
        return
    path = root / f"{name}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys())
    exists = path.exists() and path.stat().st_size > 0
    if exists:
        with path.open(encoding="utf-8", newline="") as f:
            header = next(csv.reader(f), [])
        fields = header + [k for r in rows for k in r if k not in header]
        fields = list(dict.fromkeys(fields))
        if fields != header:  # new columns: rewrite with the wider header
            old = pd.read_csv(path, dtype=str, keep_default_na=False)
            old = pd.concat([old, pd.DataFrame(rows)], ignore_index=True).reindex(columns=fields)
            old.to_csv(path, index=False, lineterminator="\n")
            return
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        if not exists:
            w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def read_log(name: str, root: Path = DATA) -> pd.DataFrame:
    path = root / f"{name}.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def write_log_frame(name: str, df: pd.DataFrame, root: Path = DATA) -> None:
    """Replace data/<name>.csv with a derived table (e.g. mismatches rebuilt from settled data)."""
    path = root / f"{name}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, lineterminator="\n")
