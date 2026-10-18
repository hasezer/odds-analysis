"""Do 6+ goal games come in waves (every few weeks, across leagues or within a league)?

One row per finished match in scope (2024/25 + 2024, 2025/26 + 2025, 2026/27 + 2026) with Nesine's 'total goals
range' price (GOAL_RANGE 0-1 / 2-3 / 4-5 / 6+; cut removed). The expected 6+ chance is that price rescaled inside each
league-season so the league-season total matches (the null keeps league and season levels; only the timing is tested).
Weeks run Monday-Sunday (Turkey time).
1. Volume: weekly 6+ count vs the number of matches played that week (international breaks every few weeks).
2. Waves in the share (all leagues together): weekly actual vs expected 6+; dispersion (are some weeks hotter than
   chance allows?), autocorrelation at lags 1-10 weeks (does a hot week come back L weeks later?) and the strongest
   cycle of 2-12 weeks (periodogram). Luck control: every match's 6+ redrawn from its own chance, SIMS times, with the
   real fixture list.
3. Waves inside each league: the same on each league's own sequence of playing weeks, pooled over leagues.
4. Calendar: actual / expected by month, week of the month, after a break of 12+ days, midweek, start and end of
   season, per season; with the luck range.
5. Prediction, as a bettor would use it: does the excess of the last 1 / 2 / 4 weeks (all leagues, or the league
   itself) predict next week's 6+ share? Hot vs cold (top / bottom 20% of excess on 2024/25 cut-offs), per season.
Writes cache/six_waves_*.parquet, output/six_waves.png and output/six_waves.xlsx.

    python analysis/six_waves.py
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
SIMS = 2000
LAGS = range(1, 11)
SEAS = {"A": "2024/25", "B": "2025/26", "C": "2026/27"}


def table():
    f = load.flat()
    g = f[(f["market_key"] == "GOAL_RANGE") & f["closing_odds"].notna() & f["in_default_analysis"]]
    w = g.pivot_table(index="match_id", columns="selection_key", values="closing_odds").dropna()
    imp = 1 / w
    p6 = (imp["6+"] / imp.sum(axis=1)).rename("p6")
    m = load.matches()
    m = m[(m["status"] == "finished") & m["ft_home"].notna()].copy()
    m["per"] = m["season"].map(PER)
    m = m[m["per"].notna()].join(p6, on="match_id")
    m = m[m["p6"].notna()].copy()
    m["y6"] = ((m["ft_home"] + m["ft_away"]) >= 6).astype(int)
    m["day"] = m["kickoff_utc"].dt.tz_convert("Europe/Istanbul").dt.tz_localize(None).dt.normalize()
    m["week"] = m["day"] - pd.to_timedelta(m["day"].dt.weekday, unit="D")
    ls = m.groupby(["league_id", "season"])
    m["p_cal"] = (m["p6"] * ls["y6"].transform("sum") / ls["p6"].transform("sum")).clip(upper=0.95)
    # league calendar: days since the league's previous match day, round order, season stage
    days = m[["league_id", "season", "day"]].drop_duplicates().sort_values("day")
    days["gap"] = days.groupby(["league_id", "season"])["day"].diff().dt.days
    days["md"] = days.groupby(["league_id", "season"]).cumcount()
    days["md_n"] = days.groupby(["league_id", "season"])["md"].transform("max") + 1
    m = m.merge(days, on=["league_id", "season", "day"], how="left")
    m["after break"] = m["gap"] >= 12
    m["midweek"] = m["day"].dt.weekday.isin([1, 2, 3])
    m["stage"] = np.select([m["md"] < 5, m["md"] >= m["md_n"] - 5], ["first 5 match days", "last 5 match days"],
                           "middle of the season")
    m["month"] = m["day"].dt.month
    m["week of month"] = (m["day"].dt.day - 1) // 7 + 1
    return m.sort_values("kickoff_utc").reset_index(drop=True)


def sims(m, rng):
    return (rng.random((SIMS, len(m))) < m["p_cal"].to_numpy()[None, :]).astype(np.int8)


def weekly(m, Y):
    """Weekly actual / expected (all leagues) and the same for every simulated season set."""
    wk, wi = np.unique(m["week"].to_numpy(), return_inverse=True)
    n = np.bincount(wi)
    E = np.bincount(wi, weights=m["p_cal"].to_numpy())
    V = np.bincount(wi, weights=(m["p_cal"] * (1 - m["p_cal"])).to_numpy())
    k = np.bincount(wi, weights=m["y6"].to_numpy())
    ks = np.stack([np.bincount(wi, weights=Y[s], minlength=len(wk)) for s in range(len(Y))])
    W = pd.DataFrame({"week": wk, "matches": n, "6+ games": k, "expected": E, "var": V})
    return W, ks


def acf(z, lags):
    z = z - z.mean()
    d = (z * z).sum()
    return np.array([(z[:-L] * z[L:]).sum() / d for L in lags])


def spectrum(z, periods):
    t = np.arange(len(z))
    z = z - z.mean()
    return np.array([np.abs((z * np.exp(-2j * np.pi * t / p)).sum()) ** 2 / len(z) for p in periods])


def wave_tests(W, ks):
    """Dispersion, autocorrelation and cycles of the weekly z-scores, real vs simulated."""
    E, V = W["expected"].to_numpy(), W["var"].to_numpy() + 1e-9
    zr = (W["6+ games"].to_numpy() - E) / np.sqrt(V)
    zs = (ks - E) / np.sqrt(V)
    periods = np.arange(2, 13)
    real = {"dispersion": (zr ** 2).sum(), "acf": acf(zr, LAGS), "spec": spectrum(zr, periods)}
    sim_d = (zs ** 2).sum(axis=1)
    sim_acf = np.stack([acf(z, LAGS) for z in zs])
    sim_spec = np.stack([spectrum(z, periods) for z in zs])
    rows = [{"test": "dispersion (are some weeks hotter than chance allows?)", "real": real["dispersion"],
             "luck median": np.median(sim_d), "luck 95%": np.percentile(sim_d, 95),
             "share of luck runs at least as extreme %": (sim_d >= real["dispersion"]).mean() * 100}]
    for L, a, s in zip(LAGS, real["acf"], sim_acf.T):
        rows.append({"test": f"a hot week comes back {L} week(s) later (autocorrelation)", "real": a,
                     "luck median": np.median(s), "luck 95%": np.percentile(s, 95),
                     "share of luck runs at least as extreme %": (np.abs(s) >= abs(a)).mean() * 100})
    best = int(np.argmax(real["spec"]))
    smax = sim_spec.max(axis=1)
    rows.append({"test": f"strongest cycle: every {periods[best]} weeks (power vs the luck runs' strongest)",
                 "real": real["spec"][best], "luck median": np.median(smax), "luck 95%": np.percentile(smax, 95),
                 "share of luck runs at least as extreme %": (smax >= real["spec"][best]).mean() * 100})
    return pd.DataFrame(rows), zr, sim_acf


def league_waves(m, Y):
    """The same inside each league: its own playing weeks, autocorrelation pooled over leagues."""
    lw = m.groupby(["league_id", "week"]).indices
    keys = sorted(lw)
    E = np.array([m["p_cal"].to_numpy()[lw[k]].sum() for k in keys])
    V = np.array([(m["p_cal"].to_numpy()[lw[k]] * (1 - m["p_cal"].to_numpy()[lw[k]])).sum() for k in keys]) + 1e-9
    idx = np.zeros(len(m), int)
    for i, k in enumerate(keys):
        idx[lw[k]] = i
    k_real = np.bincount(idx, weights=m["y6"].to_numpy(), minlength=len(keys))
    k_sim = np.stack([np.bincount(idx, weights=Y[s], minlength=len(keys)) for s in range(len(Y))])
    league = np.array([k[0] for k in keys])

    def pooled(z):
        num = np.zeros(len(LAGS))
        den = 0.0
        for lg in np.unique(league):
            zz = z[league == lg]
            zz = zz - zz.mean()
            den += (zz * zz).sum()
            num += np.array([(zz[:-L] * zz[L:]).sum() if len(zz) > L else 0.0 for L in LAGS])
        return num / den

    zr = (k_real - E) / np.sqrt(V)
    real = pooled(zr)
    sim = np.stack([pooled((k_sim[s] - E) / np.sqrt(V)) for s in range(len(k_sim))])
    disp_r, disp_s = (zr ** 2).sum(), (((k_sim - E) / np.sqrt(V)) ** 2).sum(axis=1)
    rows = [{"test": "league-weeks: dispersion", "real": disp_r, "luck median": np.median(disp_s),
             "luck 95%": np.percentile(disp_s, 95),
             "share of luck runs at least as extreme %": (disp_s >= disp_r).mean() * 100}]
    for i, L in enumerate(LAGS):
        rows.append({"test": f"league: a hot playing week comes back {L} playing week(s) later", "real": real[i],
                     "luck median": np.median(sim[:, i]), "luck 95%": np.percentile(sim[:, i], 95),
                     "share of luck runs at least as extreme %": (np.abs(sim[:, i]) >= abs(real[i])).mean() * 100})
    return pd.DataFrame(rows)


def calendar(m, Y):
    rows = []
    groups = {"after a break of 12+ days": m["after break"].map({True: "yes", False: "no"}),
              "midweek (Tue-Thu)": m["midweek"].map({True: "yes", False: "no"}), "season stage": m["stage"],
              "month": m["month"], "week of the month": m["week of month"]}
    for name, lab in groups.items():
        for (per, val), ix in m.groupby([m["per"], lab]).indices.items():
            E = m["p_cal"].to_numpy()[ix].sum()
            ratio = m["y6"].to_numpy()[ix].sum() / E
            r_sim = Y[:, ix].sum(axis=1) / E
            rows.append({"what": name, "group": str(val), "season": SEAS[per], "matches": len(ix),
                         "6+ games": int(m["y6"].to_numpy()[ix].sum()), "expected": E, "actual / expected": ratio,
                         "luck range low (5%)": np.percentile(r_sim, 5), "luck range high (95%)": np.percentile(r_sim, 95)})
    out = pd.DataFrame(rows)
    out["outside the luck range"] = (out["actual / expected"] < out["luck range low (5%)"]) | (
        out["actual / expected"] > out["luck range high (95%)"])
    return out


def prediction(m):
    """Bettor's view: next week's 6+ share after a hot or cold spell (all leagues, or the league itself)."""
    rows = []
    wk = m.groupby("week").agg(k=("y6", "sum"), E=("p_cal", "sum"), per=("per", "first"))
    lw = m.groupby(["league_id", "week"]).agg(k=("y6", "sum"), E=("p_cal", "sum"), per=("per", "first"))
    for scope, t in (("all leagues", wk.assign(grp="all")), ("the league itself",
                                                             lw.reset_index(level=0).rename(columns={"league_id": "grp"}))):
        t = t.sort_index()
        for span in (1, 2, 4):
            g = t.groupby("grp")
            past_k = g["k"].transform(lambda v: v.shift(1).rolling(span, min_periods=span).sum())
            past_E = g["E"].transform(lambda v: v.shift(1).rolling(span, min_periods=span).sum())
            excess = (past_k - past_E) / np.sqrt(past_E.clip(lower=0.5))
            d = t.assign(excess=excess).dropna(subset=["excess"])
            lo, hi = np.nanquantile(d.loc[d["per"] == "A", "excess"], [0.2, 0.8])
            for state, sel in (("after a hot spell (top 20%)", d["excess"] >= hi),
                               ("after a cold spell (bottom 20%)", d["excess"] <= lo),
                               ("all weeks", d["excess"].notna())):
                for per, nm in SEAS.items():
                    x = d[sel & (d["per"] == per)]
                    rows.append({"spell": f"{scope}, last {span} week(s)", "state": state, "season": nm,
                                 "weeks": len(x), "6+ games": int(x["k"].sum()), "expected": x["E"].sum(),
                                 "next week actual / expected": x["k"].sum() / x["E"].sum() if len(x) else np.nan})
    return pd.DataFrame(rows)


def run():
    m = table()
    rng = np.random.default_rng(6)
    Y = sims(m, rng)
    W, ks = weekly(m, Y)
    T, zr, sim_acf = wave_tests(W, ks)
    L = league_waves(m, Y)
    C = calendar(m, Y)
    P = prediction(m)
    W["share %"] = W["6+ games"] / W["matches"] * 100
    W["expected share %"] = W["expected"] / W["matches"] * 100
    W["luck range low"] = np.percentile(ks, 5, axis=0)
    W["luck range high"] = np.percentile(ks, 95, axis=0)
    for name, df in (("weekly", W), ("tests", T), ("league_tests", L), ("calendar", C), ("prediction", P)):
        df.to_parquet(CACHE / f"six_waves_{name}.parquet")
    vol = np.corrcoef(W["matches"], W["6+ games"])[0, 1]
    print(f"{len(m)} matches, {int(m['y6'].sum())} with 6+ goals ({m['y6'].mean() * 100:.1f}%), {len(W)} weeks; "
          f"weekly 6+ count vs matches played: correlation {vol:.2f}")
    return m, W, T, L, C, P, sim_acf


def chart(W, T, sim_acf, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ink, ink2, muted, grid, base, band, blue = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#e8e7e1", "#2a78d6"
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(12, 8.6), gridspec_kw={"height_ratios": [1.35, 1]})
    fig.patch.set_facecolor("#fcfcfb")
    for ax in (a1, a2):
        ax.set_facecolor("#fcfcfb")
        ax.grid(axis="y", color=grid, lw=0.6)
        ax.set_axisbelow(True)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.spines["bottom"].set_color(base)
        ax.tick_params(colors=muted, labelsize=9)
    x = pd.to_datetime(W["week"]) + pd.Timedelta(days=3)
    a1.fill_between(x, W["luck range low"], W["luck range high"], color=band, lw=0, label="range luck alone gives (90%)")
    a1.bar(x, W["6+ games"], width=5, color=blue, label="6+ goal games that happened")
    a1.plot(x, W["expected"], color=ink2, lw=2, label="expected from Nesine's 6+ prices")
    wk = pd.to_datetime(W["week"])
    top = max(W["6+ games"].max(), W["luck range high"].max()) * 1.25
    quiet = W.loc[(W["matches"] <= 60) & wk.dt.month.isin([9, 10, 11, 3]) & (wk < "2026-06-01")].tail(1)
    for _, r in quiet.iterrows():
        at = pd.Timestamp(r["week"]) + pd.Timedelta(days=3)
        a1.annotate(f"international break: {int(r['matches'])} matches", (at, r["luck range high"] + 0.5),
                    xytext=(at, top * 0.86), textcoords="data", ha="center", fontsize=9, color=ink2,
                    arrowprops={"arrowstyle": "-", "color": muted, "lw": 0.8})
    a1.set_title("6+ goal games each week, all 26 leagues: they rise and fall with how many matches are played",
                 loc="left", fontsize=12, color=ink)
    a1.set_ylabel("games with 6+ goals", color=ink2, fontsize=10)
    a1.legend(loc="upper left", frameon=False, fontsize=9, labelcolor=ink2, ncol=3)
    a1.set_ylim(0, top)
    lags = np.array(list(LAGS))
    real = T[T["test"].str.contains("autocorrelation")]["real"].to_numpy()
    lo, hi = np.percentile(sim_acf, [2.5, 97.5], axis=0)
    a2.fill_between(lags, lo, hi, color=band, lw=0, step="mid", label="range luck alone gives (95%)")
    a2.bar(lags, real, width=0.5, color=blue, label="real pattern")
    a2.axhline(0, color=base, lw=0.8)
    a2.set_xticks(lags, [f"{L} wk" for L in lags])
    a2.set_title("Does a week with extra 6+ games come back 1-10 weeks later? No regular cycle: the bars stay in the "
                 "luck range\n(5 weeks only touches its edge, and it failed as a betting signal)", loc="left",
                 fontsize=12, color=ink)
    a2.set_ylabel("link between the two weeks", color=ink2, fontsize=10)
    a2.legend(loc="lower left", frameon=False, fontsize=9, labelcolor=ink2, ncol=2)
    fig.tight_layout()
    fig.savefig(path, dpi=120, facecolor=fig.get_facecolor())
    plt.close(fig)


def excel(W, T, L, C, P, path):
    with pd.ExcelWriter(path) as xw:
        w = W.drop(columns=["var"]).assign(week=lambda d: pd.to_datetime(d["week"]).dt.date)
        w.round(2).to_excel(xw, sheet_name="Every week", index=False)
        pd.concat([T, L]).round(3).to_excel(xw, sheet_name="Wave tests", index=False)
        C.round(2).to_excel(xw, sheet_name="Calendar", index=False)
        P.round(2).to_excel(xw, sheet_name="Hot and cold spells", index=False)


if __name__ == "__main__":
    m, W, T, L, C, P, sim_acf = run()
    chart(W, T, sim_acf, HERE / "output" / "six_waves.png")
    excel(W, T, L, C, P, HERE / "output" / "six_waves.xlsx")
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 20)
    print(T.round(3).to_string(index=False))
    print(L.round(3).to_string(index=False))
    print(C[C["outside the luck range"]].round(2).to_string(index=False))
    print(P.round(2).to_string(index=False))
