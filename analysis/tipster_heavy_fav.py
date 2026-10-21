"""Tipster rule check: 'heavy favourite' games (about 1.50 / 4.00 / 5.00) end as a draw, HT/FT 1/X or 2/X.

Claim (Turkish tipster): when a team is priced a heavy favourite (favourite ~1.50, draw ~4.0, opponent ~5.0) but is
not in good form, the game ends level, with the favourite ahead at half time (HT/FT 1/0 or 2/0, Turkish 0 = draw).
Tested on Nesine's CLOSING 1X2 odds (opening odds are not in our data). Bands: favourite 1.40-1.60, draw 3.60-4.40,
opponent 4.30-5.70 (the favourite may be home or away). Bets: draw; favourite-leads-then-draw (1/X or 2/X); draw with
goals (1-1 or higher). Per season: hit rate vs the chance the odds imply and the break-even rate, return per 100;
baseline = all games with a favourite of the same price (1.40-1.60) outside the draw/opponent bands; and the form
filter: the favourite's points over its last 5 games (strictly earlier). Luck control: outcomes redrawn from the fair
chance. Writes output/tipster_heavy_fav.xlsx.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load  # noqa: E402
from htft3_data import PER  # noqa: E402

HERE = Path(__file__).resolve().parent
SEAS = {"A": "2024/25", "B": "2025/26", "C": "2026/27"}
FAV, DRAW, DOG = (1.40, 1.60), (3.60, 4.40), (4.30, 5.70)


def table():
    f = load.flat()
    h = f[(f["market_key"] == "1X2") & f["closing_odds"].notna() & f["in_default_analysis"]]
    o = h.pivot_table(index="match_id", columns="selection_key", values="closing_odds").dropna(subset=["1", "X", "2"])
    t = f[(f["market_key"] == "HT_FT") & f["closing_odds"].notna() & f["in_default_analysis"]]
    t = t.pivot_table(index="match_id", columns="selection_key", values="closing_odds")
    m = load.matches()
    m = m[(m["status"] == "finished") & m["ht_home"].notna() & m["ft_home"].notna()].copy()
    m["per"] = m["season"].map(PER)
    m = m[m["per"].notna() & m["match_id"].isin(o.index)].sort_values("kickoff_utc").reset_index(drop=True)
    m = m.join(o.rename(columns={"1": "o1", "X": "oX", "2": "o2"}), on="match_id")
    m = m.join(t[["1/X", "2/X"]].rename(columns={"1/X": "o1X", "2/X": "o2X"}), on="match_id")
    # points per team over its last 5 matches (strictly earlier; all matches in scope)
    rows = []
    for side, opp in (("home", "away"), ("away", "home")):
        g, a = m[f"ft_{side}"], m[f"ft_{opp}"]
        rows.append(pd.DataFrame({"mid": m["match_id"], "team": m[f"{side}_team_id"], "k": m["kickoff_utc"],
                                  "pts": np.where(g > a, 3, np.where(g == a, 1, 0))}))
    r = pd.concat(rows).sort_values(["team", "k"])
    r["form5"] = r.groupby("team")["pts"].transform(lambda v: v.shift(1).rolling(5, min_periods=5).sum())
    fm = r.set_index(["mid", "team"])["form5"]
    m["fav_side"] = np.where(m["o1"] < m["o2"], "home", "away")
    m["o_fav"] = np.where(m["fav_side"] == "home", m["o1"], m["o2"])
    m["o_dog"] = np.where(m["fav_side"] == "home", m["o2"], m["o1"])
    m["o_favX"] = np.where(m["fav_side"] == "home", m["o1X"], m["o2X"])
    fav_team = np.where(m["fav_side"] == "home", m["home_team_id"], m["away_team_id"])
    m["form5"] = [fm.get((a, b), np.nan) for a, b in zip(m["match_id"], fav_team)]
    ft = np.sign(m["ft_home"] - m["ft_away"])
    ht = np.sign(m["ht_home"] - m["ht_away"])
    favsign = np.where(m["fav_side"] == "home", 1, -1)
    m["draw"] = (ft == 0).astype(int)
    m["fav_lead_draw"] = ((ht == favsign) & (ft == 0)).astype(int)
    m["draw_goals"] = ((ft == 0) & (m["ft_home"] > 0)).astype(int)
    m["fav_win"] = (ft == favsign).astype(int)
    imp = 1 / m[["o1", "oX", "o2"]]
    m["p_draw"] = imp["oX"] / imp.sum(axis=1)
    return m


def summ(g, y, o, p):
    n = len(g)
    if n == 0:
        return {"games": 0}
    hit = g[y].mean()
    out = {"games": n, "won": int(g[y].sum()), "hit %": hit * 100, "chance the odds imply %": g[p].mean() * 100}
    if o:
        ok = g[o].notna()
        out["break-even % (1/odds)"] = (1 / g.loc[ok, o]).mean() * 100
        out["average odds"] = g.loc[ok, o].mean()
        out["return per 100"] = ((g.loc[ok, y] * g.loc[ok, o]).mean() - 1) * 100
    return out


def main():
    m = table()
    rule = m["o_fav"].between(*FAV) & m["oX"].between(*DRAW) & m["o_dog"].between(*DOG)
    same_fav = m["o_fav"].between(*FAV) & ~rule
    rows = []
    for label, sel in (("tipster combination (1.50 / 4.0 / 5.0)", rule), ("same favourite price, other draw/opponent odds", same_fav)):
        for per in ("all", *SEAS):
            g = m[sel & ((m["per"] == per) if per != "all" else True)]
            for bet, y, o in (("draw", "draw", "oX"), ("favourite leads at half time, ends level (1/0, 2/0)", "fav_lead_draw", "o_favX"),
                              ("draw with goals", "draw_goals", None), ("favourite wins", "fav_win", "o_fav")):
                s = summ(g.assign(_p=g["p_draw"]) if y == "draw" else g.assign(_p=np.nan), y, o, "_p")
                rows.append({"group": label, "season": SEAS.get(per, "all"), "bet": bet, **s})
    R = pd.DataFrame(rows)
    # form filter inside the tipster combination
    g = m[rule & m["form5"].notna()].copy()
    g["form"] = pd.cut(g["form5"], [-1, 4, 8, 11, 15], labels=["weak (0-4 pts of 15)", "average (5-8)", "good (9-11)", "excellent (12-15)"])
    F = []
    for form, gg in g.groupby("form", observed=True):
        F.append({"favourite's form, last 5": form, **summ(gg.assign(_p=gg["p_draw"]), "draw", "oX", "_p"),
                  "fav-leads-then-draw hit %": gg["fav_lead_draw"].mean() * 100,
                  "1/0-2/0 return per 100": ((gg["fav_lead_draw"] * gg["o_favX"]).mean() - 1) * 100})
    F = pd.DataFrame(F)
    # luck control: how often does a random 'draw' redrawn from the fair chance beat the observed return?
    rng = np.random.default_rng(1)
    g = m[rule & m["o_favX"].notna()]
    sims = []
    pF = g["p_draw"].to_numpy()
    for _ in range(2000):
        y = rng.random(len(g)) < pF
        sims.append(((y * g["oX"].to_numpy()).mean() - 1) * 100)
    obs = ((g["draw"] * g["oX"]).mean() - 1) * 100
    luck = {"games": len(g), "draw return observed": obs, "luck mean": np.mean(sims),
            "luck 95th pct": np.percentile(sims, 95), "share of luck runs >= observed %": (np.array(sims) >= obs).mean() * 100}
    out = HERE / "output" / "tipster_heavy_fav.xlsx"
    with pd.ExcelWriter(out) as xw:
        R.round(2).to_excel(xw, sheet_name="Rule vs baseline", index=False)
        F.round(2).to_excel(xw, sheet_name="By favourite's form", index=False)
        pd.DataFrame([luck]).round(2).to_excel(xw, sheet_name="Luck control", index=False)
        m[rule].assign(kickoff_utc=lambda d: d["kickoff_utc"].dt.tz_localize(None)).drop(
            columns=["ingested_at_utc"]).round(3).to_excel(xw, sheet_name="Every game", index=False)
    return m, R, F, luck, rule


if __name__ == "__main__":
    m, R, F, luck, rule = main()
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 20)
    print(R.round(1).to_string(index=False))
    print(F.round(1).to_string(index=False))
    print(luck)
    print("games in the combination:", int(rule.sum()), "of", len(m))
