"""BTTS in both halves: tables, Excel and charts from the cached steps (bb_data, bb_signs, bb_rules, bb_ml).

- ladders: hit rate by Nesine's own both-halves odds (2025/26 on) and by the chance from the goal markets (all seasons)
- fair race: every technique picks the same share of games (top 10 / 5 / 2%) inside each later season (2025/26,
  2026/27); hits pooled and compared with the normal rate. Two arenas: all games, and games with Nesine's own price.
- rules: the best confirmed rules, with the same number of games taken by the model / Nesine's own price; luck runs
- map: hit rate by home x away expected goals; live: after both scored in the 1st half; leagues; scorelines
Writes output/bb.xlsx and output/bb_1_ladders.png, bb_2_map.png, bb_3_fair_race.png.
"""
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bb_data  # noqa: E402
from bb_signs import SEAS  # noqa: E402
from htft3_report import BLUE, GRID, INK, INK2, SEQ, SURF, top_hits  # noqa: E402

OUT = Path(__file__).resolve().parent / "output"
LATER = ("B", "C")
SHARES = (0.10, 0.05, 0.02)
CALENDAR = ["kick_hour_tr", "weekday", "month", "season_day", "home_rest_days", "away_rest_days"]


def stats_model(d):
    """BTTS in both halves from each team's own last-20 goals per half (no odds): scored by one side and conceded
    by the other, averaged, as independent Poisson rates."""
    p = 1.0
    for side, opp in (("home", "away"), ("away", "home")):
        for h in (1, 2):
            lam = (d[f"{side}_t20_g{h}f"] + d[f"{opp}_t20_g{h}a"]) / 2
            p = p * (1 - np.exp(-lam))
    return p


def ladder(d, col, per_find, qs, label):
    o = d[col]
    cut = np.unique(np.round(np.nanquantile(o[d["per"] == per_find], qs), 3))
    cut[0], cut[-1] = -1e9, 1e9
    x = d[o.notna()].assign(b=pd.cut(o[o.notna()], cut))
    rows = []
    for iv, g in x.groupby("b", observed=True):
        lo, hi = iv.left, iv.right
        fmt = (lambda v: f"{v:.2f}") if col.startswith("o_") else (lambda v: f"{v * 100:.1f}%")
        band = (f"up to {fmt(hi)}" if lo < -1e8 else (f"over {fmt(lo)}" if hi > 1e8 else f"{fmt(lo)}-{fmt(hi)}"))
        r = {"by": label, "band": band, "games": len(g), "hit % (all)": g["y_bb"].mean() * 100}
        if col == "o_bb":
            r["break-even % (1/odds)"] = (1 / g["o_bb"]).mean() * 100
            r["return per 100"] = ((g["y_bb"] * g["o_bb"]).sum() / len(g) - 1) * 100
        for k, nm in SEAS.items():
            gg = g[g["per"] == k]
            r[f"hit % {nm}"] = gg["y_bb"].mean() * 100 if len(gg) else np.nan
            r[f"games {nm}"] = len(gg)
            if col == "o_bb" and len(gg):
                r[f"return per 100 {nm}"] = ((gg["y_bb"] * gg["o_bb"]).sum() / len(gg) - 1) * 100
        rows.append(r)
    return pd.DataFrame(rows)


def pick_best(d, cands, y, A):
    """The sign whose top 10% of 2024/25 games hit most often (same picking rule as the race)."""
    best = None
    for r in cands.itertuples():
        x = d[r.sign].to_numpy(float)
        x = x if r.direction == "high" else -x
        if np.isnan(x[A]).mean() > 0.7:
            continue
        h, n = top_hits(x[A], y[A], int(round(0.10 * A.sum())))
        if best is None or h / n > best[0]:
            best = (h / n, x, r.what)
    return best[1], best[2]


