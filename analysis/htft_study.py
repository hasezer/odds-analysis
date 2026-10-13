"""HT/FT (İY/MS) deep dive.

Run:  python analysis/htft_study.py            (first run builds analysis/cache/, ~3 minutes)
Writes analysis/output/htft_*.png and analysis/output/htft_study.xlsx. Results: analysis/HTFT_REPORT.md.

Conventions as in first_look.py: closing odds, 1-unit stakes, discovery = 2024/25 + 2024, check = later seasons.
"Expected" = HT/FT fair probability (cut removed within the HT/FT market). "Other markets" = the cross-market
Poisson price from htft_poisson.py (HT/FT market not used).
"""
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss

sys.path.insert(0, str(Path(__file__).resolve().parent))
import htft_poisson as hp  # noqa: E402
from first_look import BLUE, GRAY, INK, INK2, ORANGE, OUT, SURFACE  # noqa: E402  (also sets the chart style)
from htft_data import HTFT  # noqa: E402

PERIODS = ["discovery", "check"]
PERIOD_LABEL = {"discovery": "2024/25 + 2024", "check": "2025/26, 2026/27, 2025, 2026"}
NAMES = {"1/1": "1/1", "1/X": "1/X (1/0)", "1/2": "1/2", "X/1": "X/1 (0/1)", "X/X": "X/X (0/0)", "X/2": "X/2 (0/2)",
         "2/1": "2/1", "2/X": "2/X (2/0)", "2/2": "2/2"}


def _summary(d: pd.DataFrame, k: str) -> dict:
    hit = d["htft"] == k
    p = d[f"p_{k}"]
    return {"matches": len(d), "hits": int(hit.sum()), "actual_pct": hit.mean() * 100, "expected_pct": p.mean() * 100,
            "z": (hit.sum() - p.sum()) / np.sqrt((p * (1 - p)).sum()),
            "roi_pct": (hit * d[f"o_{k}"] - 1).mean() * 100}


def by_period(w, k, group=None):
    rows = []
    keys = [group] if group else []
    for key, d in w.groupby(keys + ["period"], observed=True):
        key = key if isinstance(key, tuple) else (key,)
        rows.append({**dict(zip(keys + ["period"], key)), "outcome": k, **_summary(d, k)})
    return pd.DataFrame(rows)


def wide(t, index):
    v = t.pivot_table(index=index, columns="period", values=["matches", "hits", "actual_pct", "expected_pct", "roi_pct"],
                      observed=True)
    v.columns = [f"{a}_{b}" for a, b in v.columns]
    return v.round(2).reset_index()


# ---------------------------------------------------------------- A. outcome overview
def outcomes(w):
    t = pd.concat([by_period(w, k) for k in HTFT])
    all_ = pd.DataFrame([{"outcome": k, **_summary(w, k), "median_odds": w[f"o_{k}"].median()} for k in HTFT])
    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(len(HTFT))
    for i, per in enumerate(PERIODS):
        v = t[t["period"] == per].set_index("outcome").loc[HTFT, "roi_pct"]
        ax.bar(x + (i - .5) * .38, v, width=.36, color=[BLUE, ORANGE][i], label=PERIOD_LABEL[per])
    ax.axhline(0, color=INK2, lw=1)
    ax.set_xticks(x, [NAMES[k] for k in HTFT])
    ax.set_ylabel("Return per bet (−25% = lose 25 TL per 100 TL)")
    ax.grid(axis="x", visible=False)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, frameon=False)
    ax.set_title("A. Every HT/FT outcome loses about a quarter of the stake", pad=34)
    fig.tight_layout(); fig.savefig(OUT / "htft_A_outcomes.png", dpi=150); plt.close(fig)
    return all_.round(2), wide(t, ["outcome"])


