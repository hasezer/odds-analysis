"""First look: five analyses on the complete seasons (2024/25, 2025/26, 2026/27 so far; 2024, 2025, 2026 so far).

Run:  python analysis/first_look.py
Writes analysis/output/*.png and analysis/output/first_look.xlsx.

Conventions
- Only rows with in_default_analysis = true and a closing price are used (settled, not the special Japan 2026 season).
- "Bet" = 1 unit stake at Nesine's closing odds. ROI = profit / stake (−0.10 = you lose 10 % of what you stake).
- Uncertainty: a match carries many correlated selections, so standard errors are clustered by match
  (each match counts as one independent observation).
- Discovery vs check: 2024/25 + 2024 is the "discovery" period; 2025/26, 2026/27, 2025, 2026 is the "check" period.
"""
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load  # noqa: E402

OUT = Path(__file__).resolve().parent / "output"
OUT.mkdir(exist_ok=True)

DISCOVERY = {"2024/25", "2024"}

# When only one selection of a market is priced, analysis_flat treats the market as complete: fair_prob = 1.0 and a
# negative market_margin. Mostly "both halves" / "either half" markets where only "Yes" is stored (~16,000 matches).
# Such one-sided markets are left out of the fair-probability and margin checks (they still count as bets).

# Chart style (reference palette, light surface)
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE, AQUA, RED, GRAY = "#2a78d6", "#eb6834", "#1baf7a", "#e34948", "#a3a29c"
plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 12,
    "axes.titlesize": 15, "axes.titleweight": "bold", "axes.titlelocation": "left",
})

MARKET_NAMES = {
    "1X2": "Match result (1X2)", "DC": "Double chance", "OU": "Goals over/under", "BTTS": "Both teams score",
    "HT_1X2": "1st-half result", "2H_1X2": "2nd-half result", "HT_OU": "1st-half goals over/under",
    "TEAM_OU_HOME": "Home team goals o/u", "TEAM_OU_AWAY": "Away team goals o/u",
    "HT_BTTS": "1st-half both score", "2H_BTTS": "2nd-half both score", "HT_2H_BTTS": "Both score in 1st/2nd half",
    "HT_TEAM_OU_HOME": "1st-half home goals o/u", "HT_TEAM_OU_AWAY": "1st-half away goals o/u",
    "1X2_AND_OU": "Result + goals o/u", "1X2_AND_BTTS": "Result + both score", "OU_AND_BTTS": "2.5 goals + both score",
    "HT_1X2_AND_HT_BTTS": "1st-half result + both score", "HT_1X2_AND_HT_OU": "1st-half result + goals",
    "GOAL_RANGE": "Total goals range", "BOTH_HALVES_OVER": "Both halves over 1.5", "HT_FT": "Half-time/full-time",
    "TEAM_WIN_BOTH_HALVES_HOME": "Home wins both halves", "TEAM_WIN_BOTH_HALVES_AWAY": "Away wins both halves",
    "TEAM_WIN_EITHER_HALF_HOME": "Home wins either half", "TEAM_WIN_EITHER_HALF_AWAY": "Away wins either half",
    "CORNERS_OU": "Corners over/under", "CORRECT_SCORE": "Correct score", "HT_CORRECT_SCORE": "1st-half correct score",
}


def get_data() -> pd.DataFrame:
    f = load.flat()
    f = f[f["in_default_analysis"] & f["closing_odds"].notna()].copy()
    f["hit"] = f["hit"].astype(bool)
    f["profit"] = np.where(f["hit"], f["closing_odds"] - 1.0, -1.0)
    f["period"] = np.where(f["season"].isin(DISCOVERY), "discovery", "check")
    f["market"] = f["market_key"].map(MARKET_NAMES).fillna(f["market_key"])
    priced = f.groupby(["match_id", "market_type_id", "line"], dropna=False)["closing_odds"].transform("size")
    f["two_sided"] = priced >= 2
    return f