def fair_race(d, S, ML):
    """Every technique picks the top 10 / 5 / 2% of the games in each later season; hits pooled over both."""
    y = d["y_bb"].to_numpy(float)
    per = d["per"].to_numpy()
    A = per == "A"
    s = S[(S["target"] == "BTTS both halves") & (S["found on"] == "2024/25")]
    other, other_what = pick_best(d, s[~s["sign"].isin(["q_bb"])], y, A)
    lg, lg_what = pick_best(d, s[s["sign"].str.startswith("lg_")], y, A)
    cal, cal_what = pick_best(d, s[s["sign"].isin(CALENDAR)], y, A)
    ml = ML[ML["trained on"] == "2024/25"].set_index("match_id")
    lgt = ml["logistic (25 signs)"].reindex(d["match_id"]).to_numpy(float)
    gbt = ml["boosted trees (all signs)"].reindex(d["match_id"]).to_numpy(float)
    techs = {
        "Nesine's own both-halves price": (d["p_bb"].to_numpy(float), "HT_2H_BTTS YES/YES chance (2025/26 on)"),
        "chance from the goal markets (model)": (d["q_bb"].to_numpy(float),
                                                 "four goal rates fitted to team goals, total goals, 1X2 of each half"),
        "best other single sign (chosen on 2024/25)": (other, other_what),
        "machine learning: logistic": (lgt, "25 strongest signs, trained on 2024/25"),
        "machine learning: boosted trees": (gbt, "all ~440 signs, trained on 2024/25"),
        "team habits: both teams score in both halves": (
            (d["home_t20_sb"] * d["away_t20_sb"]).to_numpy(float),
            "each team's rate of scoring in both halves, last 20"),
        "statistics-only team model": (stats_model(d).to_numpy(float), "each team's last-20 goals per half, no odds"),
        "league history": (lg, lg_what),
        "calendar, kick-off time, rest days": (cal, cal_what)}
    rows = []
    arenas = (("all games", np.ones(len(d), bool)), ("games with Nesine's own price", d["p_bb"].notna().to_numpy()))
    for arena, base in arenas:
        for name, (sc, what) in techs.items():
            if name.startswith("Nesine") and arena == "all games":
                continue
            for share in SHARES:
                r = {"arena": arena, "technique": name, "sign used": what, "share": f"top {int(share * 100)}%"}
                H = N = E = 0.0
                for k in LATER:
                    m = (per == k) & base
                    n = int(round(share * m.sum()))
                    h, n = top_hits(sc[m], y[m], n)
                    nrm = y[m].mean()
                    r[f"games {SEAS[k]}"], r[f"hit % {SEAS[k]}"], r[f"normal % {SEAS[k]}"] = n, h / n * 100, nrm * 100
                    H, N, E = H + h, N + n, E + nrm * n
                r["games (both)"], r["hit % (both)"], r["x normal"] = int(N), H / N * 100, H / E
                rows.append(r)
    return pd.DataFrame(rows)


def rules_table(R, L):
    keep = ["found on", "pool", "rule", "criteria", "matches 2024/25", "hit % 2024/25", "matches 2025/26",
            "hit % 2025/26", "matches 2026/27", "hit % 2026/27", "model q_bb, same size, % 2025/26",
            "model q_bb, same size, % 2026/27", "own price, same size, % 2025/26", "own price, same size, % 2026/27",
            "normal % 2024/25", "normal % 2025/26", "normal % 2026/27"]
    best = R[R["confirmed"]].groupby(["found on", "pool"]).head(15)[keep]
    luck = L.groupby(["found on", "pool"])["confirmed"].agg(["mean", "max"]).rename(
        columns={"mean": "luck runs: average confirmed", "max": "luck runs: most"}).reset_index()
    real = R.groupby(["found on", "pool"])["confirmed"].sum().rename("real data: confirmed").reset_index()
    return best, real.merge(luck, on=["found on", "pool"])


