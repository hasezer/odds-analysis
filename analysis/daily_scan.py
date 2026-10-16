"""Daily scan: check every strategy of the strategy book against the upcoming fixtures of the 26 leagues.

python analysis/daily_scan.py --data-dir /tmp/scan/data --days 3
  reads   analysis/strategies.yaml (build_strategy_book.py), the upcoming matches and their latest Nesine odds
          from a data directory (a fresh snapshot, see daily_scan.sh), and the rule-book engine if its cache exists
  writes  analysis/output/daily_scan.md (highlights + every match) and analysis/output/daily_scan.xlsx
"""
from __future__ import annotations

import argparse
from math import comb
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dashboard  # noqa: E402
import miner_data as mdat  # noqa: E402
from htft_data import CACHE, EXPECTED_SIZE  # noqa: E402

RANK = {"promising": 0, "watch": 1, "proven": 2, "info": 3}
SYSTEM_DAYS = 5                     # the system coupon looks this far ahead, so a Friday scan sees the whole weekend
BET_TR = {"1X2_AND_OU|2.5|X&OVER": "MS X ve 2,5 Üst", "1X2_AND_OU|3.5|X&OVER": "MS X ve 3,5 Üst (same result)",
          "GOAL_RANGE||6+": "Toplam gol 6+"}
MARKET = {"CORRECT_SCORE": "Correct score", "HT_CORRECT_SCORE": "1st-half score", "HT_FT": "HT/FT"}


def strongest_only(out):
    """When the 5% and 10% band (or the 10% and 30% pack) of the same bet both fire, keep the stricter one."""
    if not len(out):
        return out
    tiered = out["kind"].isin(["odds_band", "pack"])
    t = out[tiered].copy()
    t["fam"] = t["id"].str.rsplit("-", n=1).str[0]
    t["share"] = t["id"].str.rsplit("-", n=1).str[1].astype(int)
    t = t.sort_values("share").drop_duplicates(["match", "kickoff", "fam"]).drop(columns=["fam", "share"])
    return pd.concat([out[~tiered], t], ignore_index=True)


def live_tables(o):
    """Odds and Nesine's chance per selection label. The chance is only computed for COMPLETE markets (all
    selections priced), exactly like the historical data (ml_data._fair); a partly listed market gets NaN."""
    o = dashboard.fair_probs(o)
    key = ["match_id", "market_key", "line"]
    n = o.groupby(key, dropna=False)["odds"].transform("count")
    need = o["market_key"].map(EXPECTED_SIZE).fillna(2)
    complete = (n == need) | o["market_key"].isin(["CORRECT_SCORE", "HT_CORRECT_SCORE"])
    o["fair"] = np.where(complete, o["fair"], np.nan)
    o["lab"] = [mdat.label(a, b, c) for a, b, c in zip(o["market_key"], o["line"], o["selection_key"])]
    odds = o.pivot_table(index="match_id", columns="lab", values="odds", aggfunc="last")
    fair = o.pivot_table(index="match_id", columns="lab", values="fair", aggfunc="last")
    return odds, fair


def cut(row, what):
    """Nesine's cut on a market group like '1X2' or 'OU|2.5' (sum of 1/odds - 1), in %."""
    mk, _, line = what.partition("|")
    cols = [c for c in row.index if c.split("|")[0] == mk and c.split("|")[1] == line and pd.notna(row[c])]
    return (sum(1 / row[c] for c in cols) - 1) * 100 if len(cols) >= 2 else np.nan


OPS = {"<=": lambda v, r: v <= r, "<": lambda v, r: v < r, ">": lambda v, r: v > r, ">=": lambda v, r: v >= r}