# ---------------------------------------------------------------- B. the 35 cap on turnarounds
def cap(w):
    bands = [0, 22, 26, 30, 33.9, 40]
    labels = ["≤ 22", "22–26", "26–30", "30–33.9", "34–35 (cap)"]
    rows, exact = [], []
    for k in ["1/2", "2/1"]:
        d = w.assign(band=pd.cut(w[f"o_{k}"], bands, labels=labels))
        rows.append(by_period(d, k, "band"))
        g = d.groupby(f"o_{k}").filter(lambda s: len(s) >= 300)
        for val, s in g.groupby(f"o_{k}"):
            exact.append({"outcome": k, "odds": val, **_summary(s, k), "other_markets_pct": s[f"q_{k}"].mean() * 100})
    t = pd.concat(rows)
    share = {k: (w[f"o_{k}"] >= 34).mean() * 100 for k in ["1/2", "2/1"]}

    fig, axes = plt.subplots(1, 2, figsize=(13, 6), sharey=True)
    for ax, k in zip(axes, ["1/2", "2/1"]):
        s = t[t["outcome"] == k]
        x = np.arange(len(labels))
        for i, per in enumerate(PERIODS):
            v = s[s["period"] == per].set_index("band").reindex(labels)["roi_pct"]
            ax.bar(x + (i - .5) * .38, v, width=.36, color=[BLUE, ORANGE][i], label=PERIOD_LABEL[per])
        ax.axhline(0, color=INK2, lw=1)
        ax.set_xticks(x, labels, rotation=20)
        ax.set_title(f"{k}: {share[k]:.0f}% of matches priced at the 34–35 cap", fontsize=12)
        ax.grid(axis="x", visible=False)
        ax.set_xlabel(f"{k} odds")
    axes[0].set_ylabel("Return per bet")
    axes[0].legend(loc="lower left", bbox_to_anchor=(0, 1.07), ncol=2, frameon=False)
    fig.suptitle("B. Turnaround odds are capped at ~35, and the capped bets lose the most", x=.06, ha="left",
                 fontsize=15, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, .93)); fig.savefig(OUT / "htft_B_cap.png", dpi=150); plt.close(fig)
    return wide(t, ["outcome", "band"]), pd.DataFrame(exact).round(2)


# ---------------------------------------------------------------- C. other markets vs the HT/FT price
def cross_market(w):
    rows = []
    for k in HTFT:
        r = np.log(w[f"q_{k}"] / w[f"p_{k}"])
        cuts = np.quantile(r[w["period"] == "discovery"], [.2, .4, .6, .8])
        d = w.assign(group=np.digitize(r, cuts) + 1)
        for (g, per), s in d.groupby(["group", "period"]):
            rows.append({"outcome": k, "group": g, "period": per, **_summary(s, k),
                         "other_markets_pct": s[f"q_{k}"].mean() * 100})
    t = pd.DataFrame(rows)

    # chart: turnarounds (1/2 and 2/1 pooled), both periods pooled, actual vs HT/FT price vs other markets
    s = t[t["outcome"].isin(["1/2", "2/1"])]
    s = s.assign(exp=s["expected_pct"] * s["matches"], oth=s["other_markets_pct"] * s["matches"])
    g = s.groupby("group").agg(m=("matches", "sum"), h=("hits", "sum"), e=("exp", "sum"), o=("oth", "sum"))
    act, exp, oth = g["h"] / g["m"] * 100, g["e"] / g["m"], g["o"] / g["m"]
    se = np.sqrt(act / 100 * (1 - act / 100) / g["m"]) * 100 * 1.96
    fig, ax = plt.subplots(figsize=(11, 6.2))
    x = np.arange(1, 6)
    ax.plot(x, exp, color=GRAY, lw=2, marker="o", ms=8, label="HT/FT price says")
    ax.plot(x, oth, color=ORANGE, lw=2, marker="o", ms=8, label="Other markets say")
    ax.errorbar(x, act, yerr=se, color=BLUE, lw=2.5, marker="o", ms=9, capsize=4, label="Actually happened")
    ax.set_xticks(x, ["1\nother markets:\nmuch less likely", "2", "3", "4", "5\nother markets:\nas/more likely"])
    ax.set_ylabel("Chance of a turnaround (1/2 or 2/1), %")
    ax.set_ylim(0, None)
    ax.legend(frameon=False, loc="upper left")
    ax.set_title("C. When the other markets disagree with the HT/FT price, trust the other markets")
    fig.tight_layout(); fig.savefig(OUT / "htft_C_cross_market.png", dpi=150); plt.close(fig)
    return t.round(2)