def goals_map(d):
    x = d[d["lam_home"].notna()]
    A = x["per"] == "A"
    qh = np.nanquantile(x.loc[A, "lam_home"], [0, .2, .4, .6, .8, 1])
    qa = np.nanquantile(x.loc[A, "lam_away"], [0, .2, .4, .6, .8, 1])
    qh[0], qa[0], qh[-1], qa[-1] = 0, 0, 20, 20
    lab = lambda q: [f"under {q[1]:.2f}"] + [f"{q[i]:.2f}-{q[i + 1]:.2f}" for i in range(1, 4)] + [f"over {q[4]:.2f}"]
    x = x.assign(h=pd.cut(x["lam_home"], qh, labels=lab(qh), include_lowest=True),
                 a=pd.cut(x["lam_away"], qa, labels=lab(qa), include_lowest=True))
    hit = x.pivot_table(index="h", columns="a", values="y_bb", aggfunc="mean", observed=False) * 100
    n = x.pivot_table(index="h", columns="a", values="y_bb", aggfunc="size", observed=False)
    cells = x.groupby(["h", "a", "per"], observed=True)["y_bb"].agg(["mean", "size"]).unstack("per")
    cells.columns = [f"{'hit %' if a == 'mean' else 'games'} {SEAS[b]}" for a, b in cells.columns]
    for c in cells.columns:
        if c.startswith("hit"):
            cells[c] *= 100
    return hit, n, cells.reset_index().rename(columns={"h": "home expected goals", "a": "away expected goals"})


def live_table(d):
    b = d[d["y_b1"] == 1].copy()
    b["half-time score"] = b["ht_home"].astype(int).astype(str) + "-" + b["ht_away"].astype(int).astype(str)
    by_score = b.groupby("half-time score")["y_b2"].agg(games="size", rate="mean")
    by_score = by_score[by_score["games"] >= 40].sort_values("games", ascending=False)
    by_score["2nd-half BTTS %"] = by_score.pop("rate") * 100
    q = np.nanquantile(b["q_b2"], [0, .2, .4, .6, .8, 1])
    names = [f"{q[i] * 100:.0f}-{q[i + 1] * 100:.0f}%" for i in range(5)]
    b["pre-match 2nd-half BTTS chance (model)"] = pd.cut(b["q_b2"], q, labels=names, include_lowest=True)
    by_q = b.groupby("pre-match 2nd-half BTTS chance (model)", observed=True)["y_b2"].agg(games="size", rate="mean")
    by_q["2nd-half BTTS %"] = by_q.pop("rate") * 100
    by_season = b.groupby("per")["y_b2"].agg(games="size", rate="mean").rename(index=SEAS)
    by_season["2nd-half BTTS %"] = by_season.pop("rate") * 100
    return by_score.reset_index(), by_q.reset_index(), by_season.reset_index().rename(columns={"per": "season"})


def leagues(d):
    x = d[d["q_bb"].notna()]
    g = x.groupby(["league", "per"]).agg(games=("y_bb", "size"), hit=("y_bb", "mean"), model=("q_bb", "mean"))
    g = g.unstack("per")
    out = pd.DataFrame(index=g.index)
    for k, nm in SEAS.items():
        out[f"games {nm}"] = g[("games", k)]
        out[f"hit % {nm}"] = g[("hit", k)] * 100
        out[f"extra vs model {nm}"] = (g[("hit", k)] - g[("model", k)]) * 100
    t = x.groupby("league").agg(games=("y_bb", "size"), hit=("y_bb", "mean"), model=("q_bb", "mean"))
    out.insert(0, "model % (all)", t["model"] * 100)
    out.insert(0, "hit % (all)", t["hit"] * 100)
    out.insert(0, "games (all)", t["games"])
    return out.sort_values("hit % (all)", ascending=False).reset_index()


def scorelines(d):
    bb = d[d["y_bb"] == 1]
    ft = (bb["ft_home"].astype(int).astype(str) + "-" + bb["ft_away"].astype(int).astype(str)).value_counts()
    ht = (bb["ht_home"].astype(int).astype(str) + "-" + bb["ht_away"].astype(int).astype(str)).value_counts()
    return pd.DataFrame({"full-time score": ft.index, "games": ft.values, "share %": ft.values / ft.sum() * 100}), \
        pd.DataFrame({"half-time score": ht.index, "games": ht.values, "share %": ht.values / ht.sum() * 100})


