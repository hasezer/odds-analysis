"""Rule hunt v5 / study 3: late-season motivation from league tables rebuilt from our own results.

For every league season the table is rebuilt match by match (points, goal difference, games played, games left
from the season's own fixture list). Before each match each team gets a situation:
  relegation fight   in the drop zone or within 3 points of it
  title race         within 3 points of the leader (leader included)
  nothing to play    cannot be relegated any more AND cannot reach the top 4 (3 points x games left)
  other
Pre-registered hypotheses, last 8 games of the season only (find on 2024/25 + 2024, confirm on 2025/26 + 2025):
  H1 motivated (relegation fight / title race) vs nothing to play: the motivated team wins more than its odds say
  H2 nothing to play vs nothing to play: more goals (over 2.5, both teams score) than the odds say
  H3 both fighting relegation: more draws / unders than the odds say
Leagues without relegation (MLS, Liga MX, Argentina, Eerste Divisie) are used for H2 only.
Writes cache/v5_motivation.parquet (one row per match with situations) and prints the hypothesis results.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load  # noqa: E402
from htft_data import CACHE  # noqa: E402

DROP = {"AUT-1": 1, "DEN-1": 1, "SUI-1": 1, "SCO-1": 1, "BEL-1": 2, "NOR-1": 2, "BRA-1": 4, "ESP-2": 4, "NED-2": 0,
        "USA-1": 0, "MEX-1": 0, "ARG-1": 0}
LATE = 8
PER = lambda s: np.where(np.isin(s, ["2024/25", "2024"]), "A", np.where(np.isin(s, ["2025/26", "2025"]), "B", "C"))


def situations():
    m = load.matches().sort_values("kickoff_utc")
    rows = []
    for (lg, ss), g in m.groupby(["league_id", "season"]):
        if g["season_type"].iloc[0] not in (None, "regular") and False:
            pass
        teams = pd.unique(pd.concat([g["home_team_id"], g["away_team_id"]]))
        total = pd.concat([g["home_team_id"], g["away_team_id"]]).value_counts()
        n_drop = DROP.get(lg, 3)
        pts = dict.fromkeys(teams, 0); gd = dict.fromkeys(teams, 0); pl = dict.fromkeys(teams, 0)
        for r in g.itertuples():
            table = sorted(teams, key=lambda t: (-pts[t], -gd[t]))
            rank = {t: i + 1 for i, t in enumerate(table)}
            nt = len(teams)
            drop_pts = pts[table[nt - n_drop]] if n_drop else None          # best team inside the drop zone
            safe_pts = pts[table[nt - n_drop - 1]] if n_drop else None      # last safe team
            top_pts, fourth_pts = pts[table[0]], pts[table[min(3, nt - 1)]]
            sit = {}
            for side, t in (("home", r.home_team_id), ("away", r.away_team_id)):
                left = int(total.get(t, 0) - pl[t])
                s = "other"
                if n_drop and (rank[t] > nt - n_drop or pts[t] - drop_pts <= 3):
                    s = "relegation fight"
                elif top_pts - pts[t] <= 3:
                    s = "title race"
                elif (not n_drop or pts[t] - drop_pts > 3 * left) and pts[t] + 3 * left < fourth_pts:
                    s = "nothing to play"
                sit[side] = (s, left, rank[t])
            rows.append({"match_id": r.match_id, "league_id": lg, "season": ss, "home_sit": sit["home"][0],
                         "away_sit": sit["away"][0], "home_left": sit["home"][1], "away_left": sit["away"][1],
                         "home_rank": sit["home"][2], "away_rank": sit["away"][2]})
            if r.status == "finished" and pd.notna(r.ft_home):
                h, a = r.ft_home, r.ft_away
                pl[r.home_team_id] += 1; pl[r.away_team_id] += 1
                gd[r.home_team_id] += h - a; gd[r.away_team_id] += a - h
                if h > a:
                    pts[r.home_team_id] += 3
                elif h < a:
                    pts[r.away_team_id] += 3
                else:
                    pts[r.home_team_id] += 1; pts[r.away_team_id] += 1
    return pd.DataFrame(rows)


def run():
    s = situations()
    f = load.flat()
    f = f[f["market_key"].isin(["1X2", "OU", "BTTS"]) & f["closing_odds"].notna() & (f["status"] == "settled")]
    f = f[(f["market_key"] != "OU") | (f["line"] == 2.5)]
    f["lab"] = f["market_key"] + "|" + f["selection_key"]
    x = f.merge(s, on="match_id")
    x = x[(x["home_left"] <= LATE) & (x["away_left"] <= LATE) & (x["home_left"] >= 1)]
    x["per"] = PER(x["season_x"] if "season_x" in x else x["season"])
    x["ret"] = x["hit"].astype(float) * x["closing_odds"] - 1
    mot = {"relegation fight", "title race"}
    tests = {
        "H1 motivated home vs nothing-to-play away: home win": (x["home_sit"].isin(mot)) & (x["away_sit"] == "nothing to play") & (x["lab"] == "1X2|1"),
        "H1 motivated away vs nothing-to-play home: away win": (x["away_sit"].isin(mot)) & (x["home_sit"] == "nothing to play") & (x["lab"] == "1X2|2"),
        "H1b nothing-to-play home vs motivated away: home win (fade)": (x["away_sit"].isin(mot)) & (x["home_sit"] == "nothing to play") & (x["lab"] == "1X2|1"),
        "H2 both nothing to play: over 2.5": (x["home_sit"] == "nothing to play") & (x["away_sit"] == "nothing to play") & (x["lab"] == "OU|OVER"),
        "H2 both nothing to play: both teams score": (x["home_sit"] == "nothing to play") & (x["away_sit"] == "nothing to play") & (x["lab"] == "BTTS|YES"),
        "H3 both relegation fight: draw": (x["home_sit"] == "relegation fight") & (x["away_sit"] == "relegation fight") & (x["lab"] == "1X2|X"),
        "H3 both relegation fight: under 2.5": (x["home_sit"] == "relegation fight") & (x["away_sit"] == "relegation fight") & (x["lab"] == "OU|UNDER"),
        "H3b title race vs relegation fight: under 2.5": (x["home_sit"].isin(mot) & x["away_sit"].isin(mot)) & (x["home_sit"] != x["away_sit"]) & (x["lab"] == "OU|UNDER"),
        "ref: all late-season home wins": (x["lab"] == "1X2|1"),
        "ref: all late-season over 2.5": (x["lab"] == "OU|OVER"),
    }
    rows = []
    for name, msk in tests.items():
        for p in "ABC":
            g = x[msk & (x["per"] == p)]
            if not len(g):
                continue
            rows.append({"hypothesis": name, "period": p, "bets": len(g), "hit_pct": g["hit"].mean() * 100,
                         "breakeven_pct": (1 / g["closing_odds"]).mean() * 100, "return_per_100": g["ret"].mean() * 100})
    res = pd.DataFrame(rows)
    s.to_parquet(CACHE / "v5_motivation.parquet")
    res.to_parquet(CACHE / "v5_motivation_tests.parquet")
    return s, res


if __name__ == "__main__":
    s, res = run()
    pd.set_option("display.width", 220)
    print(s.groupby(["home_sit"]).size().to_string())
    print(res.round(1).to_string())
