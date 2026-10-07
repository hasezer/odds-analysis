"""analysis_flat (derived, rebuilt automatically, never edited by hand) and its exports.

One row per match x market x selection that Nesine offered (selections without a price included), with scores,
corner/card totals, closing and opening odds, implied/fair probability, market margin, hit and status.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from . import store
from .catalog import OVERLAP, selected_markets
from .config import DATA, ROOT

EXPORTS = Path(os.environ.get("ODDS_EXPORTS_DIR", ROOT / "exports"))
MARKET = ["match_id", "market_type_id", "line", "handicap_home", "handicap_away"]
SELECTION = MARKET + ["selection_key"]
NO_MARGIN_FAMILIES = {"player", "special"}  # selections are separate yes-bets, not one market summing to 100 %


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
    df["in_default_analysis"] = (df["season_type"] != "special") & df["status"].isin(["settled"]).fillna(False)
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
    """exports/<season>/<league_id>.csv.gz (analysis_flat, every row) and exports/<season>/oranlar_<season>.xlsx
    (one row per match, one sheet per league)."""
    d = out / store.season_path(season)
    d.mkdir(parents=True, exist_ok=True)
    paths, sheets = [], {}
    for lid in league_ids:
        df = store.read("analysis_flat", season=season, league_id=lid, root=root)
        if df.empty:
            continue
        csv = df.drop(columns=["schema_version", "ingested_at_utc"])
        for c in csv.columns:
            if isinstance(csv[c].dtype, pd.DatetimeTZDtype):
                csv[c] = csv[c].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        path = d / f"{lid}.csv.gz"
        csv.to_csv(path, index=False, compression={"method": "gzip", "mtime": 0}, lineterminator="\n")
        paths.append(path)
        view = match_view(df)
        if not view[0].empty:  # a league without finished matches yet gets no sheet
            sheets[lid] = view
    if sheets:
        xlsx = d / f"oranlar_{store.season_path(season)}.xlsx"
        write_view(sheets, xlsx)
        paths.append(xlsx)
    return paths


# ---------------------------------------------------------------- one row per match (the iPad view)

_RANK = {"1": 0, "X": 1, "2": 2, "1X": 0, "12": 1, "X2": 2, "UNDER": 0, "OVER": 1, "YES": 0, "NO": 1}


def _sel_order(key: str) -> tuple:
    """Column order inside a market: 1 X 2, Alt Üst, Var Yok, 1/1 ... 2/2, scores by goals, 'Diğer' last."""
    if key == "OTHER":
        return (99,)
    if key in _RANK:
        return (_RANK[key],)
    for sep in ("&", "/"):
        if sep in key:
            return tuple(x for part in key.split(sep) for x in _sel_order(part))
    nums = [int(x) for x in key.replace("+", "-").split("-") if x.isdigit()]
    if nums:
        return (0, *nums, 1 if key.endswith("+") else 0)
    return (50, key)


def match_view(flat: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """analysis_flat of one league-season -> (view, hits): one row per match, columns = closing odds of the markets
    in config/markets.yaml (in that order); hits has the same shape (True = winning selection)."""
    labels = {(m["key"], m.get("line")): m["label"] for m in selected_markets()}
    order = {(m["key"], m.get("line")): i for i, m in enumerate(selected_markets())}
    f = flat.copy()
    f["_mk"] = list(zip(f["market_key"], f["line"].astype("object").where(f["line"].notna(), None), strict=True))
    f = f[f["_mk"].isin(labels.keys())]
    f["_col"] = [f"{labels[mk]} {name if isinstance(name, str) else key}"
                 for mk, name, key in zip(f["_mk"], f["selection_name_tr"], f["selection_key"], strict=True)]
    ranked = {c: (order[mk], *_sel_order(k)) for mk, k, c in zip(f["_mk"], f["selection_key"], f["_col"], strict=True)}
    cols = sorted(ranked, key=lambda c: (ranked[c], c))
    odds = f.pivot_table(index="match_id", columns="_col", values="closing_odds", aggfunc="first")
    hits = f.assign(hit=f["hit"].astype("object")).pivot_table(index="match_id", columns="_col", values="hit",
                                                               aggfunc="first")
    m = f.drop_duplicates("match_id").set_index("match_id").sort_values("kickoff_utc")
    tr = m["kickoff_utc"].dt.tz_convert("Europe/Istanbul")

    def score(a, b):
        return [f"{x}-{y}" if pd.notna(x) else None for x, y in zip(a, b, strict=True)]

    view = pd.DataFrame({
        "Tarih": tr.dt.strftime("%d.%m.%Y"), "Saat": tr.dt.strftime("%H:%M"),
        "Ev Sahibi": m["home_team_tr"], "Deplasman": m["away_team_tr"],
        "İY": score(m["ht_home"], m["ht_away"]), "MS": score(m["ft_home"], m["ft_away"]),
        "Korner": m["corners_total"] if "corners_total" in m else None,
        "Sarı Kart": m["yellow_cards_total"] if "yellow_cards_total" in m else None,
        "Kırmızı Kart": m["red_cards_total"] if "red_cards_total" in m else None,
    }, index=m.index).join(odds.reindex(columns=cols))
    keep = odds.reindex(index=m.index, columns=cols).notna().any(axis=1).to_numpy()  # matches with closing odds only
    return (view[keep].reset_index(drop=True),
            hits.reindex(index=m.index, columns=cols)[keep].reset_index(drop=True))


def write_view(sheets: dict[str, tuple[pd.DataFrame, pd.DataFrame]], path: Path) -> None:
    """One sheet per league; header bold, first 4 columns frozen, winning odds filled green."""
    from openpyxl.styles import Font, PatternFill

    green = PatternFill("solid", fgColor="C6EFCE")
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        for name, (view, hits) in sheets.items():
            view.to_excel(w, sheet_name=name, index=False, freeze_panes=(1, 4))
            ws = w.sheets[name]
            for cell in ws[1]:
                cell.font = Font(bold=True)
            first = len(view.columns) - len(hits.columns) + 1
            for r, row in enumerate(hits.itertuples(index=False), start=2):
                for c, hit in enumerate(row, start=first):
                    if pd.notna(hit) and bool(hit):
                        ws.cell(row=r, column=c).fill = green