def style(ax):
    ax.set_facecolor(SURF)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.grid(axis="y", color=GRID, lw=.8)
    ax.set_axisbelow(True)


def chart_ladders(lad_own, lad_model, normal_own, normal_all):
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.6), gridspec_kw={"width_ratios": [1, 1]})
    fig.patch.set_facecolor(SURF)
    for ax, lad, normal, title, xl in (
            (axes[0], lad_own, normal_own, "By Nesine's own odds (2025/26 and 2026/27)",
             "Nesine's odds for both teams to score in both halves (lowest on the left)"),
            (axes[1], lad_model, normal_all, "By the chance from the goal markets (all three seasons)",
             "chance from Nesine's goal markets (highest on the left)")):
        style(ax)
        v = lad["hit % (all)"].to_numpy()
        ax.bar(range(len(v)), v, color=BLUE, width=.6)
        ax.axhline(normal, color=INK2, lw=1)
        ax.text(len(v) - .5, normal, f"normal {normal:.1f}%", color=INK2, fontsize=9, va="bottom", ha="right")
        for i in (0, len(v) - 1):
            ax.text(i, v[i], f"{v[i]:.1f}%", ha="center", va="bottom", fontsize=10, color=INK)
        ax.set_xticks(range(len(v)), [b.replace("up to ", "≤ ").replace("over ", "> ") for b in lad["band"]],
                      rotation=30, ha="right")
        ax.set_ylim(0, max(v.max() * 1.25, normal * 1.6))
        ax.set_ylabel("happened, % of games", color=INK2)
        ax.set_xlabel(xl, color=INK2, fontsize=9)
        ax.set_title(title, color=INK, fontsize=11, loc="left")
    fig.suptitle("Both teams score in both halves: the more goals both sides are expected to score, the more often it "
                 "happens", color=INK, fontsize=13, x=.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, .94))
    fig.savefig(OUT / "bb_1_ladders.png", dpi=150, facecolor=SURF)
    plt.close(fig)


def chart_map(hit, n):
    fig, ax = plt.subplots(figsize=(9.5, 6.4))
    fig.patch.set_facecolor(SURF)
    M = hit.to_numpy(float)
    norm = plt.Normalize(0, 12)
    ax.imshow(M, cmap=SEQ, norm=norm, aspect="auto", origin="lower")
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            rgba = SEQ(norm(M[i, j]))
            lum = 0.2126 * rgba[0] + 0.7152 * rgba[1] + 0.0722 * rgba[2]
            ax.text(j, i, f"{M[i, j]:.1f}%\n{int(n.iloc[i, j]):,} games", ha="center", va="center", fontsize=9,
                    color="white" if lum < 0.5 else INK)
    ax.set_xticks(range(M.shape[1]), list(hit.columns), color=INK2, fontsize=9)
    ax.set_yticks(range(M.shape[0]), list(hit.index), color=INK2, fontsize=9)
    ax.set_xlabel("away team's expected goals (from Nesine's goal markets)", color=INK2)
    ax.set_ylabel("home team's expected goals", color=INK2)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xticks(np.arange(-.5, M.shape[1]), minor=True)
    ax.set_yticks(np.arange(-.5, M.shape[0]), minor=True)
    ax.grid(which="minor", color=SURF, lw=2)
    ax.tick_params(which="minor", length=0)
    ax.set_title("How often both teams score in both halves, by each team's expected goals (all seasons)\n"
                 "Both attacks must be good: one strong team is not enough", color=INK, fontsize=12, loc="left")
    fig.tight_layout()
    fig.savefig(OUT / "bb_2_map.png", dpi=150, facecolor=SURF)
    plt.close(fig)


