"""Parquet storage for the SCHEMA.md tables.

data/<table>/part-0000.parquet                                        (single)
data/<table>/season=<2024-25>/league=<TUR-1>/part-0000.parquet          (history)
data/odds/season=<..>/league=<..>/date=<YYYY-MM-DD>/part-0000.parquet  (our own snapshots, by capture date)

Writes validate every row against schema.py (types, NOT NULL, allowed values, no "-" or "" for missing values),
merge with what is stored (the key decides; an unchanged row keeps its first ingested_at_utc so git sees no
change), sort by key, compress with zstd and split files so none exceeds 50 MB.
"""

from __future__ import annotations

import io
import math
from collections.abc import Iterable
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .config import DATA
from .schema import SCHEMA_VERSION, SNAPSHOT_PRICE_TYPES, TABLES, Table, season_path

MAX_FILE_BYTES = 50 * 1024 * 1024
ODDS_COLUMNS = {"odds", "closing_odds", "opening_odds"}  # stored with 2 decimals
ARROW = {"string": pa.string(), "int": pa.int64(), "float": pa.float64(), "bool": pa.bool_(),
         "ts": pa.timestamp("s", tz="UTC"), "list": pa.list_(pa.string())}
PANDAS = {pa.int64(): pd.Int64Dtype(), pa.float64(): pd.Float64Dtype(), pa.bool_(): pd.BooleanDtype(),
          pa.string(): pd.StringDtype()}
PARTITION_COLUMNS = ("season", "league_id")


class SchemaError(ValueError):
    pass


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


# ---------------------------------------------------------------- values

def _missing(v) -> bool:
    if v is None or v is pd.NA or v is pd.NaT:
        return True
    return isinstance(v, float) and math.isnan(v)


def _ts(v) -> datetime:
    if isinstance(v, pd.Timestamp):
        v = v.to_pydatetime()
    if isinstance(v, datetime):
        if v.tzinfo is None:
            raise SchemaError(f"timestamp without time zone: {v!r} (store UTC)")
        return v.astimezone(timezone.utc).replace(microsecond=0)
    if isinstance(v, str):
        return _ts(datetime.fromisoformat(v.replace("Z", "+00:00")))
    raise SchemaError(f"not a timestamp: {v!r}")


def _value(col, v):
    if _missing(v):
        return None
    t = col.type
    if t == "string":
        if not isinstance(v, str):
            v = str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)  # ids are strings
        if v.strip() in ("", "-"):
            raise SchemaError(f"{col.name}: {v!r} - missing values must be NULL")
        if col.enum and v not in col.enum:
            raise SchemaError(f"{col.name}: {v!r} not in {col.enum}")
        return v
    if t == "int":
        if isinstance(v, str):
            if v.strip() in ("", "-"):
                raise SchemaError(f"{col.name}: {v!r} - missing values must be NULL")
            v = float(v.replace(",", "."))
        if float(v) != int(float(v)):
            raise SchemaError(f"{col.name}: {v!r} is not a whole number")
        return int(float(v))
    if t == "float":
        if isinstance(v, str):
            if v.strip() in ("", "-"):
                raise SchemaError(f"{col.name}: {v!r} - missing values must be NULL")
            v = v.replace(",", ".")
        v = float(v)
        return round(v, 2) if col.name in ODDS_COLUMNS else v
    if t == "bool":
        if isinstance(v, str):
            if v not in ("true", "false", "1", "0"):
                raise SchemaError(f"{col.name}: {v!r} is not a boolean")
            return v in ("true", "1")
        return bool(v)
    if t == "ts":
        return _ts(v)
    if t == "list":
        return [str(x) for x in v]
    raise SchemaError(f"unknown type {t}")


def arrow_schema(table: Table) -> pa.Schema:
    return pa.schema([pa.field(c.name, ARROW[c.type], nullable=not c.required) for c in table.all_columns])


def to_arrow(table: Table, rows: pd.DataFrame | list[dict], *, ingested_at: datetime | None = None) -> pa.Table:
    """Validate rows and build an Arrow table with exactly the schema's columns (extra columns are dropped)."""
    df = pd.DataFrame(rows) if isinstance(rows, list) else rows
    stamp = ingested_at or now_utc()
    n = len(df)
    arrays, fields = [], []
    for col in table.all_columns:
        if col.name in df:
            raw = df[col.name].tolist()
        elif col.name == "schema_version":
            raw = [SCHEMA_VERSION] * n
        elif col.name == "ingested_at_utc":
            raw = [stamp] * n
        elif col.required:
            raise SchemaError(f"{table.name}: column {col.name} is required")
        else:
            raw = [None] * n
        if col.name == "ingested_at_utc":
            raw = [stamp if _missing(v) else v for v in raw]
        try:
            vals = [_value(col, v) for v in raw]
        except SchemaError as exc:
            raise SchemaError(f"{table.name}.{exc}") from None
        if col.required and any(v is None for v in vals):
            raise SchemaError(f"{table.name}.{col.name} is NOT NULL but has {sum(v is None for v in vals)} NULL(s)")
        arrays.append(pa.array(vals, type=ARROW[col.type]))
        fields.append(pa.field(col.name, ARROW[col.type], nullable=not col.required))
    return pa.Table.from_arrays(arrays, schema=pa.schema(fields))


def to_pandas(t: pa.Table) -> pd.DataFrame:
    return t.to_pandas(types_mapper=PANDAS.get)


# ---------------------------------------------------------------- layout

def partition_dir(table: Table, season: str | None = None, league_id: str | None = None, day: str | None = None,
                  root: Path = DATA) -> Path:
    base = root / table.name
    if table.partition == "single":
        return base
    if not season or not league_id:
        raise SchemaError(f"{table.name}: season and league_id are needed to place the rows")
    d = base / f"season={season_path(season)}" / f"league={league_id}"
    return d / f"date={day}" if day else d


