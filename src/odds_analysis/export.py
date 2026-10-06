"""Exports for the iPad: one row per match x market x selection with prices, probabilities and the result.

exports/daily/YYYY-MM-DD.xlsx       per match date (last N days kept in git; older ones can be rebuilt)
exports/monthly/YYYY-MM.csv.gz      full history by month
exports/all_settled.csv.gz          the newest months that fit under the 50 MB file limit
"""

from __future__ import annotations

import gzip
import io
import logging
from datetime import date as Date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .config import DATA, EXPORTS, TR, load, now_utc
from .settle import card_points
from .storage import read_partition

log = logging.getLogger(__name__)

MAX_ALL_BYTES = 45 * 1024 * 1024
# markets whose selections are mutually exclusive except DC-type ones (2 winners); others get no fair_prob
FAIR_FAMILIES = {"score", "first_goal", "corners", "ht_corners", "cards", "corner_timing", "penalty"}
NOT_EXCLUSIVE = ("TEAM_", "PLAYER_", "MATCH_")  # several selections can win together
WINNERS_PER_MARKET = {"DC": 2, "HT_DC": 2}

COLUMNS = [
    "date", "kickoff_local", "kickoff_utc", "weekday", "league_code", "league", "match_id", "event_code",
    "home_team", "away_team", "mbs", "market_mbs", "market_id", "market_key", "family", "line", "market_tr", "selection",
    "selection_tr", "opening_odds", "opening_utc", "closing_odds", "closing_utc", "closing_min_before_ko",
    "closing_source", "odds_source", "odds_movement_pct", "implied_prob", "fair_prob", "market_margin",
    "hit", "hit_source", "hit_official", "hit_engine", "engine_only",
    "ht_home", "ht_away", "ft_home", "ft_away", "corners_home", "corners_away", "card_pts_home", "card_pts_away",
    "result_type",
]

NUMERIC = ["match_id", "mbs", "market_mbs", "line", "opening_odds", "closing_odds", "closing_min_before_ko",
           "hit_official", "hit_engine", "engine_only", "ht_home", "ht_away", "ft_home", "ft_away",
           "corners_home", "corners_away", "card_pts_home", "card_pts_away"]


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def price_table(odds: pd.DataFrame, snapshots: pd.DataFrame, kickoffs: dict[str, str]) -> pd.DataFrame:
    """Opening / closing per selection from change-only odds rows."""
    if odds.empty:
        return pd.DataFrame()
    o = odds.copy()
    o["ko"] = o["match_id"].map(kickoffs)
    o["odds_f"] = o["odds"].map(_f)
    if "snapshot_type" not in o:
        o["snapshot_type"] = "opening"
    if "source" not in o:
        o["source"] = "popup"
    key = ["event_code", "market_id", "selection_tr"]
    pre = o[(o["snapshot_type"] != "post_match") & (o["snapshot_utc"] < o["ko"].fillna("9999"))].sort_values("snapshot_utc")
    post = o[o["snapshot_type"] == "post_match"].sort_values("snapshot_utc")
    first = pre.groupby(key).first()
    last = pre.groupby(key).last()
    pm = post.groupby(key).last()
    idx = first.index.union(pm.index)
    out = pd.DataFrame(index=idx)
    out["opening_odds"] = first["odds_f"]
    out["opening_utc"] = first["snapshot_utc"]
    out["closing_odds"] = last["odds_f"]
    out["odds_source"] = last["source"]
    out["closing_source"] = np.where(out["closing_odds"].notna(), "snapshot", None)
    use_pm = out["closing_odds"].isna() & pm.reindex(idx)["odds_f"].notna()
    out.loc[use_pm, "closing_odds"] = pm.reindex(idx).loc[use_pm, "odds_f"]
    out.loc[use_pm, "closing_source"] = "post_match"
    out.loc[use_pm, "odds_source"] = "popup"
    # closing time = last successful fetch of that event before kickoff (unchanged prices are not re-stored)
    if not snapshots.empty:
        s = snapshots.copy()
        s["ko"] = s["match_id"].map(kickoffs)
        s = s[s["snapshot_utc"] < s["ko"].fillna("9999")]
        last_fetch = s.groupby("event_code")["snapshot_utc"].max()
        ev = out.index.get_level_values("event_code")
        out["closing_utc"] = np.where(out["closing_source"] == "snapshot", ev.map(last_fetch), None)
    else:
        out["closing_utc"] = None
    return out.reset_index()


def add_probabilities(df: pd.DataFrame) -> pd.DataFrame:
    """implied = 1/closing; fair = implied with the bookmaker margin removed proportionally per market."""
    price = df["closing_odds"].where(df["closing_odds"].notna(), df["opening_odds"])
    df["implied_prob"] = 1 / price
    df["odds_movement_pct"] = (df["closing_odds"] / df["opening_odds"] - 1) * 100
    exclusive = df["family"].isin(FAIR_FAMILIES) & ~df["market_key"].fillna("").str.startswith(NOT_EXCLUSIVE)
    grp = df.groupby(["match_id", "market_id"])["implied_prob"]
    total = grp.transform("sum")
    complete = grp.transform(lambda s: s.notna().all())
    winners = df["market_key"].map(WINNERS_PER_MARKET).fillna(1)
    overround = total / winners
    ok = exclusive & complete & (overround > 1)
    df["fair_prob"] = np.where(ok, df["implied_prob"] / overround, np.nan)
    df["market_margin"] = np.where(ok, overround - 1, np.nan)
    return df