def roi_table(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """ROI per group, with a standard error clustered by match."""
    g = df.groupby(by + ["match_id"], observed=True).agg(p=("profit", "sum"), n=("profit", "size")).reset_index()
    rows = []
    for key, d in g.groupby(by, observed=True):
        stake, profit, k = d["n"].sum(), d["p"].sum(), len(d)
        roi = profit / stake
        se = np.sqrt(k / max(k - 1, 1) * ((d["p"] - roi * d["n"]) ** 2).sum()) / stake if k > 1 else np.nan
        rows.append((*(key if isinstance(key, tuple) else (key,)), k, int(stake), roi, se))
    out = pd.DataFrame(rows, columns=by + ["matches", "bets", "roi", "roi_se"])
    out["roi_low"] = out["roi"] - 1.96 * out["roi_se"]
    out["roi_high"] = out["roi"] + 1.96 * out["roi_se"]
    return out


def pct(x):
    return (x * 100).round(1)


# ---------------------------------------------------------------- 1. Are the odds honest? (calibration)
def calibration(f: pd.DataFrame):
    c = f[f["fair_prob"].notna() & f["two_sided"]].copy()
    bins = [0, .05, .10, .15, .20, .25, .30, .35, .40, .45, .50, .55, .60, .65, .70, .75, .80, .85, .90, .95, 1.0]
    c["bin"] = pd.cut(c["fair_prob"], bins, include_lowest=True)

    def summarise(d, by):
        return d.groupby(by, observed=True).agg(
            selections=("hit", "size"), matches=("match_id", "nunique"),
            expected=("fair_prob", "mean"), actual=("hit", "mean")).reset_index()

    overall = summarise(c, ["bin"])
    by_family = summarise(c, ["family", "bin"])
    one_x_two = summarise(c[c["market_key"] == "1X2"], ["bin"])

    # Per-market summary: how far off is the market on average (Brier-style check, in percentage points)
    c["gap"] = c["hit"].astype(float) - c["fair_prob"]
    mk = c.groupby("market", observed=True).agg(selections=("hit", "size"), matches=("match_id", "nunique")).reset_index()
    # mean absolute calibration error per market (selection-weighted over bins)
    mb = c.groupby(["market", "bin"], observed=True).agg(n=("hit", "size"), e=("fair_prob", "mean"), a=("hit", "mean")).reset_index()
    mb["w"] = mb["n"] / mb.groupby("market")["n"].transform("sum")
    mk["mean_abs_bin_gap"] = mk["market"].map((mb.assign(x=(mb["a"] - mb["e"]).abs() * mb["w"])).groupby("market")["x"].sum())

    fig, axes = plt.subplots(1, 2, figsize=(13, 6.2))
    for ax, d, title in [(axes[0], overall, "All markets"), (axes[1], one_x_two, "Match result (1X2) only")]:
        ax.plot([0, 1], [0, 1], color=GRAY, lw=1.5, ls="--", zorder=1)
        ax.plot(d["expected"], d["actual"], color=BLUE, lw=2, zorder=2)
        ax.scatter(d["expected"], d["actual"], s=60, color=BLUE, edgecolor=SURFACE, linewidth=2, zorder=3)
        ax.set_xlim(0, 1); ax.set_ylim(0, 1)
        ax.set_xticks(np.arange(0, 1.01, .2)); ax.set_yticks(np.arange(0, 1.01, .2))
        ax.set_xticklabels([f"{int(x*100)}%" for x in np.arange(0, 1.01, .2)])
        ax.set_yticklabels([f"{int(x*100)}%" for x in np.arange(0, 1.01, .2)])
        ax.set_xlabel("Chance according to the odds (cut removed)")
        ax.set_title(title, fontsize=13)
        ax.text(.62, .52, "perfectly honest\nodds = dashed line", color=INK2, fontsize=10)
    axes[1].text(.80, .985, "few matches", color=INK2, fontsize=9, ha="right", va="top")
    axes[0].set_ylabel("How often it actually happened")
    fig.suptitle("1. The odds predict outcomes almost perfectly", x=.06, ha="left", fontsize=16, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, .95))
    fig.savefig(OUT / "1_calibration.png", dpi=150)
    plt.close(fig)

    for d in (overall, by_family, one_x_two):
        d["bin"] = d["bin"].astype(str)
        d["expected"] = pct(d["expected"]); d["actual"] = pct(d["actual"])
        d["difference_pts"] = (d["actual"] - d["expected"]).round(1)
    mk["mean_abs_bin_gap"] = pct(mk["mean_abs_bin_gap"])
    mk = mk.rename(columns={"mean_abs_bin_gap": "avg_miss_pts"}).sort_values("avg_miss_pts")
    return overall, one_x_two, by_family, mk