def check(crit, odds_row, fair_row):
    """All criteria must hold. Kinds: {bet, op, odds} | {bet, op, chance_pct} | {cut, op, pct} |
    {bet, op: "in", values: [...]} (odds exactly one of) | {near: [bet_a, bet_b], tol} (odds within tol) |
    {any: [[criteria], [criteria], ...]} (at least one group holds)."""
    for c in crit:
        if "any" in c:
            if not any(check(g, odds_row, fair_row) for g in c["any"]):
                return False
            continue
        if "near" in c:
            a, b = (odds_row.get(k, np.nan) for k in c["near"])
            if pd.isna(a) or pd.isna(b) or abs(a - b) > c["tol"] + 1e-9:
                return False
            continue
        if c.get("op") == "in":
            v = odds_row.get(c["bet"], np.nan)
            if pd.isna(v) or not any(abs(v - x) < 1e-9 for x in c["values"]):
                return False
            continue
        if "cut" in c:
            v = cut(odds_row, c["cut"])
            ref = c["pct"]
        elif "odds" in c:
            v, ref = odds_row.get(c["bet"], np.nan), c["odds"]
        else:
            f = fair_row.get(c["bet"], np.nan)
            v, ref = f * 100 if pd.notna(f) else np.nan, c["chance_pct"]
        if pd.isna(v) or not OPS[c["op"]](v, ref):
            return False
    return True


def lift(ev):
    """Last season's hit rate / normal rate (or / the same pack in every match)."""
    v = list(ev.values())[-1]
    ref = v.get("normal_pct") or v.get("every_match_pct")
    return v["hit_pct"] / ref if v.get("hit_pct") and ref else np.nan


def record(ev):
    parts = []
    for p, v in ev.items():
        s = f"{p} {v['hit_pct']}%" if v.get("hit_pct") is not None else f"{p} –"
        if "return_per_100" in v:
            s += f" ({v['return_per_100']:+} per 100)"
        parts.append(s)
    normal = [v.get("normal_pct") for v in ev.values() if v.get("normal_pct")]
    every = [v.get("every_match_pct") for v in ev.values() if v.get("every_match_pct")]
    tail = f" | normal {normal[-1]}%" if normal else f" | same pack in every match {every[-1]}%" if every else ""
    return " · ".join(parts) + tail


def window_of(ts):
    """Kick-off -> (start date, kind) of its betting window in Turkey time: weekend = Fri-Mon, midweek = Tue-Thu."""
    d = pd.Timestamp(ts).tz_convert("Europe/Istanbul").normalize()
    dow = d.dayofweek
    back = dow - 4 if dow >= 4 else (3 if dow == 0 else dow - 1)
    return (d - pd.Timedelta(days=back)).date(), ("weekend" if dow >= 4 or dow == 0 else "midweek")


def esym(odds, kmax):
    e = np.zeros(kmax + 1)
    e[0] = 1.0
    for o in odds:
        for k in range(kmax, 0, -1):
            e[k] += e[k - 1] * o
    return e


def build_coupon(s, cands):
    """The games of a 'system' strategy: its groups in order (e.g. Portugal first), lowest odds first within a group,
    one bet per game (the higher price of equivalent bets), until s['legs'] games. cands: one row per match_id with
    'league', 'kickoff' and odds columns per bet label. Chance per game = return per unit / odds (from the book)."""
    legs, used = [], set()
    for g in s["groups"]:
        d = cands if g["leagues"] == "all" else cands[cands["league"].isin(g["leagues"])]
        bets = [b for b in g["bets"] if b in d.columns]
        if not bets or not len(d):
            continue
        o = d[bets].max(axis=1)
        d = d[o.notna() & ~d.index.isin(used)]
        if not len(d):
            continue
        d = d.assign(_o=o[d.index], _bet=d[bets].idxmax(axis=1)).sort_values("_o")
        for mid, r in d.iterrows():
            if len(legs) >= s["legs"]:
                break
            if "value_ladder" in g:
                v = next((x[1] for x in g["value_ladder"] if r["_o"] <= x[0]), g["value_ladder"][-1][1])
            else:
                v = g["value_for_chances"]
            legs.append({"match_id": mid, "league": r["league"], "kickoff": r["kickoff"], "group": g["name"],
                         "bet": r["_bet"], "odds": float(r["_o"]), "chance": min(v / r["_o"], 1.0)})
            used.add(mid)
    return pd.DataFrame(legs)


