"""Live tables by minute, from the match events (goals with minutes). A PREVIEW until events cover more matches.

The collector has match events (goals, cards, substitutions) for only a few hundred matches so far, mostly 2026/27
and 2026. Only matches whose goal events add up exactly to the final score are used (extra-time and incomplete
timelines drop out). Re-run as events build up; below MIN_MATCHES per row the numbers are only a preview.
Tables:
1. when goals come: share of goals per 15 minutes (stoppage time counted in its half);
2. score state at minute 30 / 45 (half time) / 60 / 70 / 75 / 80 / 85 (level, one-goal lead, two+ lead): how often
   another goal comes, how often the result at that minute stands, and how often the leader wins; next to the chance of
   another goal from the pre-match goal rates (bb_data: the four goal rates from Nesine's goal and result markets,
   spread evenly over the remaining minutes of each half);
3. red cards: goals per match after a red card, by the side down to ten and its opponent.
Writes cache/live_minutes.parquet.

    python analysis/live_minutes.py
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bb_data  # noqa: E402
import load  # noqa: E402

CACHE = bb_data.CACHE
MIN_MATCHES = 300
GOALS = ["goal", "penalty_goal"]
CHECKPOINTS = [30, 45, 60, 70, 75, 80, 85]


def timelines():
    """One row per goal (minute, scoring side) for matches whose goal events reproduce the final score."""
    e = load._read("events")
    m = load.matches()
    m = m[(m["status"] == "finished") & m["ft_home"].notna() & m["ht_home"].notna()]
    g = e[e["event_type"].isin(GOALS + ["own_goal"])].copy()
    # own goals: score_after tells which side gained; for other goals the scorer's side scores
    g["side"] = g["team_side"]
    sa = g["score_after"].str.split("-", expand=True).apply(pd.to_numeric, errors="coerce")
    g["h_after"], g["a_after"] = sa[0], sa[1]
    g = g.sort_values(["match_id", "event_order"])
    prev_h = g.groupby("match_id")["h_after"].shift(1).fillna(0)
    og = g["event_type"] == "own_goal"
    g.loc[og, "side"] = np.where(g.loc[og, "h_after"] > prev_h[og], "home", "away")
    g["half"] = np.where(g["minute"] <= 45, 1, 2)
    cnt = g.groupby(["match_id", "side"]).size().unstack(fill_value=0).reindex(columns=["home", "away"],
                                                                             fill_value=0)
    h1 = g[g["half"] == 1].groupby(["match_id", "side"]).size().unstack(fill_value=0).reindex(
        columns=["home", "away"], fill_value=0)
    x = m.set_index("match_id")[["league_id", "season", "ft_home", "ft_away", "ht_home", "ht_away"]]
    x = x[x.index.isin(e["match_id"])].join(cnt).join(h1, rsuffix="_h1").fillna(0)
    ok = ((x["ft_home"] == x["home"]) & (x["ft_away"] == x["away"]) & (x["ht_home"] == x["home_h1"])
          & (x["ht_away"] == x["away_h1"]))
    print(f"matches with events: {len(x)}; timelines matching the final and half-time score: {int(ok.sum())}")
    keep = x[ok].index
    return x.loc[keep], g[g["match_id"].isin(keep)], e[e["match_id"].isin(keep)]


def when_goals(g):
    bins = [0, 15, 30, 45, 60, 75, 200]
    labs = ["1-15", "16-30", "31-45+", "46-60", "61-75", "76-90+"]
    seg = pd.cut(g["minute"], bins, labels=labs)
    out = seg.value_counts(normalize=True).reindex(labs).mul(100).rename("share of goals %").reset_index()
    return out.rename(columns={"minute": "minutes"})


def states(x, g, rates):
    rows = []
    for t in CHECKPOINTS:
        before = g[g["minute"] <= t] if t != 45 else g[g["half"] == 1]
        sc = before.groupby(["match_id", "side"]).size().unstack(fill_value=0).reindex(
            index=x.index, columns=["home", "away"], fill_value=0)
        d = x[["ft_home", "ft_away"]].join(sc).join(rates)
        diff = d["home"] - d["away"]
        lead = diff.abs()
        state = np.where(lead == 0, "level", np.where(lead == 1, "one-goal lead", "two+ goal lead"))
        more = (d["ft_home"] + d["ft_away"]) > (d["home"] + d["away"])
        fin = np.sign(d["ft_home"] - d["ft_away"])
        stands = fin == np.sign(diff)
        # pre-match chance of another goal: rates spread evenly over the remaining minutes of each half
        rem1 = np.clip(45 - t, 0, 45) / 45
        rem2 = np.clip(90 - max(t, 45), 0, 45) / 45
        lam = (d["lam_h1"] + d["lam_a1"]) * rem1 + (d["lam_h2"] + d["lam_a2"]) * rem2
        exp_more = 1 - np.exp(-lam)
        for s in ("level", "one-goal lead", "two+ goal lead"):
            k = state == s
            n = int(k.sum())
            if n == 0:
                continue
            r = {"minute": t, "state": s, "matches": n, "another goal %": more[k].mean() * 100,
                 "another goal, pre-match rates %": exp_more[k].mean() * 100,
                 "result at that minute stands %": stands[k].mean() * 100}
            if s != "level":
                r["leader wins %"] = r["result at that minute stands %"]
                r["leader does not lose %"] = (fin[k] * np.sign(diff[k]) >= 0).mean() * 100
            r["preview only"] = n < MIN_MATCHES
            rows.append(r)
    return pd.DataFrame(rows)


def red_cards(x, g, e):
    reds = e[e["event_type"].isin(["red", "second_yellow"])].sort_values("minute").groupby("match_id").first()
    rows = []
    for mid, r in reds.iterrows():
        after = g[(g["match_id"] == mid) & (g["minute"] > r["minute"])]
        left = max(90 - r["minute"], 1)
        rows.append({"match_id": mid, "minute": r["minute"], "ten men goals": (after["side"] == r["team_side"]).sum(),
                     "opponent goals": (after["side"] != r["team_side"]).sum(), "minutes left": left})
    d = pd.DataFrame(rows)
    if d.empty:
        return d
    return pd.DataFrame([{"red cards": len(d), "average minute": d["minute"].mean(),
                          "goals per 90 by the side with ten": d["ten men goals"].sum() / d["minutes left"].sum() * 90,
                          "goals per 90 by the opponent": d["opponent goals"].sum() / d["minutes left"].sum() * 90,
                          "preview only": len(d) < MIN_MATCHES}])


def run():
    x, g, e = timelines()
    b = bb_data.build()
    rates = b[b["fit_rmse"] < 0.05].set_index("match_id")[["lam_h1", "lam_a1", "lam_h2", "lam_a2"]]
    x = x[x.index.isin(rates.index)]
    g = g[g["match_id"].isin(x.index)]
    print(f"with pre-match goal rates: {len(x)} matches, {len(g)} goals")
    if len(x) < MIN_MATCHES:
        print(f"PREVIEW: fewer than {MIN_MATCHES} matches; differences of 10 points are still within luck")
    W, S, R = when_goals(g), states(x, g, rates), red_cards(x, g, e)
    out = pd.concat([W.assign(table="when goals come"), S.assign(table="score at minute"),
                     R.assign(table="red cards")], ignore_index=True)
    out.to_parquet(CACHE / "live_minutes.parquet")
    pd.set_option("display.width", 250)
    for t in ("when goals come", "score at minute", "red cards"):
        print(f"\n== {t}")
        print(out[out["table"] == t].dropna(axis=1, how="all").drop(columns="table").round(1).to_string(index=False))
    return out


if __name__ == "__main__":
    run()