# ---------------------------------------------------------------- D. can a model beat the HT/FT price?
def model_test(w):
    y = w["htft"].map({k: i for i, k in enumerate(HTFT)}).to_numpy()
    tr = (w["period"] == "discovery").to_numpy(); te = ~tr
    P = w[[f"p_{k}" for k in HTFT]].to_numpy(); Q = w[[f"q_{k}" for k in HTFT]].to_numpy()
    O = w[[f"o_{k}" for k in HTFT]].to_numpy()
    hint = [c for c in w.columns if c.startswith("f_")
            and w.loc[tr, c].notna().mean() > .5 and w.loc[te, c].notna().mean() > .5]
    hist = [c for c in w.columns if c.startswith(("home_last10", "away_last10", "home_days", "away_days"))]

    def ll(p):
        return log_loss(y[te], p[te], labels=range(9))

    models = {}
    lr1 = LogisticRegression(max_iter=3000).fit(np.log(P)[tr], y[tr])
    X2 = np.hstack([np.log(P), np.log(Q)])
    lr2 = LogisticRegression(max_iter=3000).fit(X2[tr], y[tr])
    X3 = np.hstack([X2, w[hint + hist].to_numpy()])
    gb = HistGradientBoostingClassifier(max_iter=300, learning_rate=.03, max_leaf_nodes=15, l2_regularization=1.0,
                                        early_stopping=True, validation_fraction=.2, random_state=0).fit(X3[tr], y[tr])
    models["HT/FT price alone (cut removed)"] = P
    models["Other markets alone (Poisson)"] = Q / Q.sum(1, keepdims=True)
    models["HT/FT price, re-tuned on 2024/25"] = lr1.predict_proba(np.log(P))
    models["HT/FT price + other markets"] = lr2.predict_proba(X2)
    models[f"Machine learning: price + {len(hint)} hints + team history"] = gb.predict_proba(X3)
    base = ll(P)
    rows, bets = [], []
    for name, pm in models.items():
        rows.append({"model": name, "log_loss_check": round(ll(pm), 5),
                     "better_than_price_pct": round((base - ll(pm)) / base * 100, 3)})
        if name in ("HT/FT price alone (cut removed)", "Other markets alone (Poisson)"):
            continue        # the Poisson price has no cut, so price x odds never clears 1
        for edge in (0, .05, .10, .20):
            bet = ((pm * O - 1) > edge) & te[:, None]
            hit = y[:, None] == np.arange(9)[None, :]
            prof = np.where(hit, O - 1, -1)[bet]
            bets.append({"model": name, "bet_when_model_edge_above": f"{edge:.0%}", "bets": int(bet.sum()),
                         "roi_pct": round(prof.mean() * 100, 1) if bet.sum() else np.nan})
    return pd.DataFrame(rows), pd.DataFrame(bets)


