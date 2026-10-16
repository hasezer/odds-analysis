"""Tipster rule 5 by league: does a high "Total goals 0-1" price make 6+ goals more likely, league by league?

For each league: 6+ goals by 0-1 odds band and by 0-1 odds threshold (> 4, 4.5, 5, 5.5, 6, 7), per season:
matches, hit rate, the league's normal 6+ rate, hit rate needed to break even at the 6+ odds paid, return per 100.
"Made money every season": >= 15 bets in each season and return > 0 in all three. Luck control: the same count with
league labels shuffled across matches within each season (50 runs).
Writes output/rule5_by_league.xlsx and output/rule5_by_league.png (6+ hit rate heatmap).
"""
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rule_tester as rt  # noqa: E402
from dashboard import leagues  # noqa: E402

OUT = Path(__file__).resolve().parent / "output"
BANDS = [0, 3.5, 4.0, 4.5, 5.0, 6.0, 7.0, 8.5, 100]
BLAB = ["≤ 3.50", "3.50–4.00", "4.00–4.50", "4.50–5.00", "5.00–6.00", "6.00–7.00", "7.00–8.50", "> 8.50"]
THR = [4.0, 4.5, 5.0, 5.5, 6.0, 7.0]
SEAS = ["2024/25", "2025/26", "2026/27"]


def table(d, key):
    """Per (league, key-cell): stats per season and over all seasons."""
    rows = []
    for (lg, cell), g in d.groupby(["league", key], observed=True):
        row = {"league": lg, key: cell}
        for p in SEAS + ["all"]:
            x = g if p == "all" else g[g["period"] == p]
            n = len(x)
            row[f"matches {p}"] = n
            row[f"hit % {p}"] = x["hit"].mean() * 100 if n else np.nan
            row[f"return {p}"] = (x["hit"] * x["odds"] - 1).mean() * 100 if n else np.nan
        row["break-even %"] = (1 / g["odds"]).mean() * 100
        row["avg 6+ odds"] = g["odds"].mean()
        row["every season profitable"] = all(row[f"matches {p}"] >= 15 and row[f"return {p}"] > 0 for p in SEAS)
        rows.append(row)
    return pd.DataFrame(rows)


def count_profitable(d):
    n = 0
    for key in ("band", "thr"):
        x = d if key == "band" else d.dropna(subset=["thr"])
        t = table(x, key)
        n += int(t["every season profitable"].sum()) if len(t) else 0
    return n


def explode_thr(d):
    """One row per (match, threshold it passes): '0-1 > 4.0', '0-1 > 4.5', ..."""
    parts = []
    for t in THR:
        x = d[d["o01"] > t].copy()
        x["thr"] = f"0-1 odds > {t:.2f}"
        parts.append(x)
    return pd.concat(parts)


