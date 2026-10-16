"""Live tracker: how does every strategy of the book do on matches played AFTER it was added?

Each strategy is replayed exactly as stored in analysis/strategies.yaml on every finished match from the day after
its `first_added` date, at the closing odds the project collected (data/ on main). Nothing needs to be logged in
advance, so no pick can be lost or edited afterwards. Retired strategies are tracked too (until they were retired).

python analysis/tracker.py  ->  analysis/output/tracker.md and analysis/output/tracker.xlsx
"""
from __future__ import annotations

import datetime as dt
from math import comb
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dashboard  # noqa: E402
import daily_scan as ds  # noqa: E402
import hi_data  # noqa: E402
import load  # noqa: E402
import miner_data as mdat  # noqa: E402
import ml_data as md  # noqa: E402

G = md
EXTRA = {  # combined bets of the high-odds study (same definitions as hi_data.py)
    "HT/FT comeback (1/2 or 2/1)": ((G.HT == "1") & (G.FT == "2")) | ((G.HT == "2") & (G.FT == "1")),
    "Draw with 4+ goals (2-2, 3-3 ...)": (G.FT == "X") & (G.T >= 4),
    "Total goals 6+ (any)": G.T >= 6,
    "Both teams score in both halves": (G.H1 > 0) & (G.A1 > 0) & (G.H2 > 0) & (G.A2 > 0),
    "Winner by 3+ goals": np.abs(G.HH - G.AA) >= 3,
    "Half-time draw, full-time not (X/1 or X/2)": (G.HT == "X") & (G.FT != "X"),
    "Home team scores 3+": G.HH >= 3,
    "Away team scores 3+": G.AA >= 3,
    "5+ goals and both score": (G.T >= 5) & (G.HH > 0) & (G.AA > 0),
    "2nd half has 3+ goals": G.T2 >= 3,
}


def outcome(key, idx, ok, keys):
    """1/0 per match for a bet key (selection label or combined bet), from the half-time and full-time score."""
    if key in EXTRA:
        mask = EXTRA[key]
    else:
        mk, line, sk = key.split("|")
        mask = md.predicate(mk, float(line) if line else None, sk, keys.get(mk, []))
        if mask is None:
            return np.full(len(idx), np.nan)
    return np.where(ok, mask[idx], np.nan)


def finished_since(start):
    m = load.matches()
    m = m[(m["status"] == "finished") & (m["kickoff_utc"] >= start) & m["ft_home"].notna() & m["ht_home"].notna()]
    f = load.flat()
    f = f[f["match_id"].isin(m["match_id"]) & f["closing_odds"].notna()]
    o = f.rename(columns={"closing_odds": "odds"})[["match_id", "market_type_id", "market_key", "line",
                                                     "selection_key", "odds"]]
    return m.reset_index(drop=True), o