def build_date(date: str) -> pd.DataFrame:
    settled = read_partition("settled", date)
    if settled.empty:
        return pd.DataFrame(columns=COLUMNS)
    results = read_partition("results", date)
    matches = read_partition("matches", date)
    odds = read_partition("odds", date)
    snaps = read_partition("snapshots", date)
    events = read_partition("events", date)
    rules = load("card_rules")

    meta = results.set_index("match_id")
    if not matches.empty:
        meta = meta.combine_first(matches.set_index("match_id")[[c for c in ("kickoff_local", "mbs", "league_code", "kickoff_utc")
                                                                     if c in matches]])
    kickoffs = meta["kickoff_utc"].dropna().to_dict()
    prices = price_table(odds, snaps, kickoffs)
    df = settled.merge(prices, on=["event_code", "market_id", "selection_tr"], how="left")
    mbs_by_sel = (odds.drop_duplicates(["event_code", "market_id"], keep="last").set_index(["event_code", "market_id"])["mbs"]
                  if not odds.empty and "mbs" in odds else pd.Series(dtype=str))
    df["market_mbs"] = [mbs_by_sel.get((e, m)) for e, m in zip(df["event_code"], df["market_id"])]

    card = {}
    if not events.empty:
        for mid, g in events.groupby("match_id"):
            (h, a), _ = card_points(g.to_dict("records"), rules)
            card[mid] = (h, a)
    for col in ("kickoff_local", "kickoff_utc", "league_code", "league", "home_team", "away_team", "mbs", "ht_home",
                "ht_away", "ft_home", "ft_away", "corners_home", "corners_away", "result_type"):
        df[col] = df["match_id"].map(meta[col]) if col in meta else None
    df["card_pts_home"] = df["match_id"].map(lambda m: card.get(m, (None, None))[0])
    df["card_pts_away"] = df["match_id"].map(lambda m: card.get(m, (None, None))[1])
    df["date"] = date
    df["weekday"] = Date.fromisoformat(date).strftime("%a")
    ko = pd.to_datetime(df["kickoff_utc"], utc=True, errors="coerce")
    cl = pd.to_datetime(df["closing_utc"], utc=True, errors="coerce")
    df["closing_min_before_ko"] = ((ko - cl).dt.total_seconds() / 60).round()
    df = add_probabilities(df)
    for c in ("implied_prob", "fair_prob", "market_margin"):
        df[c] = df[c].round(4)
    df["odds_movement_pct"] = df["odds_movement_pct"].round(2)
    for c in NUMERIC:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["hit"] = [h if h == "void" else (int(h) if str(h) in ("0", "1") else None) for h in df["hit"]]
    return df.reindex(columns=COLUMNS).sort_values(["kickoff_utc", "match_id", "market_key", "selection"], kind="stable")


def _gz_csv(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        gz.write(df.to_csv(index=False, lineterminator="\n").encode("utf-8"))
    return buf.getvalue()


def _write_if_changed(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_bytes() != data:
        path.write_bytes(data)


def write_xlsx(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    matches = (df.drop_duplicates("match_id")[["date", "kickoff_local", "league_code", "league", "home_team", "away_team",
                                               "mbs", "ht_home", "ht_away", "ft_home", "ft_away", "corners_home",
                                               "corners_away", "card_pts_home", "card_pts_away", "result_type"]])
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        df.to_excel(xw, sheet_name="selections", index=False, freeze_panes=(1, 0))
        matches.to_excel(xw, sheet_name="matches", index=False, freeze_panes=(1, 0))
        for ws in xw.book.worksheets:
            ws.auto_filter.ref = ws.dimensions


def export(dates: list[str], keep_daily_days: int = 60) -> dict:
    stats = {"dates": [], "rows": 0}
    months: set[str] = set()
    for d in dates:
        df = build_date(d)
        if df.empty:
            continue
        stats["dates"].append(d)
        stats["rows"] += len(df)
        write_xlsx(df, EXPORTS / "daily" / f"{d}.xlsx")
        months.add(d[:7])
    settled_dir = DATA / "settled"
    for month in sorted(months):
        days = sorted(p.name[:10] for p in settled_dir.glob(f"{month}-*.csv.gz"))
        frames = [build_date(d) for d in days]
        frames = [f for f in frames if not f.empty]
        if frames:
            _write_if_changed(EXPORTS / "monthly" / f"{month}.csv.gz", _gz_csv(pd.concat(frames, ignore_index=True)))
    stats["all_settled_months"] = rebuild_all()
    cutoff = (now_utc().astimezone(TR).date() - timedelta(days=keep_daily_days)).isoformat()
    for p in (EXPORTS / "daily").glob("*.xlsx"):
        if p.name[:10] < cutoff:
            p.unlink()
    return stats


def rebuild_all() -> list[str]:
    """exports/all_settled.csv.gz = newest monthly files that fit under the size limit."""
    monthly = sorted((EXPORTS / "monthly").glob("*.csv.gz"), reverse=True)
    chosen, size = [], 0
    for p in monthly:
        s = p.stat().st_size
        if chosen and size + s > MAX_ALL_BYTES:
            break
        chosen.append(p)
        size += s
    if not chosen:
        return []
    frames = [pd.read_csv(p, dtype=str, keep_default_na=False) for p in reversed(chosen)]
    _write_if_changed(EXPORTS / "all_settled.csv.gz", _gz_csv(pd.concat(frames, ignore_index=True)))
    return [p.name[:7] for p in reversed(chosen)]