# ---------------------------------------------------------------- 2. Where is the cut lowest? (margin)
def margins(f: pd.DataFrame):
    # one margin per match x market x line (complete markets only); the broken "wins both halves" rows have margin < 0
    m = f[f["market_margin"].notna() & f["two_sided"]]
    m = m.drop_duplicates(["match_id", "market_type_id", "line"])
    m = m.assign(payback=1 / (1 + m["market_margin"]))

    by_market = m.groupby("market").agg(markets=("payback", "size"), payback=("payback", "median")).reset_index()
    by_market["payback_pct"] = pct(by_market["payback"]); by_market["cut_pct"] = (100 - by_market["payback_pct"]).round(1)
    by_market = by_market.drop(columns="payback").sort_values("payback_pct", ascending=False)

    main = m[m["market_key"] == "1X2"]
    by_league = main.groupby("league_id").agg(matches=("payback", "size"), payback=("payback", "median")).reset_index()
    ou = m[(m["market_key"] == "OU") & (m["line"] == 2.5)].groupby("league_id")["payback"].median()
    by_league["payback_1x2_pct"] = pct(by_league.pop("payback"))
    by_league["payback_ou25_pct"] = pct(by_league["league_id"].map(ou))
    by_league = by_league.sort_values("payback_1x2_pct", ascending=False)

    by_season = main.groupby("season")["payback"].median().map(lambda x: round(x * 100, 1)).reset_index(name="payback_1x2_pct")

    fig, ax = plt.subplots(figsize=(11, 10))
    d = by_market.sort_values("payback_pct")
    ax.barh(d["market"], d["payback_pct"], color=BLUE, height=.7)
    for y, v in enumerate(d["payback_pct"]):
        ax.text(v + .5, y, f"{v:.0f}%", va="center", fontsize=10, color=INK2)
    ax.set_xlim(0, 100); ax.grid(axis="y", visible=False)
    ax.set_xlabel("Money paid back on average (100% = no cut). Typical match, median.")
    ax.set_title("2. How much of your stake comes back, by market")
    fig.tight_layout()
    fig.savefig(OUT / "2_payback_by_market.png", dpi=150)
    plt.close(fig)
    return by_market, by_league, by_season


# ---------------------------------------------------------------- 3. Favourites vs long shots
ODDS_BINS = [1.0, 1.3, 1.6, 2.0, 2.5, 3.0, 4.0, 5.0, 7.0, 10.0, 15.0, 25.0, 50.0, 1000.0]
ODDS_LABELS = ["1.01–1.30", "1.31–1.60", "1.61–2.00", "2.01–2.50", "2.51–3.00", "3.01–4.00", "4.01–5.00",
               "5.01–7.00", "7.01–10", "10.01–15", "15.01–25", "25.01–50", "50+"]


