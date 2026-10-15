"""Daily scan: check every strategy of the strategy book against the upcoming fixtures of the 26 leagues.

python analysis/daily_scan.py --data-dir /tmp/scan/data --days 3
  reads   analysis/strategies.yaml (build_strategy_book.py), the upcoming matches and their latest Nesine odds
          from a data directory (a fresh snapshot, see daily_scan.sh), and the rule-book engine if its cache exists
  writes  analysis/output/daily_scan.md (highlights + every match) and analysis/output/daily_scan.xlsx
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dashboard  # noqa: E402
import miner_data as mdat  # noqa: E402
from htft_data import CACHE  # noqa: E402

RANK = {"promising": 0, "watch": 1, "proven": 2}
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
    o = dashboard.fair_probs(o)
    o["lab"] = [mdat.label(a, b, c) for a, b, c in zip(o["market_key"], o["line"], o["selection_key"])]
    odds = o.pivot_table(index="match_id", columns="lab", values="odds", aggfunc="last")
    fair = o.pivot_table(index="match_id", columns="lab", values="fair", aggfunc="last")
    return odds, fair


def cut(row, what):
    """Nesine's cut on a market group like '1X2' or 'OU|2.5' (sum of 1/odds - 1), in %."""
    mk, _, line = what.partition("|")
    cols = [c for c in row.index if c.split("|")[0] == mk and c.split("|")[1] == line and pd.notna(row[c])]
    return (sum(1 / row[c] for c in cols) - 1) * 100 if len(cols) >= 2 else np.nan


def check(crit, odds_row, fair_row):
    for c in crit:
        if "cut" in c:
            v = cut(odds_row, c["cut"])
            ref = c["pct"]
        elif "odds" in c:
            v, ref = odds_row.get(c["bet"], np.nan), c["odds"]
        else:
            f = fair_row.get(c["bet"], np.nan)
            v, ref = f * 100 if pd.notna(f) else np.nan, c["chance_pct"]
        if pd.isna(v) or not (v <= ref if c["op"] == "<=" else v > ref):
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


def scan(data_dir: Path, days: int):
    book = [s for s in yaml.safe_load((HERE / "strategies.yaml").read_text())["strategies"]
            if s.get("status") != "retired"]
    m, o, teams, mknames = dashboard.load_upcoming(data_dir, days)
    lg = dashboard.leagues()
    odds, fair = live_tables(o)
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
            if k in ("odds_band", "odds_rule", "watch", "league_rule"):
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
            dd = dashboard.compute(m, o, teams, mknames, days)
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
    return pd.concat([out, rb], ignore_index=True), m


def write(res, m, out_md: Path, days: int):
    now = pd.Timestamp.now(tz="Europe/Istanbul")
    L = [f"# Daily scan — {now:%d %b %Y %H:%M} (Turkey time)", "",
         f"{len(m)} upcoming matches in the next {days} days across the 26 leagues; {int(m['priced'].sum())} already "
         f"have Nesine odds (the rest are checked on a later day); "
         f"{res['match'].nunique() if len(res) else 0} matches fit at least one strategy.", ""]
    if not len(res):
        out_md.write_text("\n".join(L + ["Nothing fits today."]))
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
    x.to_excel(out_md.with_suffix(".xlsx"), index=False)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--out", type=Path, default=HERE / "output" / "daily_scan.md")
    a = ap.parse_args()
    res, m = scan(a.data_dir, a.days)
    write(res, m, a.out, a.days)
    print(a.out, len(res))