def run():
    W = rt.wide()
    names = leagues()
    d = pd.DataFrame({"league": W["league_id"].map(lambda l: names.get(l, {}).get("en", l)), "period": W["period"],
                      "o01": W["GOAL_RANGE||0-1"], "odds": W["GOAL_RANGE||6+"], "hit": rt.outcome(W, "GOAL_RANGE||6+")})
    d = d.dropna(subset=["o01", "odds", "hit"])
    d["band"] = pd.cut(d["o01"], BANDS, labels=BLAB)
    normal = d.groupby("league")["hit"].mean() * 100
    tb = table(d, "band")
    dt = explode_thr(d)
    tt = table(dt, "thr")
    for t in (tb, tt):
        t.insert(2, "league normal 6+ %", t["league"].map(normal))
    real = int(tb["every season profitable"].sum() + tt["every season profitable"].sum())
    rng = np.random.default_rng(5)
    luck = []
    for _ in range(50):
        s = d.copy()
        for p in SEAS:
            ix = s.index[s["period"] == p]
            s.loc[ix, "league"] = rng.permutation(s.loc[ix, "league"].to_numpy())
        luck.append(int(table(s, "band")["every season profitable"].sum() +
                        table(explode_thr(s), "thr")["every season profitable"].sum()))
    best = pd.concat([tb.rename(columns={"band": "cell"}), tt.rename(columns={"thr": "cell"})])
    best = best[best["every season profitable"]].sort_values("return all", ascending=False)
    allg = table(d.assign(league="ALL LEAGUES"), "band")
    with pd.ExcelWriter(OUT / "rule5_by_league.xlsx") as xw:
        pd.DataFrame({"Read me": [
            "6+ goals by 'Total goals 0-1' odds, per league and season. Return = per 100 staked on 6+ at Nesine's odds.",
            f"Cells that made money in every season (>= 15 bets each): {real}. With league labels shuffled "
            f"(pure luck, 50 runs): average {np.mean(luck):.1f}, most {max(luck)}.",
            "Break-even % = hit rate needed to break even at the 6+ odds paid in that cell."]}).to_excel(
            xw, sheet_name="Read me", index=False)
        allg.round(1).to_excel(xw, sheet_name="All leagues by band", index=False)
        best.round(1).to_excel(xw, sheet_name="Made money every season", index=False)
        tt.round(1).to_excel(xw, sheet_name="By league - thresholds", index=False)
        tb.round(1).to_excel(xw, sheet_name="By league - bands", index=False)
        for ws in xw.sheets.values():
            ws.set_column(0, 1, 26); ws.set_column(2, 30, 13)
    # heatmap: 6+ hit rate (all seasons) by league x band; cells with < 20 matches left blank
    hm = tb.pivot(index="league", columns="band", values="hit % all").reindex(columns=BLAB)
    nn = tb.pivot(index="league", columns="band", values="matches all").reindex(columns=BLAB)
    hm = hm.where(nn >= 20)
    hm = hm.loc[normal.sort_values(ascending=False).index]
    fig, ax = plt.subplots(figsize=(11, 10), facecolor="#fcfcfb")
    im = ax.imshow(hm.to_numpy(), cmap="Blues", vmin=0, vmax=35, aspect="auto")
    ax.set_xticks(range(len(BLAB)), BLAB, rotation=30, ha="right", fontsize=10)
    ax.set_yticks(range(len(hm)), [f"{l} ({normal[l]:.0f}%)" for l in hm.index], fontsize=9.5)
    for i in range(hm.shape[0]):
        for j in range(hm.shape[1]):
            v = hm.iat[i, j]
            if v == v:
                ax.text(j, i, f"{v:.0f}", ha="center", va="center", fontsize=8.5,
                        color="white" if v > 20 else "#0b0b0b")
    ax.set_xlabel("'Total goals 0-1' odds band", color="#52514e")
    ax.set_title("6+ goals hit rate (%) by league and 0-1 odds — all seasons (blank: < 20 matches)\n"
                 "league's normal 6+ rate in brackets", loc="left", fontsize=12.5, color="#0b0b0b", fontweight="bold")
    fig.colorbar(im, ax=ax, shrink=.6, label="6+ goals hit %")
    fig.tight_layout()
    fig.savefig(OUT / "rule5_by_league.png", dpi=150)
    return allg, best, tt, real, luck


if __name__ == "__main__":
    allg, best, tt, real, luck = run()
    pd.set_option("display.width", 250)
    print(f"made money every season: {real}; shuffled leagues: mean {np.mean(luck):.1f}, max {max(luck)}")
    print(allg[["band", "matches all", "hit % all", "break-even %", "return 2024/25", "return 2025/26",
                "return 2026/27", "return all"]].round(1).to_string())
    print(best[["league", "cell", "matches 2024/25", "matches 2025/26", "matches 2026/27", "hit % all",
                "league normal 6+ %", "break-even %", "return 2024/25", "return 2025/26", "return 2026/27"]]
          .round(1).to_string())
    top = tt[tt["thr"] == "0-1 odds > 5.00"].sort_values("hit % all", ascending=False)
    print(top[["league", "matches all", "hit % all", "league normal 6+ %", "break-even %", "return all"]].round(1)
          .head(12).to_string())