def coupon_stats(odds, chances, sizes):
    """Stake (1 unit per combo), chance of 3+/4+/5+ hits (independent games) and the average payout for exactly
    3/4/5 hits as a multiple of the stake (sum over sizes k of e_k(all odds) * C(n-k, h-k) / C(n, h))."""
    n = len(odds)
    dist = np.zeros(n + 1)
    dist[0] = 1.0
    for p in chances:
        new = dist * (1 - p)
        new[1:] += dist[:-1] * p
        dist = new
    e = esym(odds, max(sizes))
    stake = sum(comb(n, k) for k in sizes)
    pays = {h: sum(e[k] * comb(n - k, h - k) for k in sizes if k <= h) / comb(n, h) / stake
            for h in (3, 4, 5) if h <= n}
    return {"games": n, "stake": stake, "p": {h: dist[h:].sum() * 100 for h in (3, 4, 5)}, "pays": pays}


def system_coupons(book, m, odds, lg, teams):
    """One coupon per 'system' strategy for the first weekend among the upcoming matches."""
    systems = [s for s in book if s["kind"] == "system"]
    if not systems or not len(m):
        return []
    m = m[m["match_id"].isin(odds.index)].copy()
    if not len(m):
        return []
    w = [window_of(t) for t in m["kickoff_utc"]]
    m["win"], m["wkind"] = [x[0] for x in w], [x[1] for x in w]
    out = []
    for s in systems:
        mw = m[m["wkind"] == s["window"]]
        if not len(mw):
            continue
        first = mw["win"].min()
        g = mw[mw["win"] == first]
        cands = odds.reindex(g["match_id"])
        cands["league"] = g.set_index("match_id")["league_id"]
        cands["kickoff"] = g.set_index("match_id")["kickoff_utc"].dt.tz_convert("Europe/Istanbul")
        legs = build_coupon(s, cands)
        if not len(legs):
            continue
        hm = g.set_index("match_id")
        legs["match"] = [f"{teams.get(hm.loc[x, 'home_team_id'], hm.loc[x, 'home_team_id'])} – "
                         f"{teams.get(hm.loc[x, 'away_team_id'], hm.loc[x, 'away_team_id'])}" for x in legs["match_id"]]
        legs["league_name"] = [lg.get(x, {}).get("en", x) for x in legs["league"]]
        st = coupon_stats(legs["odds"].to_numpy(), legs["chance"].to_numpy(), s["sizes"])
        out.append({"strategy": s, "window": first, "legs": legs, "stats": st,
                    "games_in_window": int(len(g))})
    return out


def write_systems(sysc):
    if not sysc:
        return []
    L = ["", "## Your 10-game system (system 3-4-5)", ""]
    for c in sysc:
        s, legs, st = c["strategy"], c["legs"], c["stats"]
        L += [f"### {s.get('name', s['id'])} [{s['status']}] — weekend starting {c['window']:%a %d %b}", "",
              s["summary"], ""]
        L += ["| # | Kick-off | Match | League | Bet | Odds | Chance |", "|---|---|---|---|---|---|---|"]
        for i, r in enumerate(legs.itertuples(), 1):
            L.append(f"| {i} | {r.kickoff:%a %H:%M} | {r.match} | {r.league_name} | {BET_TR.get(r.bet, r.bet)} | "
                     f"{r.odds:.2f} | {r.chance * 100:.0f}% |")
        short = f" (only {st['games']} games have odds so far)" if st["games"] < s["legs"] else ""
        L += ["", f"{st['games']} games{short} → {st['stake']} combos at 1 unit. Chance of 3+ hits ≈ "
              f"{st['p'][3]:.1f}%, 4+ ≈ {st['p'][4]:.1f}%, 5+ ≈ {st['p'][5]:.2f}%. "
              + ", ".join(f"{h} hits pay ≈ {v:,.1f}x the stake" for h, v in st["pays"].items()) + "."]
        ev = "; ".join(f"{p}: {v['coupons']} weekends, 3+ hits in {v['coupons_3plus_hits_pct']}%, system 3-4-5 "
                       f"{v['system_345_return_per_100']:+} per 100, singles {v['return_per_100']:+}"
                       for p, v in s["evidence"].items())
        L += [f"Record (one coupon per weekend): {ev}."]
        if s.get("note"):
            L += [f"Note: {s['note']}"]
        L.append("")
    return L