def longshots(f: pd.DataFrame):
    d = f.assign(odds_band=pd.cut(f["closing_odds"], ODDS_BINS, labels=ODDS_LABELS))
    allm = roi_table(d, ["odds_band"])
    by_family = roi_table(d, ["family", "odds_band"])
    x12 = roi_table(d[d["market_key"] == "1X2"], ["odds_band"])

    fig, ax = plt.subplots(figsize=(12, 6.5))
    y = allm["roi"] * 100
    err = np.vstack([y - allm["roi_low"] * 100, allm["roi_high"] * 100 - y])
    ax.bar(range(len(allm)), y, color=BLUE, width=.7)
    ax.errorbar(range(len(allm)), y, yerr=err, fmt="none", ecolor=INK2, elinewidth=1.2, capsize=3)
    for i, v in enumerate(y):
        ax.text(i, min(v, 0) - 3, f"{v:.0f}%", ha="center", va="top", fontsize=10, color=INK2)
    ax.axhline(0, color=INK2, lw=1)
    ax.set_xticks(range(len(allm)), allm["odds_band"].astype(str), rotation=40, ha="right")
    ax.set_ylim(min(y.min() - 12, -60), 5)
    ax.grid(axis="x", visible=False)
    ax.set_xlabel("Closing odds of the bet")
    ax.set_ylabel("Return per bet (−20% = lose 20 TL per 100 TL)")
    ax.set_title("3. The longer the odds, the more you lose")
    ax.text(len(allm) - .5, 2, "all markets · black lines = 95% range", ha="right", fontsize=10, color=INK2)
    fig.tight_layout()
    fig.savefig(OUT / "3_return_by_odds.png", dpi=150)
    plt.close(fig)
    for t in (allm, x12, by_family):
        for c in ("roi", "roi_low", "roi_high"):
            t[c] = pct(t[c])
        t.drop(columns="roi_se", inplace=True)
    return allm, x12, by_family


# ---------------------------------------------------------------- 4. Simple strategies
def strategies(f: pd.DataFrame):
    sel = {}
    x = f[f["market_key"] == "1X2"]
    sel["Home win"] = x[x["selection_key"] == "1"]
    sel["Draw"] = x[x["selection_key"] == "X"]
    sel["Away win"] = x[x["selection_key"] == "2"]
    fav_idx = x.groupby("match_id")["closing_odds"].idxmin()
    dog_idx = x[x["selection_key"] != "X"].groupby("match_id")["closing_odds"].idxmax()
    sel["Favourite wins"] = x.loc[fav_idx]
    sel["Underdog wins"] = x.loc[dog_idx]
    fav = x.loc[fav_idx]
    sel["Strong favourite (odds ≤ 1.50)"] = fav[fav["closing_odds"] <= 1.5]
    ou = f[(f["market_key"] == "OU") & (f["line"] == 2.5)]
    sel["Over 2.5 goals"] = ou[ou["selection_key"] == "OVER"]
    sel["Under 2.5 goals"] = ou[ou["selection_key"] == "UNDER"]
    bt = f[f["market_key"] == "BTTS"]
    sel["Both teams score: yes"] = bt[bt["selection_key"] == "YES"]
    sel["Both teams score: no"] = bt[bt["selection_key"] == "NO"]
    ht = f[f["market_key"] == "HT_1X2"]
    sel["1st half draw"] = ht[ht["selection_key"] == "X"]
    # corners: the match's main line = the line whose OVER/UNDER prices are closest to each other
    co = f[f["market_key"] == "CORNERS_OU"]
    piv = co.pivot_table(index=["match_id", "line"], columns="selection_key", values="closing_odds").dropna()
    main_line = (piv["OVER"] - piv["UNDER"]).abs().groupby(level=0).idxmin().map(lambda t: t[1])
    co = co[co["line"] == co["match_id"].map(main_line)]
    sel["Corners over (main line)"] = co[co["selection_key"] == "OVER"]
    sel["Corners under (main line)"] = co[co["selection_key"] == "UNDER"]
    cs = f[f["market_key"] == "CORRECT_SCORE"]
    sel["Correct score 0-0"] = cs[cs["selection_key"] == "0-0"]
    sel["Correct score 1-1"] = cs[cs["selection_key"] == "1-1"]

    s = pd.concat([d.assign(strategy=k) for k, d in sel.items()])
    order = list(sel)
    overall = roi_table(s, ["strategy"])
    per_period = roi_table(s, ["strategy", "period"])
    per_season = roi_table(s, ["strategy", "season"])
    per_league = roi_table(s, ["strategy", "league_id", "period"])

    # Discovery -> check: pick every strategy x league that made money in the discovery period, see how it did later
    pl = per_league.pivot_table(index=["strategy", "league_id"], columns="period", values=["roi", "bets"]).reset_index()
    pl.columns = ["strategy", "league_id", "bets_check", "bets_discovery", "roi_check", "roi_discovery"]
    winners = pl[(pl["roi_discovery"] > 0) & pl["roi_check"].notna()].sort_values("roi_discovery", ascending=False)
    combined = s.merge(winners[["strategy", "league_id"]], on=["strategy", "league_id"])
    winners_total = roi_table(combined, ["period"])

    fig, ax = plt.subplots(figsize=(12, 8))
    pp = per_period.pivot(index="strategy", columns="period", values="roi").reindex(order[::-1]) * 100
    yy = np.arange(len(pp))
    ax.barh(yy + .2, pp["discovery"], height=.38, color=BLUE, label="2024/25 + 2024")
    ax.barh(yy - .2, pp["check"], height=.38, color=ORANGE, label="2025/26, 2026/27, 2025, 2026")
    ax.set_yticks(yy, pp.index)
    ax.axvline(0, color=INK2, lw=1)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Return per bet (−10% = lose 10 TL per 100 TL staked)")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, frameon=False, fontsize=11)
    ax.set_title("4. Every simple strategy loses money", pad=34)
    fig.tight_layout()
    fig.savefig(OUT / "4_strategies.png", dpi=150)
    plt.close(fig)

    for t in (overall, per_period, per_season, per_league, winners_total):
        for c in ("roi", "roi_low", "roi_high"):
            t[c] = pct(t[c])
        t.drop(columns="roi_se", inplace=True)
    overall["strategy"] = pd.Categorical(overall["strategy"], order); overall = overall.sort_values("strategy")
    winners[["roi_discovery", "roi_check"]] = pct(winners[["roi_discovery", "roi_check"]])
    return overall, per_season, per_league, winners, winners_total


