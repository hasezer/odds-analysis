"""analysis_flat (derived, rebuilt automatically, never edited by hand) and its exports.

One row per match x market x selection that Nesine offered (selections without a price included), with scores,
corner/card totals, closing and opening odds, implied/fair probability, market margin, hit and status.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import store
from .catalog import OVERLAP
from .config import DATA, ROOT

EXPORTS = ROOT / "exports"
MARKET = ["match_id", "market_type_id", "line", "handicap_home", "handicap_away"]
SELECTION = MARKET + ["selection_key"]
NO_MARGIN_FAMILIES = {"player", "special"}  # selections are separate yes-bets, not one market summing to 100 %
EXCLUDED_FAMILIES = {"cards"}  # Kart Puanı rule not confirmed yet (SCHEMA.md); flip when it is


def _key_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Join keys with NULLs (line, handicap) made comparable."""
    out = df.copy()
    for c in ("line", "handicap_home", "handicap_away"):
        out[c] = out[c].astype("object").where(out[c].notna(), None)
    return out


def build(season: str, league_id: str, root: Path = DATA) -> pd.DataFrame:
    matches = store.read("matches", season=season, league_id=league_id, root=root)
    odds = store.read("odds", season=season, league_id=league_id, root=root)
    if matches.empty or odds.empty:
        return pd.DataFrame()
    sets = store.read("settlements", season=season, league_id=league_id, root=root)
    stats = store.read("stats", season=season, league_id=league_id, root=root)
    teams = store.read("teams", root=root)
    markets = store.read("markets", root=root)

    odds = _key_frame(odds)
    sel = odds.sort_values("price_type").drop_duplicates(SELECTION)[SELECTION + ["market_key", "selection_name_tr"]]

    def price(kind: str, first: bool = False) -> pd.DataFrame:
        o = odds[odds["price_type"] == kind].sort_values("captured_at_utc", na_position="first")
        o = o.drop_duplicates(SELECTION, keep="first" if first else "last")
        return o[SELECTION + ["odds"]]

    snap_close, hist_close = price("closing_snapshot"), price("closing_history")
    opening = price("opening_snapshot", first=True).rename(columns={"odds": "opening_odds"})
    df = sel.merge(snap_close.rename(columns={"odds": "_cs"}), on=SELECTION, how="left")
    df = df.merge(hist_close.rename(columns={"odds": "_ch"}), on=SELECTION, how="left")
    df["closing_odds"] = df["_cs"].where(df["_cs"].notna(), df["_ch"])
    df["closing_source"] = pd.Series(pd.NA, index=df.index, dtype="object")
    df.loc[df["_ch"].notna(), "closing_source"] = "closing_history"
    df.loc[df["_cs"].notna(), "closing_source"] = "closing_snapshot"
    df = df.drop(columns=["_cs", "_ch"]).merge(opening, on=SELECTION, how="left")
    df["odds_movement_pct"] = (df["closing_odds"] / df["opening_odds"] - 1) * 100

    mk = markets[["market_type_id", "name_tr", "family"]].rename(columns={"name_tr": "market_name_tr"})
    df = df.merge(mk, on="market_type_id", how="left")
    df["implied_prob"] = 1 / df["closing_odds"]
    grp = df.groupby(MARKET, dropna=False)
    complete = grp["closing_odds"].transform(lambda s: s.notna().all())
    total = grp["implied_prob"].transform("sum") / df["market_key"].map(OVERLAP).fillna(1)
    ok = complete & ~df["family"].isin(NO_MARGIN_FAMILIES)
    df["market_margin"] = (total - 1).where(ok)
    df["fair_prob"] = (df["implied_prob"] / total).where(ok)

    if not sets.empty:
        s = _key_frame(sets)[SELECTION + ["hit", "status"]]
        df = df.merge(s, on=SELECTION, how="left")
    else:
        df["hit"], df["status"] = pd.NA, pd.NA

    m = matches[["match_id", "league_id", "season", "season_type", "kickoff_utc", "home_team_id", "away_team_id",
                 "ht_home", "ht_away", "ft_home", "ft_away"]]
    df = df.merge(m, on="match_id", how="inner")
    names = teams.set_index("team_id")["name_tr"] if not teams.empty else pd.Series(dtype="object")
    df["home_team_tr"] = df["home_team_id"].map(names)
    df["away_team_tr"] = df["away_team_id"].map(names)
    if not stats.empty:
        tot = stats.groupby("match_id")[["corners", "yellow_cards", "red_cards"]].sum(min_count=2)
        tot.columns = ["corners_total", "yellow_cards_total", "red_cards_total"]
        df = df.merge(tot, left_on="match_id", right_index=True, how="left")
    df["in_default_analysis"] = ((df["season_type"] != "special") & ~df["family"].isin(EXCLUDED_FAMILIES)
                                 & df["status"].isin(["settled"]).fillna(False))
    df = df.sort_values(SELECTION, kind="stable").reset_index(drop=True)
    return df


def rebuild(season: str, league_id: str, root: Path = DATA) -> int:
    df = build(season, league_id, root)
    if df.empty:
        return 0
    flat_dir = store.partition_dir(store.TABLES["analysis_flat"], season, league_id, root=root)
    for f in flat_dir.glob("part-*.parquet"):  # derived: replaced, never merged
        f.unlink()
    return store.upsert("analysis_flat", df, root=root)


def export(season: str, league_ids: list[str], root: Path = DATA, out: Path = EXPORTS) -> list[Path]:
    """exports/analysis_flat/<season>.csv.gz and exports/analysis_flat/<season>.xlsx (one sheet per league)."""
    frames = [store.read("analysis_flat", season=season, league_id=lid, root=root) for lid in league_ids]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return []
    df = pd.concat(frames, ignore_index=True).drop(columns=["schema_version", "ingested_at_utc"])
    for c in df.columns:
        if isinstance(df[c].dtype, pd.DatetimeTZDtype):
            df[c] = df[c].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    d = out / "analysis_flat"
    d.mkdir(parents=True, exist_ok=True)
    name = store.season_path(season)
    csv = d / f"{name}.csv.gz"
    df.to_csv(csv, index=False, compression={"method": "gzip", "mtime": 0}, lineterminator="\n")
    xlsx = d / f"{name}.xlsx"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as w:
        for lid, part in df.groupby("league_id", sort=True):
            part.to_excel(w, sheet_name=lid, index=False)
    return [csv, xlsx]