def run():
    book = yaml.safe_load((HERE / "strategies.yaml").read_text())["strategies"]
    start = pd.Timestamp(min(s.get("first_added", "2026-10-14") for s in book), tz="UTC") + pd.Timedelta(days=1)
    m, o = finished_since(start)
    if not len(m):
        return pd.DataFrame(), pd.DataFrame(), start, pd.DataFrame()
    odds, fair = ds.live_tables(o)
    idx, ok = hi_data.cells(m)
    names = list(odds.columns)
    keys = {}
    for n in names:
        mk, _, sk = n.split("|")
        keys.setdefault(mk, []).append(sk)
    rows = []
    for s in book:
        if s["kind"] == "system":                      # whole coupons: replayed per weekend in system_coupons()
            continue
        since = pd.Timestamp(s.get("first_added", "2026-10-14"), tz="UTC") + pd.Timedelta(days=1)
        until = pd.Timestamp(s["retired_on"], tz="UTC") if s.get("retired_on") else None
        if s["kind"] == "pack":
            ys = {x: outcome(x, idx, ok, keys) for x in s["selections"]}
        else:
            y = outcome(s["bet"], idx, ok, keys)
        for i, r in enumerate(m.itertuples()):
            if r.kickoff_utc < since or (until is not None and r.kickoff_utc >= until) or r.match_id not in odds.index:
                continue
            orow, frow = odds.loc[r.match_id], fair.loc[r.match_id]
            k = s["kind"]
            if k == "pack":
                sel = [x for x in s["selections"] if pd.notna(frow.get(x, np.nan))]
                if len(sel) < s["k"]:
                    continue
                top = sorted(sel, key=lambda x: -frow[x])[:s["k"]]
                if sum(frow[x] for x in top) < s["min_pack_chance"]:
                    continue
                od = [orow.get(x, np.nan) for x in top]
                price = 1 / sum(1 / v for v in od) if all(pd.notna(v) for v in od) else np.nan
                hit = max(ys[x][i] for x in top)
                bet = f"pack: {', '.join(x.split('|')[-1] for x in top)}"
            else:
                if k == "league":
                    if r.league_id != s["league"]:
                        continue
                elif k == "league_rule":
                    if r.league_id != s["league"] or not ds.check(s["criteria"], orow, frow):
                        continue
                elif not ds.check(s["criteria"], orow, frow):
                    continue
                hit, price, bet = y[i], orow.get(s["bet"], np.nan), s["bet_name"]
            if np.isnan(hit):
                continue
            rows.append({"strategy": s["id"], "kind": k, "status": s["status"], "summary": s["summary"],
                         "kickoff": r.kickoff_utc.tz_convert("Europe/Istanbul").tz_localize(None),
                         "league": r.league_id, "match_id": r.match_id, "bet": bet,
                         "score": f"{int(r.ht_home)}-{int(r.ht_away)} / {int(r.ft_home)}-{int(r.ft_away)}",
                         "closing_odds": price, "hit": int(hit),
                         "return": hit * price - 1 if pd.notna(price) else np.nan,
                         "expected_hit_pct": list(s["evidence"].values())[-1].get("hit_pct")})
    picks = pd.DataFrame(rows)
    sysr = system_coupons(book, m, odds, idx, ok, keys)
    if not len(picks):
        return picks, pd.DataFrame(), start, sysr
    summ = picks.groupby(["strategy", "kind", "status", "summary"]).agg(
        picks=("hit", "size"), hits=("hit", "sum"), expected_hit_pct=("expected_hit_pct", "first"),
        priced=("return", "count"), returns=("return", "sum")).reset_index()
    summ["hit_pct"] = summ["hits"] / summ["picks"] * 100
    summ["return_per_100"] = summ["returns"] / summ["priced"].replace(0, np.nan) * 100
    return picks, summ, start, sysr


def system_coupons(book, m, odds, idx, ok, keys):
    """Replay each 'system' strategy (a whole coupon per weekend, e.g. the owner's 10-game 3-4-5 system) on every
    weekend that started after it was added, at closing odds: hits, stake and payout per system size."""
    rows = []
    if not len(m):
        return pd.DataFrame()
    w = [ds.window_of(t) for t in m["kickoff_utc"]]
    mm = m.assign(win=[x[0] for x in w], wkind=[x[1] for x in w], row=np.arange(len(m)))
    for s in [x for x in book if x["kind"] == "system"]:
        since = (pd.Timestamp(s.get("first_added", "2026-10-14")) + pd.Timedelta(days=1)).date()
        until = pd.Timestamp(s["retired_on"]).date() if s.get("retired_on") else None
        bets = sorted({b for g in s["groups"] for b in g["bets"]})
        ys = {b: outcome(b, idx, ok, keys) for b in bets}
        for win, g in mm[mm["wkind"] == s["window"]].groupby("win"):
            if win < since or (until is not None and win >= until):
                continue
            g = g[g["match_id"].isin(odds.index)]
            cands = odds.reindex(g["match_id"])
            cands["league"] = g.set_index("match_id")["league_id"]
            cands["kickoff"] = g.set_index("match_id")["kickoff_utc"]
            legs = ds.build_coupon(s, cands)
            if len(legs) < 3:
                continue
            r = g.set_index("match_id")["row"]
            hit = np.array([ys[b][r[mid]] for mid, b in zip(legs["match_id"], legs["bet"])], dtype=float)
            if np.isnan(hit).any():
                continue
            o = legs["odds"].to_numpy(float)
            e = ds.esym(o[hit == 1], max(s["sizes"]))
            n = len(o)
            stake = sum(comb(n, k) for k in s["sizes"])
            rows.append({"strategy": s["id"], "name": s.get("name", s["id"]), "status": s["status"],
                         "summary": s["summary"], "weekend": str(win),
                         "games": n, "hits": int(hit.sum()), "avg_odds": o.mean(),
                         "expected_hits": float(legs["chance"].sum()),
                         "system_stake": stake, "system_return": float(sum(e[k] for k in s["sizes"])),
                         "singles_stake": n, "singles_return": float((o * hit).sum())})
    return pd.DataFrame(rows)