# ---------------------------------------------------------------- 5. League personalities
def leagues(f: pd.DataFrame):
    picks = {
        "Over 2.5 goals": (f["market_key"] == "OU") & (f["line"] == 2.5) & (f["selection_key"] == "OVER"),
        "Draw": (f["market_key"] == "1X2") & (f["selection_key"] == "X"),
        "Home win": (f["market_key"] == "1X2") & (f["selection_key"] == "1"),
        "Both teams score": (f["market_key"] == "BTTS") & (f["selection_key"] == "YES"),
        "Corners over 9.5": (f["market_key"] == "CORNERS_OU") & (f["line"] == 9.5) & (f["selection_key"] == "OVER"),
    }
    rows = []
    for name, mask in picks.items():
        d = f[mask & f["fair_prob"].notna() & f["two_sided"]]
        for (lg, per), g in d.groupby(["league_id", "period"]):
            rows.append((lg, per, name, len(g), g["fair_prob"].mean(), g["hit"].mean()))
        for lg, g in d.groupby("league_id"):
            rows.append((lg, "all", name, len(g), g["fair_prob"].mean(), g["hit"].mean()))
    t = pd.DataFrame(rows, columns=["league_id", "period", "measure", "matches", "expected", "actual"])
    t["diff_pts"] = (t["actual"] - t["expected"]) * 100
    # standard error of the difference (binomial, matches independent)
    t["se_pts"] = np.sqrt(t["expected"] * (1 - t["expected"]) / t["matches"]) * 100

    allp = t[t["period"] == "all"].pivot(index="league_id", columns="measure", values="diff_pts")[list(picks)]
    allp = allp.loc[allp.abs().max(axis=1).sort_values(ascending=False).index]

    # Did a league's surprise in the discovery period repeat in the check period?
    wide = t[t["period"] != "all"].pivot_table(index=["league_id", "measure"], columns="period", values="diff_pts").dropna().reset_index()
    repeat = wide.groupby("measure").apply(lambda g: pd.Series({
        "leagues": len(g),
        "correlation": round(g["discovery"].corr(g["check"]), 2),
        "same_direction_pct": round(((g["discovery"] > 0) == (g["check"] > 0)).mean() * 100),
    }), include_groups=False).reset_index()

    # heatmap
    from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
    cmap = LinearSegmentedColormap.from_list("div", ["#184f95", "#6da7ec", "#f0efec", "#ee8a89", "#b52d2d"])
    lim = 8
    fig, ax = plt.subplots(figsize=(10, 12))
    ax.imshow(allp.values, cmap=cmap, norm=TwoSlopeNorm(0, -lim, lim), aspect="auto")
    ax.set_xticks(range(allp.shape[1]), allp.columns, rotation=20, ha="right")
    ax.set_yticks(range(allp.shape[0]), allp.index)
    ax.grid(False)
    for i in range(allp.shape[0]):
        for j in range(allp.shape[1]):
            v = allp.values[i, j]
            if np.isnan(v):
                ax.text(j, i, "–", ha="center", va="center", color=INK2, fontsize=10)
                continue
            ax.text(j, i, f"{v:+.1f}", ha="center", va="center", fontsize=10,
                    color="white" if abs(v) > lim * .6 else INK)
    ax.set_title("5. Where leagues beat the odds' expectation\n(percentage points: actual − expected, all seasons)",
                 fontsize=14)
    ax.set_xlabel("red = happened more often than the odds said · blue = less often · – = line not offered",
                  fontsize=10, color=INK2)
    for s in ax.spines.values():
        s.set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT / "5_league_surprises.png", dpi=150)
    plt.close(fig)

    t[["expected", "actual"]] = pct(t[["expected", "actual"]])
    t[["diff_pts", "se_pts"]] = t[["diff_pts", "se_pts"]].round(1)
    return allp.round(1).reset_index(), t, repeat


