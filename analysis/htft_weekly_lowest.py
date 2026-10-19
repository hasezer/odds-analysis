"""Each league's lowest HT/FT comeback odds of the week: how often do they land?

Bets (Turkish notation 0 = draw): 2/1, 1/2 (comebacks) and 1/0 = 1/X, 2/0 = 2/X (leader at half time, ends level).
For every league and week (Monday-Sunday, Turkey time), the games are ranked by Nesine's closing odds of the bet;
the week's lowest (rank 1), and the lowest 2 and 3, are 'picked'. Per league and season (2024/25 + 2024,
2025/26 + 2025, 2026/27 + 2026): picks, hit rate, the chance the odds imply (break-even), Nesine's fair chance (cut
removed), and the return per 100 at closing odds; the same for every game of the league as the baseline.
Neighbours: for the week's lowest 1/2 (and 2/1) game, how did it actually end (1/1, 1/X, 1/2 ...), and what backing
1/2 + 1/X together (2/1 + 2/X) would have paid. Writes output/htft_weekly_lowest.xlsx and
cache/htft_weekly_lowest.parquet.

    python analysis/htft_weekly_lowest.py
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load  # noqa: E402
from htft_data import CACHE  # noqa: E402
from htft3_data import PER  # noqa: E402

HERE = Path(__file__).resolve().parent
BETS = {"2/1": "2/1", "1/2": "1/2", "1/0 (1/X)": "1/X", "2/0 (2/X)": "2/X"}
SEAS = {"A": "2024/25", "B": "2025/26", "C": "2026/27"}
RANKS = (1, 2, 3)


def table():
    f = load.flat()
    h = f[(f["market_key"] == "HT_FT") & f["closing_odds"].notna() & f["in_default_analysis"]]
    o = h.pivot_table(index="match_id", columns="selection_key", values="closing_odds")
    o = o.dropna(subset=list(BETS.values()))
    fair = (1 / o).div((1 / o).sum(axis=1), axis=0)          # 9-way market, cut spread evenly
    m = load.matches()
    m = m[(m["status"] == "finished") & m["ht_home"].notna() & m["ft_home"].notna()].copy()
    m["per"] = m["season"].map(PER)
    m = m[m["per"].notna() & m["match_id"].isin(o.index)].copy()
    s = lambda a, b: np.where(a > b, "1", np.where(a < b, "2", "X"))  # noqa: E731
    m["htft"] = pd.Series(s(m["ht_home"], m["ht_away"]), index=m.index) + "/" + s(m["ft_home"], m["ft_away"])
    m["day"] = m["kickoff_utc"].dt.tz_convert("Europe/Istanbul").dt.tz_localize(None).dt.normalize()
    m["week"] = m["day"] - pd.to_timedelta(m["day"].dt.weekday, unit="D")
    for lab, k in BETS.items():
        m[f"o_{k}"] = m["match_id"].map(o[k])
        m[f"f_{k}"] = m["match_id"].map(fair[k])
    return m.reset_index(drop=True)


def ranked(m, k):
    """Rank of each game's odds for bet k inside its league-week (1 = lowest odds; ties by kick-off)."""
    x = m.sort_values([f"o_{k}", "kickoff_utc"])
    return x.groupby(["league_id", "week"]).cumcount().reindex(m.index) + 1


def summary(g, k):
    y = (g["htft"] == k).to_numpy(float)
    o = g[f"o_{k}"].to_numpy(float)
    return {"picks": len(g), "won": int(y.sum()), "hit %": y.mean() * 100 if len(g) else np.nan,
            "break-even % (1/odds)": (1 / o).mean() * 100 if len(g) else np.nan,
            "fair chance %": g[f"f_{k}"].mean() * 100 if len(g) else np.nan,
            "average odds": o.mean() if len(g) else np.nan,
            "return per 100": ((y * o).mean() - 1) * 100 if len(g) else np.nan}