def chart_race(race):
    rows = [("all games", t) for t in ["chance from the goal markets (model)",
                                       "best other single sign (chosen on 2024/25)", "machine learning: logistic",
                                       "machine learning: boosted trees",
                                       "team habits: both teams score in both halves",
                                       "statistics-only team model", "league history",
                                       "calendar, kick-off time, rest days"]] + \
           [("games with Nesine's own price", t) for t in ["Nesine's own both-halves price",
                                                           "chance from the goal markets (model)"]]
    cols = [f"top {int(s * 100)}%" for s in SHARES]
    M = np.full((len(rows), len(cols)), np.nan)
    for i, (arena, t) in enumerate(rows):
        g = race[(race["arena"] == arena) & (race["technique"] == t)].set_index("share")
        for j, c in enumerate(cols):
            M[i, j] = g.loc[c, "x normal"]
    labels = [t for a, t in rows[:-2]] + ["Nesine's own price (games where it exists)",
                                          "goal-markets model (the same games)"]
    fig, ax = plt.subplots(figsize=(11, 6.8))
    fig.patch.set_facecolor(SURF)
    norm = plt.Normalize(0.6, 2.6)
    ax.imshow(M, cmap=SEQ, norm=norm, aspect="auto")
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            rgba = SEQ(norm(M[i, j]))
            lum = 0.2126 * rgba[0] + 0.7152 * rgba[1] + 0.0722 * rgba[2]
            ax.text(j, i, f"{M[i, j]:.2f}x", ha="center", va="center", fontsize=10, color="white" if lum < 0.5 else INK)
    ax.set_xticks(range(len(cols)), [f"its {c} of games" for c in cols], color=INK2, fontsize=10)
    ax.set_yticks(range(len(rows)), labels, color=INK2, fontsize=9)
    ax.axhline(7.5, color=SURF, lw=6)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xticks(np.arange(-.5, len(cols)), minor=True)
    ax.set_yticks(np.arange(-.5, len(rows)), minor=True)
    ax.grid(which="minor", color=SURF, lw=2)
    ax.tick_params(which="minor", length=0)
    fig.suptitle("Fair race: how many times more often than normal it happened,\nwhen each technique picks the same "
                 "share of games\n(2025/26 and 2026/27 together; chosen or trained on 2024/25 only; 1.00x = random)",
                 color=INK, fontsize=12, x=.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, .9))
    fig.savefig(OUT / "bb_3_fair_race.png", dpi=150, facecolor=SURF)
    plt.close(fig)