# ---------------------------------------------------------------- E. history patterns (last match etc.)
def team_view(w):
    tm, flip = {"1": "W", "X": "D", "2": "L"}, {"1": "L", "X": "D", "2": "W"}

    def tk(k, side):
        a, b = k.split("/")
        m = tm if side == "home" else flip
        return f"{m[a]}/{m[b]}"

    parts = []
    for side, opp in (("home", "away"), ("away", "home")):
        d = pd.DataFrame({"match_id": w["match_id"], "period": w["period"], "side": side,
                          "team": w[f"{side}_team_id"], "actual": w["htft"].map(lambda k: tk(k, side))})
        for k in HTFT:
            d[f"p_{tk(k, side)}"] = w[f"p_{k}"].values
            d[f"o_{tk(k, side)}"] = w[f"o_{k}"].values
        for c in ("prev_score", "prev_htft_team", "prev_goals_total", "prev_second_half_goals",
                  "last10_comeback_win", "last10_blown_lead", "last10_2h_goals", "days_rest"):
            d[f"own_{c}"] = w[f"{side}_{c}"].values
            d[f"opp_{c}"] = w[f"{opp}_{c}"].values
        parts.append(d)
    t = pd.concat(parts, ignore_index=True)
    common = lambda s: s.where(s.map(s.value_counts()) >= 300, "other")
    t["last match score (own view)"] = common(t["own_prev_score"])
    t["opponent's last match score"] = common(t["opp_prev_score"])
    t["last match HT/FT (own view)"] = t["own_prev_htft_team"]
    t["opponent's last match HT/FT"] = t["opp_prev_htft_team"]
    t["goals in last match"] = pd.cut(t["own_prev_goals_total"], [-1, 1, 3, 5, 20], labels=["0-1", "2-3", "4-5", "6+"])
    t["2nd-half goals in last match"] = pd.cut(t["own_prev_second_half_goals"], [-1, 0, 2, 20], labels=["0", "1-2", "3+"])
    t["comeback wins in last 10"] = pd.cut(t["own_last10_comeback_win"], [-1, 0, 1, 10], labels=["0", "1", "2+"])
    t["blown HT leads in last 10"] = pd.cut(t["own_last10_blown_lead"], [-1, 0, 1, 10], labels=["0", "1", "2+"])
    t["avg 2nd-half goals, last 10"] = pd.cut(t["own_last10_2h_goals"], [0, 1.2, 1.6, 2.0, 10],
                                               labels=["<1.2", "1.2-1.6", "1.6-2.0", "2.0+"])
    t["rest vs opponent"] = pd.cut(t["own_days_rest"] - t["opp_days_rest"], [-100, -3, -1, 1, 3, 100],
                                   labels=["3+ days less", "1-3 less", "same", "1-3 more", "3+ days more"])
    t["days since last match"] = pd.cut(t["own_days_rest"], [0, 3.5, 5.5, 9, 400], labels=["≤3", "4-5", "6-9", "10+"])
    return t


FEATURES = ["last match score (own view)", "opponent's last match score", "last match HT/FT (own view)",
            "opponent's last match HT/FT", "goals in last match", "2nd-half goals in last match",
            "comeback wins in last 10", "blown HT leads in last 10", "avg 2nd-half goals, last 10", "rest vs opponent",
            "days since last match"]
TEAM_OUT = ["W/W", "W/D", "W/L", "D/W", "D/D", "D/L", "L/W", "L/D", "L/L"]