def scan(data_dir: Path, days: int):
    book = [s for s in yaml.safe_load((HERE / "strategies.yaml").read_text())["strategies"]
            if s.get("status") != "retired"]
    m_all, o, teams, mknames = dashboard.load_upcoming(data_dir, max(days, SYSTEM_DAYS))
    m = m_all[m_all["kickoff_utc"] <= pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=days)]
    o_days = o[o["match_id"].isin(m["match_id"])]
    lg = dashboard.leagues()
    odds, fair = live_tables(o)
    sysc = system_coupons(book, m_all, odds, lg, teams)
    rows = []
    for r in m.itertuples():
        if r.match_id not in odds.index:
            continue
        orow, frow = odds.loc[r.match_id], fair.loc[r.match_id]
        base = {"kickoff": pd.Timestamp(r.kickoff_utc).tz_convert("Europe/Istanbul"), "league": r.league_id,
                "league_name": lg.get(r.league_id, {}).get("en", r.league_id),
                "match": f"{teams.get(r.home_team_id, r.home_team_id)} – {teams.get(r.away_team_id, r.away_team_id)}"}
        for s in book:
            k = s["kind"]
            if k in ("odds_band", "odds_rule", "watch", "league_rule", "tipster"):
                if (k == "league_rule" and r.league_id != s["league"]) or not check(s["criteria"], orow, frow):
                    continue
                rows.append({**base, "status": s["status"], "kind": k, "bet": s["bet_name"],
                             "odds_now": orow.get(s["bet"], np.nan), "why": s["summary"], "record": record(s["evidence"]),
                             "id": s["id"], "lift": lift(s["evidence"])})
            elif k == "league" and r.league_id == s["league"]:
                rows.append({**base, "status": s["status"], "kind": k, "bet": s["bet_name"],
                             "odds_now": orow.get(s["bet"], np.nan), "why": s["summary"], "record": record(s["evidence"]),
                             "id": s["id"], "lift": lift(s["evidence"])})
            elif k == "pack":
                sel = [x for x in s["selections"] if pd.notna(frow.get(x, np.nan))]
                if len(sel) < s["k"]:
                    continue
                top = sorted(sel, key=lambda x: -frow[x])[:s["k"]]
                ch = sum(frow[x] for x in top)
                if ch < s["min_pack_chance"]:
                    continue
                od = [orow.get(x, np.nan) for x in top]
                eff = 1 / sum(1 / v for v in od) if all(pd.notna(v) for v in od) else np.nan
                picks = ", ".join(f"{x.split('|')[-1]} @ {v:.2f}" for x, v in zip(top, od))
                rows.append({**base, "status": s["status"], "kind": k,
                             "bet": f"{MARKET.get(s['market'], s['market'])} pack: {picks}", "odds_now": eff,
                             "why": s["summary"], "record": record(s["evidence"]), "id": s["id"],
                             "lift": lift(s["evidence"])})
    out = strongest_only(pd.DataFrame(rows))
    # rule book (older study) through the Matchday Radar engine, if its cache exists
    rb = pd.DataFrame()
    if (CACHE / "rules_deep.parquet").exists():
        try:
            dd = dashboard.compute(m, o_days, teams, mknames, days)
            ms = {x["id"]: x for x in dd["matches"]}
            p = pd.DataFrame(dd["picks"])
            if len(p):
                p = p[(p["rating"] == "very reliable") & (p["odds"] >= 4) & (p["hit"] >= 1.5 * p["normal"])]
                for x in p.itertuples():
                    mm = ms[x.m]
                    rb = pd.concat([rb, pd.DataFrame([{
                        "kickoff": pd.Timestamp(f"{mm['date']} {mm['time']}", tz="Europe/Istanbul"),
                        "league": mm["league"], "league_name": mm.get("league_name", mm["league"]),
                        "match": f"{mm['home']} – {mm['away']}", "status": "rule book", "kind": "rule_book",
                        "bet": x.bet, "odds_now": x.odds, "why": f"rule: {x.rule}",
                        "record": f"hit {x.hit_all:.1f}% in {x.n} past matches (normal {x.normal:.1f}%), "
                                  f"expected now ≈ {x.hit:.1f}%", "id": "rule_book",
                        "lift": x.hit_all / x.normal}])])
        except Exception as exc:  # noqa: BLE001
            print(f"rule book skipped: {exc}")
    m = m.assign(priced=m["match_id"].isin(odds.index))
    return pd.concat([out, rb], ignore_index=True), m, sysc