def main():
    f = get_data()
    print(f"{f['match_id'].nunique():,} matches, {len(f):,} priced settled selections")
    cal_all, cal_1x2, cal_fam, cal_mk = calibration(f)
    m_mk, m_lg, m_season = margins(f)
    ls_all, ls_1x2, ls_fam = longshots(f)
    st_all, st_season, st_league, st_winners, st_winners_total = strategies(f)
    lg_heat, lg_detail, lg_repeat = leagues(f)

    sheets = {
        "1 Honest odds - all": cal_all, "1 Honest odds - 1X2": cal_1x2, "1 By market": cal_mk, "1 By family": cal_fam,
        "2 Payback by market": m_mk, "2 Payback by league": m_lg, "2 Payback by season": m_season,
        "3 Return by odds": ls_all, "3 Return by odds - 1X2": ls_1x2, "3 By family": ls_fam,
        "4 Strategies": st_all, "4 By season": st_season, "4 By league": st_league,
        "4 Discovery winners": st_winners, "4 Winners later": st_winners_total,
        "5 League surprises": lg_heat, "5 Did it repeat": lg_repeat, "5 Detail": lg_detail,
    }
    with pd.ExcelWriter(OUT / "first_look.xlsx", engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.sheets[name[:31]]
            ws.freeze_panes = "A2"
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = max(10, min(32, max(len(str(c.value or "")) for c in col) + 2))

    for name in ["1 By market", "2 Payback by league", "3 Return by odds", "3 Return by odds - 1X2", "4 Strategies",
                 "4 Winners later", "5 Did it repeat", "1 Honest odds - all"]:
        print(f"\n== {name}\n{sheets[name].to_string(index=False)}")
    print("\n== 4 per season\n", st_season.pivot(index="strategy", columns="season", values="roi").to_string())
    print("\n== 4 Discovery winners (top 15)\n", st_winners.head(15).to_string(index=False))
    print("\n== 5 heat\n", lg_heat.to_string(index=False))


if __name__ == "__main__":
    main()
