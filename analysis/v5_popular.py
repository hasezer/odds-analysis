"""Rule hunt v5 / study 4: does Nesine shade the odds of popular teams (its customers are Turkish)?

Popular teams (fixed list, chosen before looking): Turkey's big four and a few global giants. For their matches we
compare, against ALL other matches with the same odds band (like for like), the return per 100 of:
  backing the popular team to win, backing the draw, backing the opponent
If popular teams are over-backed, their odds are too short (backing them loses MORE than usual) and the other
side is too long (backing the opponent / draw loses LESS than usual, maybe wins).
Writes cache/v5_popular.parquet.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load  # noqa: E402
from htft_data import CACHE  # noqa: E402

TURKEY = ["TUR-GALATASARAY", "TUR-FENERBAHCE", "TUR-BESIKTAS", "TUR-TRABZONSPOR"]
GLOBAL = ["ESP-REAL_MADRID", "ESP-BARCELONA", "ENG-MAN_CITY", "ENG-LIVERPOOL", "ENG-MAN_UNITED", "ENG-ARSENAL",
          "ENG-CHELSEA", "GER-BAYERN_MUNIH", "FRA-PSG", "ITA-JUVENTUS", "ITA-INTER", "ITA-MILAN"]
PER = lambda s: np.where(np.isin(s, ["2024/25", "2024"]), "A", np.where(np.isin(s, ["2025/26", "2025"]), "B", "C"))


def run():
    f = load.flat()
    f = f[(f["market_key"] == "1X2") & f["closing_odds"].notna() & (f["status"] == "settled")]
    w = f.pivot_table(index=["match_id", "home_team_id", "away_team_id", "season"], columns="selection_key",
                      values=["closing_odds", "hit"], aggfunc="first").dropna().reset_index()
    w.columns = ["match_id", "home", "away", "season", "o1", "o2", "oX", "h1", "h2", "hX"]
    rows = []
    for side, opp in (("home", "away"), ("away", "home")):
        s1, s2 = ("1", "2") if side == "home" else ("2", "1")
        rows.append(pd.DataFrame({"match_id": w["match_id"], "team": w[side], "opp": w[opp], "season": w["season"],
                                  "o_team": w[f"o{s1}"], "h_team": w[f"h{s1}"].astype(float),
                                  "o_opp": w[f"o{s2}"], "h_opp": w[f"h{s2}"].astype(float),
                                  "o_draw": w["oX"], "h_draw": w["hX"].astype(float), "venue": side}))
    t = pd.concat(rows)
    t = t[~t["opp"].isin(TURKEY + GLOBAL)]            # one popular side per row
    t["group"] = np.where(t["team"].isin(TURKEY), "Turkey big 4", np.where(t["team"].isin(GLOBAL), "global giants",
                                                                           "all other teams"))
    t["band"] = pd.cut(t["o_team"], [1, 1.25, 1.5, 1.8, 2.2, 3, 50])
    t["per"] = PER(t["season"])
    out = []
    for bet in ("team", "draw", "opp"):
        t[f"r_{bet}"] = t[f"h_{bet}"] * t[f"o_{bet}"] - 1
    base = t[t["group"] == "all other teams"].groupby(["band", "venue"], observed=True)[["r_team", "r_draw", "r_opp"]].mean()
    for (g, p), x in t[t["group"] != "all other teams"].groupby(["group", "per"]):
        exp = base.reindex(pd.MultiIndex.from_arrays([x["band"], x["venue"]])).to_numpy()
        row = {"group": g, "period": p, "matches": len(x)}
        for k, bet in enumerate(("team", "draw", "opp")):
            row[f"{bet}: return"] = x[f"r_{bet}"].mean() * 100
            row[f"{bet}: same odds, other teams"] = np.nanmean(exp[:, k]) * 100
        out.append(row)
    res = pd.DataFrame(out)
    res.to_parquet(CACHE / "v5_popular.parquet")
    return res


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    print(run().round(1).to_string())
