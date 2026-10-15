"""Betting slips for any competitions on a date, built from the strategy book and the rule book.

python analysis/slips.py --date 2026-10-15 --competition 4oogyu6o156iphvdvphwpck10:"UEFA Avrupa Ligi" ...
  1. fetches the current Nesine odds of the competitions' matches (read-only, in memory; fixture_picks.fetch)
  2. checks every strategy of analysis/strategies.yaml that is not tied to a league (odds bands, odds rules,
     packs, watch) and the rule-book engine (dashboard.compute, 'very reliable' picks)
  3. keeps, per match, its candidates with an expected hit rate (the strategy's record) and builds slips:
       safe       3 matches, the most likely pick of each (odds >= 1.20)
       balanced   3 matches, picks with odds 1.50-2.60 and the best hit rate vs break-even
       high odds  2 matches, picks with odds >= 3.50 closest to (or above) break-even
       singles    the 3 high-odds picks closest to (or above) break-even, one match each
     chance of a slip = product of the picks' expected hit rates (different matches, taken as independent)
  writes analysis/output/slips_<date>.md and .xlsx
Note: the strategies were learned on the project's 26 domestic leagues; European cups are outside that data.
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import daily_scan as ds  # noqa: E402
import dashboard  # noqa: E402
import fixture_picks as fp  # noqa: E402

ROOT = HERE.parent


def expected_hit(ev):
    vals = [v["hit_pct"] for v in ev.values() if v.get("hit_pct") is not None]
    return float(np.mean(vals)) if vals else np.nan        # average over the seasons (less noisy than the last one)


def candidates(m, o, teams, lg_name):
    book = [s for s in yaml.safe_load((HERE / "strategies.yaml").read_text())["strategies"]
            if s.get("status") != "retired" and s["kind"] in ("odds_band", "odds_rule", "pack", "watch")]
    odds, fair = ds.live_tables(o)
    rows = []
    for r in m.itertuples():
        if r.match_id not in odds.index:
            continue
        orow, frow = odds.loc[r.match_id], fair.loc[r.match_id]
        base = {"match_id": r.match_id, "competition": lg_name.get(r.league_id, r.league_id),
                "kickoff": pd.Timestamp(r.kickoff_utc).tz_convert("Europe/Istanbul").tz_localize(None),
                "match": f"{teams.get(r.home_team_id, r.home_team_id)} – {teams.get(r.away_team_id, r.away_team_id)}"}
        for s in book:
            if s["kind"] == "pack":
                sel = [x for x in s["selections"] if pd.notna(frow.get(x, np.nan))]
                if len(sel) < s["k"]:
                    continue
                top = sorted(sel, key=lambda x: -frow[x])[:s["k"]]
                if sum(frow[x] for x in top) < s["min_pack_chance"]:
                    continue
                od = [orow.get(x, np.nan) for x in top]
                if not all(pd.notna(v) for v in od):
                    continue
                name = {"CORRECT_SCORE": "Correct score", "HT_CORRECT_SCORE": "1st-half score", "HT_FT": "HT/FT"}
                bet = f"{name.get(s['market'], s['market'])} {' or '.join(x.split('|')[-1] for x in top)} " \
                      f"(split the stake: {', '.join(f'{v:.2f}' for v in od)})"
                price = 1 / sum(1 / v for v in od)
            else:
                if not ds.check(s["criteria"], orow, frow):
                    continue
                price = orow.get(s["bet"], np.nan)
                if pd.isna(price):
                    continue
                bet = s["bet_name"]
            rows.append({**base, "bet": bet, "odds": float(price), "expected_hit_pct": expected_hit(s["evidence"]),
                         "source": f"{s['kind']} [{s['status']}]", "why": s["summary"]})
    # rule book (older study) through the Matchday Radar engine
    try:
        mk = pd.read_parquet(ROOT / "data" / "markets" / "part-0000.parquet").drop_duplicates("market_type_id")
        dd = dashboard.compute(m, o, teams, mk.set_index("market_type_id")["name_tr"], days=1,
                               league_names={k: {"tr": v, "en": v} for k, v in lg_name.items()})
        ms = {x["id"]: x for x in dd["matches"]}
        for p in dd["picks"]:
            if p["rating"] != "very reliable" or p["odds"] is None or p.get("hist_price") is None:
                continue                       # no recorded price for the rule -> its context cannot be checked
            mm = ms[p["m"]]
            rows.append({"match_id": p["m"], "competition": lg_name.get(mm["league"], mm["league"]),
                         "kickoff": pd.Timestamp(f"{mm['date']} {mm['time']}"), "match": f"{mm['home']} – {mm['away']}",
                         "bet": p["bet"], "odds": float(p["odds"]), "expected_hit_pct": float(p["hit"]),
                         "source": "rule book [very reliable]", "why": f"rule: {p['rule']}"})
    except Exception as exc:  # noqa: BLE001
        print(f"rule book skipped: {exc}")
    c = pd.DataFrame(rows)
    if len(c):
        c["breakeven_pct"] = 100 / c["odds"]
        c["edge"] = c["expected_hit_pct"] / c["breakeven_pct"]       # > 1 would mean the record beats the price
        # sanity: no strategy beats Nesine's price by 30%+ in our tests; such a pick is a rule out of its context
        c = c[c["edge"] <= 1.3]
        # one line per match + bet: the strategy with the best record
        c = c.sort_values("expected_hit_pct", ascending=False).drop_duplicates(["match_id", "bet"])
    return c


def build_slips(c):
    def pick(pool, n, key):
        out, used = [], set()
        for r in pool.sort_values(key, ascending=False).itertuples():
            if r.match_id in used:
                continue
            out.append(r); used.add(r.match_id)
            if len(out) == n:
                break
        return out
    slips = {
        "Safe slip (3 matches, most likely picks)": pick(c[c["odds"] >= 1.20], 3, "expected_hit_pct"),
        "Balanced slip (3 matches, odds 1.50–2.60)": pick(c[(c["odds"] >= 1.5) & (c["odds"] <= 2.6)], 3, "edge"),
        "High-odds slip (2 matches, odds 3.50–12)": pick(c[(c["odds"] >= 3.5) & (c["odds"] <= 12)], 2, "edge"),
    }
    singles = pick(c[c["odds"] >= 3.5], 3, "edge")
    return slips, singles


def write(c, slips, singles, d, out):
    L = [f"# Slips — {d:%d %b %Y}", "",
         "Built from the strategy book (odds bands, odds rules, packs) and the rule book, on Nesine's current odds. "
         "The strategies were learned on our 26 domestic leagues: European cups are outside that data, so treat them "
         "with extra caution. Chance of a slip = product of the picks' past hit rates. None of these beats Nesine's "
         "prices over time: they pick the likelier outcomes, and the odds already reflect that. Check Nesine's minimum "
         "number of matches per slip (MBS) before playing.", ""]
    for name, picks in list(slips.items()) + [("Singles (high odds, one match each)", singles)]:
        if not picks:
            continue
        L += [f"## {name}", ""]
        if not name.startswith("Singles"):
            tot_odds = float(np.prod([p.odds for p in picks]))
            chance = float(np.prod([p.expected_hit_pct / 100 for p in picks]))
            L += [f"**Total odds {tot_odds:.2f} — chance about {chance * 100:.1f}% (about 1 in {1 / chance:.0f})**", ""]
        for p in picks:
            L.append(f"- {p.kickoff:%H:%M} **{p.match}** ({p.competition}): **{p.bet}** @ {p.odds:.2f} — past hit "
                     f"rate {p.expected_hit_pct:.0f}% (break-even {p.breakeven_pct:.0f}%) · {p.source}")
        L.append("")
    out.write_text("\n".join(L))
    c.round({"odds": 2, "expected_hit_pct": 1, "breakeven_pct": 1, "edge": 2}).to_excel(out.with_suffix(".xlsx"),
                                                                                       index=False)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", type=date.fromisoformat, default=date.today())
    ap.add_argument("--competition", action="append", required=True, help="mackolik_id:Name")
    a = ap.parse_args()
    ms, os_, ts, names = [], [], [], {}
    from htft_data import CACHE
    for item in a.competition:
        cid, _, nm = item.partition(":")
        lid = f"CUP-{cid[:6]}"
        names[lid] = nm or cid
        cf = CACHE / f"slips_{a.date:%Y%m%d}_{cid}.pkl"           # same-day re-runs reuse the fetched odds
        if cf.exists() and (pd.Timestamp.now() - pd.Timestamp(cf.stat().st_mtime, unit="s")).total_seconds() < 3600:
            m, o, t = pd.read_pickle(cf)
        else:
            m, o, t = fp.fetch(cid, a.date, lid)
            pd.to_pickle((m, o, t), cf)
        ms.append(m); os_.append(o); ts.append(t)
    m, o, teams = pd.concat(ms, ignore_index=True), pd.concat(os_, ignore_index=True), pd.concat(ts)
    c = candidates(m, o, teams, names)
    slips, singles = build_slips(c)
    out = HERE / "output" / f"slips_{a.date:%Y-%m-%d}.md"
    write(c, slips, singles, a.date, out)
    print(out, len(m), "matches", len(c), "candidates")