def _groups(table: Table, df: pd.DataFrame, root: Path) -> Iterable[tuple[Path, pd.DataFrame]]:
    if table.partition == "single":
        yield partition_dir(table, root=root), df
        return
    missing = [c for c in PARTITION_COLUMNS if c not in df]
    if missing:
        raise SchemaError(f"{table.name}: rows need {missing} to choose the partition")
    day = None
    if table.partition == "snapshot":
        snap = df["price_type"].isin(SNAPSHOT_PRICE_TYPES)
        captured = df["captured_at_utc"] if "captured_at_utc" in df else [None] * len(df)
        day = [(_ts(t).date().isoformat() if s else "") for t, s in zip(captured, snap, strict=True)]
    keys = pd.DataFrame({"season": df["season"], "league_id": df["league_id"], "day": day or [""] * len(df)})
    for (season, league, d), idx in keys.groupby(["season", "league_id", "day"], sort=True).groups.items():
        yield partition_dir(table, season, league, d or None, root), df.loc[idx]


def _hashable(df: pd.DataFrame) -> pd.DataFrame:
    """List columns (teams.aliases) -> joined strings so rows can be compared."""
    out = df.copy()
    seq = (list, tuple, np.ndarray)
    for c in out.columns:
        if out[c].map(lambda v: isinstance(v, seq)).any():
            out[c] = out[c].map(lambda v: "\x1f".join(map(str, v)) if isinstance(v, seq) else v)
    return out


def _read_dir(d: Path) -> pa.Table | None:
    files = sorted(d.glob("part-*.parquet"))
    if not files:
        return None
    return pa.concat_tables([_read_file(f) for f in files])


def _read_file(f: Path, columns: list[str] | None = None) -> pa.Table:
    """One file as written (no column guessing from the season=/league= folder names)."""
    return pq.ParquetFile(f).read(columns=columns)


def _write_dir(table: Table, d: Path, t: pa.Table) -> None:
    d.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    pq.write_table(t, buf, compression="zstd")
    parts = max(1, math.ceil(buf.tell() / (MAX_FILE_BYTES * 0.9)))
    rows_per = math.ceil(t.num_rows / parts) if t.num_rows else 0
    wanted = []
    for i in range(parts):
        path = d / f"part-{i:04d}.parquet"
        piece = t.slice(i * rows_per, rows_per) if parts > 1 else t
        out = io.BytesIO()
        pq.write_table(piece, out, compression="zstd")
        data = out.getvalue()
        if len(data) > MAX_FILE_BYTES:
            raise RuntimeError(f"{path}: {len(data) / 1e6:.1f} MB > 50 MB after splitting")
        if not path.exists() or path.read_bytes() != data:  # unchanged data -> no git change
            path.write_bytes(data)
        wanted.append(path)
    for old in d.glob("part-*.parquet"):
        if old not in wanted:
            old.unlink()


def upsert(name: str, rows: pd.DataFrame | list[dict], *, root: Path = DATA, ingested_at: datetime | None = None) -> int:
    """Validate and merge rows into the table (later rows win per key). Returns the number of rows given.

    Rows of partitioned tables carry `season` and `league_id` (used for the folder; dropped if the table has no
    such column)."""
    table = TABLES[name]
    df = pd.DataFrame(rows) if isinstance(rows, list) else rows.copy()
    if df.empty:
        return 0
    stamp = ingested_at or now_utc()
    data_cols = [c.name for c in table.columns]
    for d, part in _groups(table, df.reset_index(drop=True), root):
        new = to_pandas(to_arrow(table, part, ingested_at=stamp))
        old_t = _read_dir(d)
        if old_t is not None:
            old = to_pandas(old_t.cast(arrow_schema(table)))
            both = pd.concat([old, new], ignore_index=True)
            h = _hashable(both)
            both = both.loc[~h.duplicated(subset=data_cols, keep="first")]  # unchanged row: keep the old one
            h = _hashable(both)
            both = both.loc[~h.duplicated(subset=list(table.key), keep="last")]  # changed row: new one wins
        else:
            h = _hashable(new)
            both = new.loc[~h.duplicated(subset=list(table.key), keep="last")]
        both = both.sort_values(list(table.key), kind="stable", na_position="first").reset_index(drop=True)
        _write_dir(table, d, to_arrow(table, both))
    return len(df)


def read(name: str, *, season: str | None = None, league_id: str | None = None, root: Path = DATA,
         columns: list[str] | None = None) -> pd.DataFrame:
    """Read a table (optionally one season/league). Partitioned tables get `season`/`league_id` from the path
    when the table has no such column."""
    table = TABLES[name]
    base = root / name
    if not base.exists():
        return pd.DataFrame(columns=[c.name for c in table.all_columns])
    pattern = "part-*.parquet" if table.partition == "single" else \
        f"season={season_path(season) if season else '*'}/league={league_id or '*'}/**/part-*.parquet"
    frames = []
    for f in sorted(base.glob(pattern)):
        df = to_pandas(_read_file(f, columns))
        if table.partition != "single":
            parts = dict(p.split("=", 1) for p in f.relative_to(base).parts[:-1] if "=" in p)
            for col, key in (("season", "season"), ("league_id", "league")):
                if col not in df.columns:
                    df[col] = _season_from_path(parts[key]) if col == "season" else parts[key]
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=[c.name for c in table.all_columns])
    return pd.concat(frames, ignore_index=True)


def _season_from_path(s: str) -> str:
    return s.replace("-", "/") if "-" in s else s


def as_date(v) -> date:
    return _ts(v).date()