def ret_txt(v):
    return f"return {v:+.1f} per 100" if pd.notna(v) else "no odds for this bet"


def system_lines(sysr):
    L = ["", "## Your 10-game system: one coupon per weekend since it was added", ""]
    if sysr is None or not len(sysr):
        return L + ["No complete weekend since the system coupons were added yet."]
    for sid, g in sysr.groupby("strategy", sort=False):
        sr = g["system_return"].sum() / g["system_stake"].sum() * 100 - 100
        si = g["singles_return"].sum() / g["singles_stake"].sum() * 100 - 100
        L.append(f"- **{g['name'].iloc[0]}** [{g['status'].iloc[0]}] — {len(g)} weekends, "
                 f"{int(g['hits'].sum())} of {int(g['games'].sum())} games won (expected {g['expected_hits'].sum():.1f}),"
                 f" 3+ hits in {int((g['hits'] >= 3).sum())} weekends; system 3-4-5 {sr:+.1f} per 100, singles "
                 f"{si:+.1f} per 100")
        for r in g.itertuples():
            L.append(f"  - {r.weekend}: {r.hits} of {r.games} won (odds ≈ {r.avg_odds:.1f}); system paid "
                     f"{r.system_return / r.system_stake:.2f}x the stake")
    return L


def write(picks, summ, start, sysr=None):
    out = HERE / "output" / "tracker.md"
    out.parent.mkdir(exist_ok=True)
    L = [f"# Strategy tracker — {dt.date.today():%d %b %Y}", "",
         f"Every strategy replayed, as stored, on matches played after it was added (from {start:%d %b %Y}), "
         "at the closing odds the project collected.", ""]
    if not len(picks):
        out.write_text("\n".join(L + ["No finished matches since the strategies were added yet."] + system_lines(sysr)))
        return out
    t = picks.copy()
    tot = lambda g: (f"{len(g)} picks, {g['hit'].sum()} won ({g['hit'].mean() * 100:.1f}%), "
                     f"return {g['return'].mean() * 100:+.1f} per 100 staked" if g['return'].notna().any() else "")
    L += [f"**All strategies:** {tot(t)} — {t['match_id'].nunique()} matches.", ""]
    L += ["| Kind | Picks | Won | Hit % | Expected hit % | Return per 100 |", "|---|---|---|---|---|---|"]
    for k, g in summ.groupby("kind"):
        exp = np.average(g["expected_hit_pct"].fillna(g["hit_pct"]), weights=g["picks"])
        ret = g["returns"].sum() / g["priced"].sum() * 100 if g["priced"].sum() else np.nan
        L.append(f"| {k} | {g['picks'].sum()} | {g['hits'].sum()} | {g['hits'].sum() / g['picks'].sum() * 100:.1f} | "
                 f"{exp:.1f} | {ret:+.1f} |" if pd.notna(ret) else f"{exp:.1f} | – |")
    L += ["", "## Promising and watch strategies", ""]
    for r in summ[summ["status"] != "proven"].sort_values("picks", ascending=False).itertuples():
        L.append(f"- **{r.summary}** — {r.picks} picks, {r.hits} won ({r.hit_pct:.1f}%, expected "
                 f"{r.expected_hit_pct}%), {ret_txt(r.return_per_100)}")
    L += ["", "## Proven strategies with the most picks", ""]
    for r in summ[summ["status"] == "proven"].sort_values("picks", ascending=False).head(25).itertuples():
        L.append(f"- {r.summary} — {r.picks} picks, {r.hit_pct:.1f}% won (expected {r.expected_hit_pct}%), "
                 f"{ret_txt(r.return_per_100)}")
    L += system_lines(sysr)
    L += ["", "Small samples swing a lot: judge a strategy after 100+ picks, a long-odds one after several hundred."]
    out.write_text("\n".join(L))
    with pd.ExcelWriter(out.with_suffix(".xlsx")) as xw:
        summ.round(2).to_excel(xw, sheet_name="By strategy", index=False)
        picks.round({"closing_odds": 2, "return": 3}).to_excel(xw, sheet_name="Every pick", index=False)
        if sysr is not None and len(sysr):
            sysr.round(3).to_excel(xw, sheet_name="System coupons", index=False)
    return out


if __name__ == "__main__":
    p, s, st, sy = run()
    print(write(p, s, st, sy), len(p), "picks,", len(sy), "system coupons")