def by_league(m):
    rows = []
    for lab, k in BETS.items():
        rk = ranked(m, k)
        for scope in ("every game",) + tuple(f"week's lowest {r}" for r in RANKS):
            sel = rk.notna() if scope == "every game" else rk <= int(scope.split()[-1])
            for (lg, per), g in m[sel].groupby(["league_id", "per"]):
                rows.append({"bet": lab, "which games": scope, "league": lg, "season": SEAS[per], **summary(g, k)})
            for lg, g in m[sel].groupby("league_id"):
                rows.append({"bet": lab, "which games": scope, "league": lg, "season": "all", **summary(g, k)})
            for per, g in m[sel].groupby("per"):
                rows.append({"bet": lab, "which games": scope, "league": "ALL LEAGUES", "season": SEAS[per],
                             **summary(g, k)})
            rows.append({"bet": lab, "which games": scope, "league": "ALL LEAGUES", "season": "all",
                         **summary(m[sel], k)})
    return pd.DataFrame(rows)


def neighbours(m):
    """How the week's lowest 1/2 (2/1) games actually ended, and backing 1/2 + 1/X (2/1 + 2/X) together."""
    out, pair = [], []
    for k, alt in (("1/2", "1/X"), ("2/1", "2/X")):
        rk = ranked(m, k)
        for r in RANKS:
            g = m[rk <= r]
            for per, gg in list(g.groupby("per")) + [("all", g)]:
                share = gg["htft"].value_counts(normalize=True).mul(100)
                out.append({"week's lowest": f"{k}, lowest {r}", "season": SEAS.get(per, "all"), "games": len(gg),
                            **{f"ended {c} %": share.get(c, 0.0) for c in
                               ("1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2")}})
                y1, y2 = (gg["htft"] == k).to_numpy(float), (gg["htft"] == alt).to_numpy(float)
                o1, o2 = gg[f"o_{k}"].to_numpy(float), gg[f"o_{alt}"].to_numpy(float)
                pair.append({"week's lowest": f"{k}, lowest {r}", "season": SEAS.get(per, "all"), "games": len(gg),
                             "comeback hit %": y1.mean() * 100, "leader-then-draw (1/0 or 2/0) hit %": y2.mean() * 100,
                             "either hit %": np.maximum(y1, y2).mean() * 100,
                             "comeback alone, return per 100": ((y1 * o1).mean() - 1) * 100,
                             "leader-then-draw alone, return per 100": ((y2 * o2).mean() - 1) * 100,
                             "both, half stake each, return per 100": ((y1 * o1 + y2 * o2) / 2 - 1).mean() * 100})
    return pd.DataFrame(out), pd.DataFrame(pair)


def main():
    m = table()
    L = by_league(m)
    N, P = neighbours(m)
    L.to_parquet(CACHE / "htft_weekly_lowest.parquet")
    out = HERE / "output" / "htft_weekly_lowest.xlsx"
    with pd.ExcelWriter(out) as xw:
        for lab in BETS:
            x = L[(L["bet"] == lab) & (L["season"] == "all")].drop(columns=["bet", "season"])
            x.round(1).to_excel(xw, sheet_name=f"{lab.split()[0].replace('/', '-')} by league", index=False)
        L.round(2).to_excel(xw, sheet_name="Every league x season", index=False)
        N.round(1).to_excel(xw, sheet_name="How lowest 1-2 2-1 ended", index=False)
        P.round(1).to_excel(xw, sheet_name="1-2 plus 1-0 together", index=False)
    print(f"{len(m)} games, {m['league_id'].nunique()} leagues, {m.groupby(['league_id', 'week']).ngroups} league-weeks")
    return m, L, N, P


if __name__ == "__main__":
    m, L, N, P = main()
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 20)
    print(L[L["league"] == "ALL LEAGUES"].round(1).to_string(index=False))
    print(N.round(1).to_string(index=False))
    print(P.round(1).to_string(index=False))