def write(res, m, out_md: Path, days: int, sysc=()):
    now = pd.Timestamp.now(tz="Europe/Istanbul")
    L = [f"# Daily scan — {now:%d %b %Y %H:%M} (Turkey time)", "",
         f"{len(m)} upcoming matches in the next {days} days across the 26 leagues; {int(m['priced'].sum())} already "
         f"have Nesine odds (the rest are checked on a later day); "
         f"{res['match'].nunique() if len(res) else 0} matches fit at least one strategy.", ""]
    if not len(res):
        out_md.write_text("\n".join(L + ["Nothing fits today."] + write_systems(sysc)))
        return
    res = res.sort_values(["kickoff", "match"])
    cnt = res.groupby("status").size().to_dict()
    L.append("Findings: " + ", ".join(f"{v} {k}" for k, v in sorted(cnt.items(), key=lambda kv: RANK.get(kv[0], 9))))
    lgr = res[res["kind"] == "league"]
    if len(lgr):
        L += ["", "## League tendencies today", ""]
        for sid, g in lgr.groupby("id", sort=False):
            r = g.iloc[0]
            ms = ", ".join(f"{x.match} {x.kickoff:%a %H:%M} @ " + (f"{x.odds_now:.2f}" if pd.notna(x.odds_now) else "–")
                           for x in g.itertuples())
            L.append(f"- **{r['why']}** [{r['status']}]  \n  Record: {r['record']}  \n  Today: {ms}")
    hi = res[res["kind"].isin(["league_rule", "watch", "pack"])]
    if len(hi):
        L += ["", "## Money leads, packs and watch patterns", ""]
    for r in hi.itertuples():
        od = f"{r.odds_now:.2f}" if pd.notna(r.odds_now) else "not offered yet"
        L.append(f"- **{r.kickoff:%a %H:%M} {r.match}** ({r.league_name}) — {r.bet} @ {od} [{r.status}]  \n"
                 f"  {r.why}. Record: {r.record}")
    L += write_systems(sysc)
    L += ["", "## Every match", ""]
    for (k, mt), g in res.groupby(["kickoff", "match"], sort=True):
        L.append(f"### {k:%a %d %b %H:%M} — {mt} ({g['league_name'].iloc[0]})")
        g = g[g["kind"] != "league"].sort_values("lift", ascending=False)
        for bet, gb in g.groupby("bet", sort=False):               # one line per bet: its strongest strategy
            r = gb.iloc[0]
            od = f"{r.odds_now:.2f}" if pd.notna(r.odds_now) else "no own odds"
            more = f" (+{len(gb) - 1} more strategies agree)" if len(gb) > 1 else ""
            L.append(f"- {bet} @ {od} [{r.status}, {r.lift:.1f}x normal] — {r.record}{more}")
        L.append("")
    out_md.write_text("\n".join(L))
    x = res.copy()
    x["kickoff"] = x["kickoff"].dt.tz_localize(None)
    with pd.ExcelWriter(out_md.with_suffix(".xlsx")) as xw:
        x.to_excel(xw, sheet_name="Findings", index=False)
        for c in sysc:
            legs = c["legs"].assign(kickoff=c["legs"]["kickoff"].dt.tz_localize(None))
            legs[["kickoff", "match", "league_name", "group", "bet", "odds", "chance"]].to_excel(
                xw, sheet_name=c["strategy"]["id"][:31], index=False)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--out", type=Path, default=HERE / "output" / "daily_scan.md")
    a = ap.parse_args()
    res, m, sysc = scan(a.data_dir, a.days)
    write(res, m, a.out, a.days, sysc)
    print(a.out, len(res))