def patterns(t):
    rows = []
    for f in FEATURES:
        for val, g in t.groupby(f, observed=True):
            for k in TEAM_OUT:
                for per in PERIODS:
                    s = g[g["period"] == per]
                    if len(s) < 100:
                        continue
                    hit = s["actual"] == k
                    p = s[f"p_{k}"]
                    rows.append({"feature": f, "value": str(val), "team_outcome": k, "period": per, "n": len(s),
                                 "hits": int(hit.sum()), "expected": p.sum(),
                                 "z": (hit.sum() - p.sum()) / np.sqrt((p * (1 - p)).sum()),
                                 "roi_pct": (hit * s[f"o_{k}"] - 1).mean() * 100})
    r = pd.DataFrame(rows)
    v = r.pivot_table(index=["feature", "value", "team_outcome"], columns="period",
                      values=["n", "hits", "expected", "z", "roi_pct"]).dropna()
    v.columns = [f"{a}_{b}" for a, b in v.columns]
    v = v.reset_index()
    # each match appears once from each side, so "own X" and "opponent's X" rows mirror each other
    v = v[~v["feature"].str.startswith("opponent")]
    sig = v[v["z_discovery"].abs() > 1.96]
    held = sig[(np.sign(sig["z_check"]) == np.sign(sig["z_discovery"])) & (sig["z_check"].abs() > 1.96)]
    score = pd.DataFrame([
        {"step": "patterns tested (own-team view)", "count": len(v)},
        {"step": "looked significant in 2024/25 + 2024 (|z| > 1.96)", "count": len(sig)},
        {"step": "…expected by pure luck (5%)", "count": round(len(v) * .05)},
        {"step": "significant again, same direction, in later seasons", "count": len(held)},
        {"step": "…expected by pure luck", "count": round(len(sig) * .025, 1)},
    ])

    fig, ax = plt.subplots(figsize=(10, 8))
    ax.scatter(v["z_discovery"], v["z_check"], s=14, color=GRAY, alpha=.6, linewidths=0)
    ax.scatter(sig["z_discovery"], sig["z_check"], s=40, color=BLUE, edgecolor=SURFACE, linewidth=1,
               label="looked significant in 2024/25 + 2024")
    for _, r_ in v.iterrows():
        if (r_["feature"], r_["value"], r_["team_outcome"]) in {("last match score (own view)", "3-3", "L/W"),
                                                                ("goals in last match", "6+", "L/W")}:
            ax.annotate(f"{r_['value']} last match → comeback", (r_["z_discovery"], r_["z_check"]),
                        xytext=(10, -22), textcoords="offset points", fontsize=10, color=INK,
                        arrowprops=dict(arrowstyle="-", color=INK2))
    for x in (-1.96, 1.96):
        ax.axvline(x, color=INK2, lw=.8, ls="--"); ax.axhline(x, color=INK2, lw=.8, ls="--")
    ax.set_xlabel("Strength of the pattern in 2024/25 + 2024  (z-score)")
    ax.set_ylabel("Strength in the later seasons  (z-score)")
    ax.legend(frameon=False, loc="upper left")
    ax.set_title("E. Patterns from past results don't repeat\n(each dot = one 'after X, outcome Y' pattern)",
                 fontsize=14)
    fig.tight_layout(); fig.savefig(OUT / "htft_E_patterns.png", dpi=150); plt.close(fig)
    return score, v.round(2).sort_values("z_discovery", ascending=False)


def user_examples(t):
    rows = []
    for label, mask in [
        ("last match 3-2 or 2-3", t["own_prev_score"].isin(["3-2", "2-3"])),
        ("last match won 3-2", t["own_prev_score"] == "3-2"),
        ("last match lost 2-3", t["own_prev_score"] == "2-3"),
        ("last match 3-3", t["own_prev_score"] == "3-3"),
        ("last match had 6+ goals", t["own_prev_goals_total"] >= 6),
        ("last match was a comeback win (L/W)", t["own_prev_htft_team"] == "L/W"),
        ("last match blew a HT lead (W/L)", t["own_prev_htft_team"] == "W/L"),
        ("every team-match", t["own_prev_score"].notna()),
    ]:
        for k, desc in (("L/W", "comes back to win (home 2/1, away 1/2)"),
                        ("W/L", "blows a HT lead (home 1/2, away 2/1)")):
            row = {"condition": label, "outcome for that team": desc}
            for per in PERIODS:
                s = t[mask & (t["period"] == per)]
                hit = s["actual"] == k
                row.update({f"n_{per}": len(s), f"hits_{per}": int(hit.sum()),
                            f"expected_{per}": round(s[f"p_{k}"].sum(), 1),
                            f"roi_pct_{per}": round((hit * s[f"o_{k}"] - 1).mean() * 100, 1)})
            rows.append(row)
    return pd.DataFrame(rows)