def main():
    d = bb_data.build()
    S = pd.read_parquet(bb_data.CACHE / "bb_signs.parquet")
    R = pd.read_parquet(bb_data.CACHE / "bb_rules.parquet")
    L = pd.read_parquet(bb_data.CACHE / "bb_rules_luck.parquet")
    M = pd.read_parquet(bb_data.CACHE / "bb_ml.parquet")
    ML = pd.read_parquet(bb_data.CACHE / "bb_ml_scores.parquet")
    I = pd.read_parquet(bb_data.CACHE / "bb_ml_importance.parquet")
    qs = [0, .05, .1, .2, .35, .5, .65, .8, .9, 1]
    lad_own = ladder(d, "o_bb", "B", qs, "Nesine's own odds")
    lad_model = ladder_model_labels(d, qs)
    race = fair_race(d, S, ML)
    best_rules, luck = rules_table(R, L)
    hit, n, cells = goals_map(d)
    live_score, live_q, live_season = live_table(d)
    lg = leagues(d)
    ft, ht = scorelines(d)
    own = d["o_bb"].notna()
    chart_ladders(lad_own, lad_model, d.loc[own, "y_bb"].mean() * 100, d["y_bb"].mean() * 100)
    chart_map(hit, n)
    chart_race(race)
    signs = S[S["target"] == "BTTS both halves"].sort_values("AUC 2025/26", ascending=False)
    readme = [
        f"Both teams score in both halves (Nesine 'HT_2H_BTTS YES/YES') in {len(d):,} finished matches of our data: "
        f"2024/25 {int((d['per'] == 'A').sum()):,}, 2025/26 {int((d['per'] == 'B').sum()):,}, 2026/27 so far "
        f"{int((d['per'] == 'C').sum()):,}. It happened in {d['y_bb'].mean() * 100:.1f}% of them.",
        "Nesine's own price for it exists only from 2025/26 (about half the games then, most games now). The 'chance "
        "from the goal markets' is a model fitted to Nesine's team-goals, total-goals and half-result prices (not the "
        "BTTS markets), so it exists in every season.",
        "Hit rate only. Signs and models are chosen on 2024/25 and checked on 2025/26 and 2026/27.",
        "Ladders: how often it happened at each level of Nesine's own odds (with the money) and of the model chance.",
        "Fair race: each technique picks its top 10 / 5 / 2% of games in each later season; x normal = how many times "
        "more often than normal it happened.",
        "Rules: best 1-2 condition rules found on 2024/25 (confirmed on 2025/26) or on 2025/26 (checked on 2026/27), "
        "with the same number of games picked by the model and by Nesine's own price. Luck: the same search on "
        "shuffled results.",
        "Map: home x away expected goals. Live: if both teams scored in the 1st half, how often both score in the 2nd.",
        "Leagues: rate per league and the extra beyond the model (it does not carry over from season to season)."]
    sheets = [("Read me", pd.DataFrame({"Read me": readme})), ("Ladder - own odds", lad_own),
              ("Ladder - model chance", lad_model), ("Fair race", race), ("Rules (best)", best_rules),
              ("Rules luck control", luck), ("Map - hit %", hit.reset_index()), ("Map - games", n.reset_index()),
              ("Map by season", cells), ("Live - by HT score", live_score), ("Live - by pre-match chance", live_q),
              ("Live - by season", live_season), ("Leagues", lg), ("Scorelines - full time", ft),
              ("Scorelines - half time", ht), ("Machine learning", M), ("ML what it used", I),
              ("Single signs", signs.drop(columns=["sign"]))]
    with pd.ExcelWriter(OUT / "bb.xlsx") as xw:
        for name, df in sheets:
            df.round(3).to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.sheets[name[:31]]
            ws.set_column(0, 0, 22)
            ws.set_column(1, 1, 50)
            ws.set_column(2, 40, 14)
    return race, lad_own, lad_model, live_score, live_q


def ladder_model_labels(d, qs):
    """Model-chance ladder with the highest chances on the left (cut-offs from 2024/25)."""
    q = d["q_bb"]
    cut = np.nanquantile(q[d["per"] == "A"], [1 - v for v in qs][::-1])
    cut[0], cut[-1] = -1, 2
    x = d[q.notna()].assign(b=pd.cut(q[q.notna()], np.unique(cut)))
    rows = []
    for iv, g in sorted(x.groupby("b", observed=True), key=lambda t: -t[0].left):
        band = (f"over {iv.left * 100:.1f}%" if iv.right > 1 else
                (f"up to {iv.right * 100:.1f}%" if iv.left < 0 else f"{iv.left * 100:.1f}-{iv.right * 100:.1f}%"))
        r = {"by": "chance from the goal markets", "band": band, "games": len(g), "hit % (all)": g["y_bb"].mean() * 100,
             "model chance % (average)": g["q_bb"].mean() * 100}
        for k, nm in SEAS.items():
            gg = g[g["per"] == k]
            r[f"hit % {nm}"] = gg["y_bb"].mean() * 100 if len(gg) else np.nan
            r[f"games {nm}"] = len(gg)
        rows.append(r)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    race, lo, lm, ls, lq = main()
    pd.set_option("display.width", 260)
    pd.set_option("display.max_colwidth", 60)
    pd.set_option("display.max_rows", 200)
    print(race[["arena", "technique", "share", "games (both)", "hit % 2025/26", "hit % 2026/27", "hit % (both)",
                "x normal"]].round(2).to_string(index=False))
    print(lo.round(2).to_string(index=False))
    print(lm.round(2).to_string(index=False))
    print(ls.round(1).to_string(index=False))
    print(lq.round(1).to_string(index=False))
