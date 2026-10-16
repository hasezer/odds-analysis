"""Grade the picks of outside tipsters, winners AND losers, against our own data.

Log every shared pick in analysis/tipster_log.csv (date in Turkey time, team ids from data/teams, bet as a selection
label such as HT_2H_BTTS||YES/YES or GOAL_RANGE||6+, the odds they showed if any). This script finds each match,
settles the bet from the score, takes Nesine's closing odds from our data, and compares the record with what the
odds expected.

python analysis/tipster_log.py  ->  analysis/output/tipster_log.md and .xlsx
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import daily_scan as ds  # noqa: E402
import hi_data  # noqa: E402
import tracker as tk  # noqa: E402


def run():
    log = pd.read_csv(HERE / "tipster_log.csv", dtype=str)
    log["odds_seen"] = pd.to_numeric(log["odds_seen"], errors="coerce")
    start = pd.Timestamp(log["date"].min(), tz="Europe/Istanbul").tz_convert("UTC") - pd.Timedelta(days=1)
    m, o = tk.finished_since(start)
    odds, _ = ds.live_tables(o) if len(o) else (pd.DataFrame(), None)
    idx, ok = hi_data.cells(m) if len(m) else (np.array([]), np.array([]))
    keys = {}
    for n in odds.columns:
        mk, _, sk = n.split("|")
        keys.setdefault(mk, []).append(sk)
    m = m.assign(row=np.arange(len(m)),
                 day=m["kickoff_utc"].dt.tz_convert("Europe/Istanbul").dt.strftime("%Y-%m-%d"))
    rows = []
    for r in log.itertuples():
        hit = mm = None
        g = m[(m["home_team_id"] == r.home_team_id) & (m["away_team_id"] == r.away_team_id) & (m["day"] == r.date)]
        if len(g):
            mm = g.iloc[0]
            hit = tk.outcome(r.bet, idx, ok, keys)[int(mm["row"])]
        close = odds.loc[mm["match_id"]].get(r.bet, np.nan) if mm is not None and mm["match_id"] in odds.index else np.nan
        price = r.odds_seen if pd.notna(r.odds_seen) else close
        rows.append({"date": r.date, "source": r.source, "match": f"{r.home_team_id} - {r.away_team_id}",
                     "bet": r.bet, "odds_seen": r.odds_seen, "nesine_closing_odds": close,
                     "score": f"{int(mm['ht_home'])}-{int(mm['ht_away'])} / {int(mm['ft_home'])}-{int(mm['ft_away'])}"
                     if mm is not None else "not played / no result yet",
                     "won": hit if hit is not None and not np.isnan(hit) else np.nan,
                     "return": (hit * price - 1) if hit is not None and pd.notna(price) and not np.isnan(hit) else np.nan,
                     "chance_from_odds_pct": 100 / price if pd.notna(price) else np.nan})
    return pd.DataFrame(rows)


def write(r):
    out = HERE / "output" / "tipster_log.md"
    done = r[r["won"].notna()]
    L = ["# Tipster log — every shared pick, winners and losers", ""]
    for src, g in done.groupby("source"):
        p = g[g["return"].notna()]
        L.append(f"- **{src}**: {len(g)} settled picks, {int(g['won'].sum())} won ({g['won'].mean() * 100:.1f}%); "
                 f"the odds expected {p['chance_from_odds_pct'].mean():.1f}% (incl. Nesine's cut); return "
                 f"{p['return'].mean() * 100:+.1f} per 100 staked on singles")
    L += ["", f"Waiting for a result: {int(r['won'].isna().sum())} picks.", "",
          "| Date | Match | Bet | Odds | Score (HT / FT) | Won |", "|---|---|---|---|---|---|"]
    for x in r.itertuples():
        od = x.odds_seen if pd.notna(x.odds_seen) else x.nesine_closing_odds
        L.append(f"| {x.date} | {x.match} | {x.bet} | {od if pd.notna(od) else '–'} | {x.score} | "
                 f"{'–' if pd.isna(x.won) else ('yes' if x.won else 'no')} |")
    out.write_text("\n".join(L))
    r.to_excel(out.with_suffix(".xlsx"), index=False)
    return out


if __name__ == "__main__":
    print(write(run()))