def persistence(t, w):
    rows = []
    for k in ("L/W", "W/L", "D/W", "W/D", "D/D"):
        g = t.assign(hit=t["actual"] == k).groupby(["team", "period"]).apply(
            lambda d: pd.Series({"n": len(d), "excess": (d["hit"].sum() - d[f"p_{k}"].sum()) / len(d)}),
            include_groups=False).unstack().dropna()
        g = g[(g[("n", "discovery")] >= 30) & (g[("n", "check")] >= 30)]
        rows.append({"level": "team", "outcome (team view)": k, "units": len(g),
                     "correlation_discovery_vs_check": round(g[("excess", "discovery")].corr(g[("excess", "check")]), 3)})
    for k in HTFT:
        g = w.assign(hit=w["htft"] == k).groupby(["league_id", "period"]).apply(
            lambda d: d["hit"].mean() - d[f"p_{k}"].mean(), include_groups=False).unstack()
        rows.append({"level": "league", "outcome (team view)": k, "units": len(g),
                     "correlation_discovery_vs_check": round(g["discovery"].corr(g["check"]), 3)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- F. fingerprint: what turnaround matches look like
def fingerprint(w):
    key = {"f_1X2__1": "home win %", "f_1X2__X": "draw %", "f_1X2__2": "away win %", "f_OU_2.5_OVER": "over 2.5 %",
           "f_BTTS__YES": "both score %", "f_HT_OU_1.5_OVER": "1st-half over 1.5 %"}
    w = w.assign(second_half_share=(w["lam_h2"] + w["lam_a2"]) /
                 (w["lam_h1"] + w["lam_a1"] + w["lam_h2"] + w["lam_a2"]) * 100)
    rows = []
    for k in HTFT + ["ALL"]:
        d = w if k == "ALL" else w[w["htft"] == k]
        rows.append({"outcome": k, "matches": len(d), **{v: d[c].mean() * 100 for c, v in key.items()},
                     "share of goals expected after HT %": d["second_half_share"].mean()})
    fp = pd.DataFrame(rows).round(1)

    # heat map: turnaround rate by favourite strength x goal expectation (actual, and actual − price)
    w = w.assign(fav=pd.cut(w["f_1X2__1"] - w["f_1X2__2"], [-1, -.35, -.15, .15, .35, 1],
                            labels=["away strong fav", "away fav", "even", "home fav", "home strong fav"]),
                 goals=pd.cut(w["f_OU_2.5_OVER"], [0, .45, .55, .65, 1], labels=["low", "medium", "high", "very high"]))
    rows = []
    for (a, b), d in w.groupby(["fav", "goals"], observed=True):
        hit = d["htft"].isin(["1/2", "2/1"])
        exp = d["p_1/2"] + d["p_2/1"]
        rows.append({"favourite": a, "goals expected": b, "matches": len(d), "turnaround_actual_pct": hit.mean() * 100,
                     "turnaround_price_pct": exp.mean() * 100,
                     "excess_pts": (hit.mean() - exp.mean()) * 100})
    heat = pd.DataFrame(rows)
    rows_o = ["very high", "high", "medium", "low"]
    cols_o = ["away strong fav", "away fav", "even", "home fav", "home strong fav"]
    m = heat.pivot(index="goals expected", columns="favourite", values="turnaround_actual_pct").reindex(rows_o)[cols_o]
    n = heat.pivot(index="goals expected", columns="favourite", values="matches").reindex(rows_o)[cols_o]
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("seq", ["#cde2fb", "#6da7ec", "#256abf", "#0d366b"])
    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.imshow(m.values, cmap=cmap, aspect="auto", vmin=0, vmax=10)
    ax.set_xticks(range(m.shape[1]), m.columns); ax.set_yticks(range(m.shape[0]), m.index)
    ax.grid(False)
    for i in range(m.shape[0]):
        for j in range(m.shape[1]):
            v, nn = m.values[i, j], n.values[i, j]
            if np.isnan(v):
                continue
            ax.text(j, i, f"{v:.1f}%\n{int(nn):,} matches", ha="center", va="center", fontsize=10,
                    color="white" if v > 5 else INK)
    ax.set_ylabel("Goals expected\n(over 2.5 chance)")
    ax.set_xlabel("1X2 odds: who is favourite (home win % minus away win %)")
    ax.set_title("F. Turnarounds (1/2 or 2/1) happen most in even, high-scoring games\n"
                 "— but the odds already price that in", fontsize=14)
    for s in ax.spines.values():
        s.set_visible(False)
    fig.tight_layout(); fig.savefig(OUT / "htft_F_where.png", dpi=150); plt.close(fig)
    return fp, heat.round(2)


def season_phase(w):
    w = w.assign(phase=pd.cut(w.groupby(["league_id", "season"])["kickoff_utc"].rank(pct=True), [0, .15, .85, 1],
                              labels=["first 15% of season", "middle", "last 15% of season"]))
    return wide(pd.concat([by_period(w, k, "phase") for k in HTFT]), ["outcome", "phase"])


def watch_list(w):
    """The few leads worth tracking on new matches (not proven)."""
    rows = []
    for label, mask, k in [
        ("1/2 priced ≤ 26", w["o_1/2"] <= 26, "1/2"),
        ("2/1 priced ≤ 26", w["o_2/1"] <= 26, "2/1"),
        ("1/2 priced ≤ 20", w["o_1/2"] <= 20, "1/2"),
        ("1/2 in even/away-fav games with over 2.5 > 65%",
         (w["f_1X2__1"] - w["f_1X2__2"] < .15) & (w["f_OU_2.5_OVER"] > .65), "1/2"),
        ("1/2 or 2/1 at the 34–35 cap (lay-off zone)", None, None),
    ]:
        if k is None:
            for kk in ("1/2", "2/1"):
                s = w[w[f"o_{kk}"] >= 34]
                rows += [{"lead": f"{kk} at the 34–35 cap", "period": per, **_summary(s[s["period"] == per], kk)}
                         for per in PERIODS]
            continue
        rows += [{"lead": label, "period": per, **_summary(w[mask & (w["period"] == per)], k)} for per in PERIODS]
    return pd.DataFrame(rows).round(2)


def main():
    w = hp.build()
    print(f"{len(w):,} matches with a complete HT/FT market")
    t = team_view(w)
    out_all, out_period = outcomes(w)
    cap_band, cap_exact = cap(w)
    cm = cross_market(w)
    mdl, mdl_bets = model_test(w)
    score, pats = patterns(t)
    ex = user_examples(t)
    pers = persistence(t, w)
    fp, heat = fingerprint(w)
    phase = season_phase(w)
    watch = watch_list(w)

    sheets = {"A Outcomes": out_all, "A Outcomes by period": out_period, "B Cap - by odds band": cap_band,
              "B Cap - exact odds": cap_exact, "C Other markets vs price": cm, "D Model test": mdl,
              "D Model betting test": mdl_bets, "E Pattern scoreboard": score, "E Your examples": ex,
              "E All patterns": pats, "E Team+league repeat": pers, "F Fingerprint": fp, "F Where turnarounds": heat,
              "G Season phase": phase, "H Watch list": watch}
    with pd.ExcelWriter(OUT / "htft_study.xlsx", engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.sheets[name[:31]]
            ws.freeze_panes = "A2"
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = max(
                    10, min(40, max(len(str(c.value if c.value is not None else "")) for c in col) + 2))
    for name in ("A Outcomes", "D Model test", "D Model betting test", "E Pattern scoreboard", "E Your examples",
                 "E Team+league repeat", "F Fingerprint", "F Where turnarounds", "H Watch list"):
        print(f"\n== {name}\n{sheets[name].round(2).to_string(index=False)}")


if __name__ == "__main__":
    main()
