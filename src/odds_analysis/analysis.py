"""Weekly analysis on this project's own Nesine/Mackolik data only.

reports/YYYY-MM-DD.md (+ PNG charts), reports/findings.md (+ findings.csv state),
exports/analysis_summary.csv.

Every number carries n. Hit rates get Wilson 95% intervals; each segment is tested against the
bookmaker's implied probability (hits vs sum of 1/odds: Poisson-binomial, normal approximation),
which is the same as testing flat-stake ROI = 0. p-values are Benjamini-Hochberg corrected,
segments with n < 100 are flagged insufficient, and patterns must survive a walk-forward split
(older 70% of dates -> newer 30%).
"""

from __future__ import annotations

import logging
import math
from datetime import date as Date
from pathlib import Path

import numpy as np
import pandas as pd

from .config import DATA, EXPORTS, REPORTS, TR, load, now_utc
from .export import build_date
from .storage import read_table

log = logging.getLogger(__name__)

MIN_N = 100
ALPHA = 0.05
BANDS = [(1.01, 1.20), (1.21, 1.40), (1.41, 1.60), (1.61, 1.80), (1.81, 2.00), (2.01, 2.50), (2.51, 3.00),
         (3.01, 4.00), (4.01, 5.00), (5.01, 1e9)]
BAND_LABELS = [f"{a:.2f}-{b:.2f}" if b < 1e8 else "5.00+" for a, b in BANDS]

# palette (reference instance, light mode) - static PNGs embedded in markdown
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
BLUE, ORANGE = "#2a78d6", "#eb6834"


# ---------------------------------------------------------------- statistics
def wilson(k: float, n: float, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (np.nan, np.nan)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


def pb_test(hits: float, probs: np.ndarray) -> tuple[float, float]:
    """Two-sided test of observed hits vs expected sum(p) (Poisson-binomial, normal approx). -> (z, p)."""
    mu = float(np.sum(probs))
    var = float(np.sum(probs * (1 - probs)))
    if var <= 0:
        return (np.nan, np.nan)
    z = (hits - mu) / math.sqrt(var)
    return z, math.erfc(abs(z) / math.sqrt(2))


def bh(pvals: pd.Series) -> pd.Series:
    """Benjamini-Hochberg q-values (NaN kept)."""
    p = pvals.dropna().sort_values()
    m = len(p)
    if not m:
        return pd.Series(np.nan, index=pvals.index)
    ranks = np.arange(1, m + 1)
    q = (p.values * m / ranks)
    q = np.minimum.accumulate(q[::-1])[::-1]
    out = pd.Series(np.nan, index=pvals.index)
    out[p.index] = np.minimum(q, 1)
    return out


def band_of(odds: float) -> str | None:
    for (a, b), lab in zip(BANDS, BAND_LABELS):
        if a - 1e-9 <= odds <= b + 0.005:
            return lab
    return None


# ---------------------------------------------------------------- data
def load_rows(dates: list[str] | None = None) -> pd.DataFrame:
    """All settled selections with prices (rebuilt from data/, same rows as the exports)."""
    if dates is None:
        dates = sorted(p.name[:10] for p in (DATA / "settled").glob("*.csv.gz"))
    frames = [build_date(d) for d in dates]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Bettable, settled rows with derived segment columns."""
    rules = load("card_rules")
    d = df[df["hit"].isin([0, 1]) & df["closing_odds"].notna() & (df["closing_odds"] > 1)].copy()
    if not rules.get("include_in_analysis", True):
        d = d[d["family"] != "cards"]
    d["hit"] = d["hit"].astype(int)
    d["price"] = d["closing_odds"].astype(float)
    d["implied"] = 1 / d["price"]
    d["profit"] = np.where(d["hit"] == 1, d["price"] - 1, -1.0)
    d["odds_band"] = d["price"].map(band_of)
    d["market_group"] = d["market_key"].str.replace(r"_-?[\d.]+$", "", regex=True).str.replace(r"_[\d.]+_", "_", regex=True)
    ko = pd.to_datetime(d["kickoff_utc"], utc=True, errors="coerce").dt.tz_convert("Europe/Istanbul")
    d["kickoff_hour"] = ko.dt.hour
    d["weekday"] = ko.dt.day_name().str[:3]
    d["mbs"] = d["mbs"].astype("Int64").astype(str)
    # favourite / longshot inside each market (by closing price)
    rank = d.groupby(["match_id", "market_id"])["price"].rank(method="min")
    size = d.groupby(["match_id", "market_id"])["price"].transform("count")
    d["fav_long"] = np.select([rank == 1, rank == size], ["favourite", "longshot"], "middle")
    d.loc[size < 2, "fav_long"] = "single"
    d["outcome"] = np.where(d["market_key"] == "1X2", d["selection"], None)
    mv = d["odds_movement_pct"]
    d["movement"] = np.select([mv <= -2, mv >= 2, mv.abs() < 2], ["shortening", "drifting", "stable"], None)
    d.loc[mv.isna(), "movement"] = None
    return d


def segment_stats(d: pd.DataFrame, dims: list[str]) -> pd.DataFrame:
    rows = []
    for dim in dims:
        for val, g in d.dropna(subset=[dim]).groupby(dim):
            n = len(g)
            hits = int(g["hit"].sum())
            lo, hi = wilson(hits, n)
            z, p = pb_test(hits, g["implied"].to_numpy())
            gf = g.dropna(subset=["fair_prob"])
            zf, pf = pb_test(gf["hit"].sum(), gf["fair_prob"].to_numpy()) if len(gf) else (np.nan, np.nan)
            fair = gf["fair_prob"]
            rows.append({
                "dimension": dim, "segment": str(val), "n": n, "hits": hits, "hit_rate": hits / n,
                "ci_low": lo, "ci_high": hi, "mean_implied": g["implied"].mean(),
                "mean_fair": fair.mean() if len(fair) else np.nan, "mean_odds": g["price"].mean(),
                "roi": g["profit"].mean(), "roi_se": g["profit"].std(ddof=1) / math.sqrt(n) if n > 1 else np.nan,
                "z": z, "p_value": p, "n_fair": len(gf),
                "fair_hit_rate": gf["hit"].mean() if len(gf) else np.nan, "z_fair": zf, "p_fair": pf,
                "insufficient": n < MIN_N,
            })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["q_value"] = bh(out["p_value"].where(~out["insufficient"]))
    out["q_fair"] = bh(out["p_fair"].where(out["n_fair"] >= MIN_N))
    # ROI t-test (normal approx): flat-stake profit per bet vs 0
    out["p_roi"] = [math.erfc(abs(r / se) / math.sqrt(2)) if se and se > 0 else np.nan
                    for r, se in zip(out["roi"], out["roi_se"])]
    # beats the closing price: more hits than the price implies (BH-significant) AND a significantly positive ROI
    out["beats_price"] = (out["z"] > 0) & (out["q_value"] < ALPHA) & (out["roi"] > 0) & (out["p_roi"] < ALPHA)
    out["bias_vs_fair"] = np.where(out["q_fair"] < ALPHA, np.where(out["z_fair"] > 0, "underpriced", "overpriced"), "")
    return out


DIMENSIONS = ["market_key", "family", "league_code", "odds_band", "outcome", "fav_long", "mbs",
              "weekday", "kickoff_hour", "movement", "hit_source"]


def walk_forward(d: pd.DataFrame, dims: list[str]) -> tuple[pd.DataFrame, str | None]:
    dates = sorted(d["date"].unique())
    if len(dates) < 4:
        return pd.DataFrame(), None
    cut = dates[int(len(dates) * 0.7) - 1]
    train, test = d[d["date"] <= cut], d[d["date"] > cut]
    tr, te = segment_stats(train, dims), segment_stats(test, dims)
    if tr.empty:
        return pd.DataFrame(), cut
    m = tr.merge(te, on=["dimension", "segment"], how="left", suffixes=("_train", "_test"))
    # a) positive ROI on old data that stays positive and significant on new data
    m["survived_roi"] = (m["beats_price_train"].fillna(False).astype(bool) & (m["roi_test"] > 0)
                         & (m["p_value_test"] < ALPHA) & (m["n_test"] >= 30))
    # b) mispricing vs fair probability (margin removed) in the same direction on new data
    m["survived_bias"] = ((m["bias_vs_fair_train"].fillna("") != "") & (np.sign(m["z_fair_train"]) == np.sign(m["z_fair_test"]))
                          & (m["p_fair_test"] < ALPHA) & (m["n_fair_test"] >= 30))
    m["survived"] = m["survived_roi"] | m["survived_bias"]
    return m, cut


# ---------------------------------------------------------------- cross-market (one row per match)
def match_table(d_all: pd.DataFrame) -> pd.DataFrame:
    m = d_all.drop_duplicates("match_id")[["match_id", "date", "league_code", "ht_home", "ht_away", "ft_home", "ft_away",
                                           "corners_home", "corners_away", "card_pts_home", "card_pts_away", "result_type"]]
    m = m[m["result_type"] == "final"].copy()
    for c in ("ht_home", "ht_away", "ft_home", "ft_away", "corners_home", "corners_away", "card_pts_home", "card_pts_away"):
        m[c] = pd.to_numeric(m[c], errors="coerce")
    fav = d_all[(d_all["market_key"] == "1X2")].dropna(subset=["closing_odds"])
    fav = fav.loc[fav.groupby("match_id")["closing_odds"].idxmin()][["match_id", "selection", "closing_odds"]]
    fav.columns = ["match_id", "fav_side", "fav_odds"]
    return m.merge(fav, on="match_id", how="left")


def _sign(x):
    return np.select([x > 0, x < 0], ["home", "away"], "draw")


def cross_market(mt: pd.DataFrame) -> dict[str, pd.DataFrame | str]:
    out: dict[str, pd.DataFrame | str] = {}
    g = mt.dropna(subset=["ft_home", "ft_away"])
    if g.empty:
        return out
    total = g["ft_home"] + g["ft_away"]
    btts = (g["ft_home"] > 0) & (g["ft_away"] > 0)
    over = total > 2.5
    ct = pd.crosstab(btts.map({True: "BTTS yes", False: "BTTS no"}), over.map({True: "Over 2.5", False: "Under 2.5"}))
    phi = np.corrcoef(btts.astype(int), over.astype(int))[0, 1] if len(g) > 2 else np.nan
    out["btts_ou"] = ct
    out["btts_ou_note"] = f"n = {len(g)} matches, phi = {phi:.3f}"
    h = g.dropna(subset=["ht_home", "ht_away"])
    if len(h):
        tm = pd.crosstab(pd.Series(_sign(h["ht_home"] - h["ht_away"]), name="HT"),
                         pd.Series(_sign(h["ft_home"] - h["ft_away"]), name="FT"), normalize="index").round(3)
        tm["n"] = pd.Series(_sign(h["ht_home"] - h["ht_away"])).value_counts()
        out["ht_ft"] = tm
    f = g.dropna(subset=["fav_side", "fav_odds"])
    f = f[f["fav_side"].isin(["home", "away"])]
    if len(f):
        margin = np.where(f["fav_side"] == "home", f["ft_home"] - f["ft_away"], f["ft_away"] - f["ft_home"])
        f = f.assign(fav_win=margin > 0, fav_win2=margin >= 2, band=f["fav_odds"].map(band_of))
        t = f.groupby("band").agg(n=("fav_win", "size"), fav_win_rate=("fav_win", "mean"),
                                  win_by_2plus_rate=("fav_win2", "mean")).round(3)
        t["share_of_wins_by_2plus"] = (f[f["fav_win"]].groupby("band")["fav_win2"].mean()).round(3)
        out["favourite_handicap"] = t
    c = g.dropna(subset=["corners_home", "corners_away"])
    if len(c) > 2:
        corners = c["corners_home"] + c["corners_away"]
        goals = c["ft_home"] + c["ft_away"]
        out["corners_goals_note"] = (f"n = {len(c)} matches, Spearman rho(corners, goals) = "
                                     f"{corners.rank().corr(goals.rank()):.3f}, mean corners {corners.mean():.2f}")
    k = g.dropna(subset=["card_pts_home", "card_pts_away"])
    if len(k) > 2:
        pts = k["card_pts_home"] + k["card_pts_away"]
        tight = (k["ft_home"] - k["ft_away"]).abs()
        note = f"n = {len(k)} matches, Spearman rho(card points, |goal difference|) = {pts.rank().corr(tight.rank()):.3f}"
        kk = k.dropna(subset=["fav_odds"])
        if len(kk) > 2:
            note += (f"; rho(card points, favourite price) = "
                     f"{(kk['card_pts_home'] + kk['card_pts_away']).rank().corr(kk['fav_odds'].rank()):.3f} (n = {len(kk)})")
        out["cards_tightness_note"] = note
    return out


# ---------------------------------------------------------------- charts
def _style(ax, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_facecolor(SURFACE)
    ax.figure.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_title(title, color=INK, fontsize=12, loc="left", pad=12)
    ax.set_xlabel(xlabel, color=INK2, fontsize=9)
    ax.set_ylabel(ylabel, color=INK2, fontsize=9)


def chart_calibration(seg: pd.DataFrame, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    s = seg[seg["dimension"] == "odds_band"].copy()
    s["order"] = s["segment"].map({b: i for i, b in enumerate(BAND_LABELS)})
    s = s.sort_values("order")
    fig, ax = plt.subplots(figsize=(7.5, 5), dpi=150)
    ax.plot([0, 1], [0, 1], color=INK2, linewidth=1, linestyle=(0, (4, 3)), label="hit rate = implied")
    ax.errorbar(s["mean_implied"], s["hit_rate"], yerr=[s["hit_rate"] - s["ci_low"], s["ci_high"] - s["hit_rate"]],
                fmt="o", color=BLUE, ecolor=BLUE, elinewidth=1.5, markersize=7, capsize=0, label="odds band (95% CI)")
    for _, r in s.iterrows():
        ax.annotate(f"{r['segment']}\nn={r['n']:,}", (r["mean_implied"], r["hit_rate"]), textcoords="offset points",
                    xytext=(8, -4), fontsize=7, color=INK2)
    lim = max(0.05, float(np.nanmax(np.r_[s["mean_implied"], s["ci_high"]])) + 0.05) if len(s) else 1
    ax.set_xlim(0, min(1, lim))
    ax.set_ylim(0, min(1, lim))
    _style(ax, "Calibration: actual hit rate vs implied probability", "implied probability (1 / closing odds)", "hit rate")
    ax.legend(frameon=False, fontsize=8, labelcolor=INK2, loc="upper left")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def chart_roi(seg: pd.DataFrame, dim: str, title: str, path: Path, order: list[str] | None = None, top: int = 15) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    s = seg[(seg["dimension"] == dim)].copy()
    if order:
        s["o"] = s["segment"].map({v: i for i, v in enumerate(order)})
        s = s.sort_values("o")
    else:
        s = s.sort_values("n", ascending=False).head(top).sort_values("roi")
    fig, ax = plt.subplots(figsize=(7.5, max(3, 0.32 * len(s) + 1.5)), dpi=150)
    y = np.arange(len(s))
    ax.barh(y, s["roi"] * 100, height=0.6, color=BLUE, edgecolor=SURFACE, linewidth=2)
    ax.errorbar(s["roi"] * 100, y, xerr=1.96 * s["roi_se"] * 100, fmt="none", ecolor=INK2, elinewidth=1)
    ax.axvline(0, color=INK2, linewidth=1)
    ax.set_yticks(y, [f"{a}  (n={n:,})" for a, n in zip(s["segment"], s["n"])])
    _style(ax, title, "flat-stake ROI % at closing odds (±95%)", "")
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def chart_movement(d: pd.DataFrame, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    m = d.dropna(subset=["movement"])
    m = m[m["movement"].isin(["shortening", "drifting"])]
    if m.empty:
        return
    fig, ax = plt.subplots(figsize=(7.5, 5), dpi=150)
    ax.plot([0, 1], [0, 1], color=INK2, linewidth=1, linestyle=(0, (4, 3)), label="hit rate = implied")
    for (name, g), color, off in zip(m.groupby("movement"), [ORANGE, BLUE], [-0.004, 0.004]):
        rows = []
        for band, gb in g.groupby("odds_band"):
            lo, hi = wilson(gb["hit"].sum(), len(gb))
            rows.append((gb["implied"].mean(), gb["hit"].mean(), lo, hi, len(gb)))
        r = pd.DataFrame(rows, columns=["imp", "hr", "lo", "hi", "n"]).sort_values("imp")
        ax.errorbar(r["imp"] + off, r["hr"], yerr=[r["hr"] - r["lo"], r["hi"] - r["hr"]], fmt="o-", color=color,
                    linewidth=2, markersize=6, elinewidth=1, capsize=0, label=f"{name} (n={len(g):,})")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    _style(ax, "Odds movement: shortening vs drifting selections", "implied probability at closing", "hit rate")
    ax.legend(frameon=False, fontsize=8, labelcolor=INK2, loc="upper left")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


# ---------------------------------------------------------------- report
def _pct(x, digits=1):
    return "" if pd.isna(x) else f"{x * 100:.{digits}f}%"


def _fmt_seg_table(s: pd.DataFrame, limit: int = 25) -> str:
    if s.empty:
        return "_no data_\n"
    lines = ["| dimension | segment | n | hit rate (95% CI) | implied | fair | ROI | q vs implied | q vs fair | |",
             "|---|---|---:|---|---:|---:|---:|---:|---:|---|"]
    for _, r in s.head(limit).iterrows():
        if r["insufficient"]:
            flag = "⚠️ n<100"
        else:
            flag = " ".join(x for x in ("💰 beats price" if r["beats_price"] else "",
                                        f"🔎 {r['bias_vs_fair']}" if r["bias_vs_fair"] else "") if x)
        q = lambda v: "" if pd.isna(v) else f"{v:.3f}"
        lines.append(f"| {r['dimension']} | {r['segment']} | {r['n']:,} | {_pct(r['hit_rate'])} "
                     f"({_pct(r['ci_low'])}–{_pct(r['ci_high'])}) | {_pct(r['mean_implied'])} | {_pct(r['mean_fair'])} | "
                     f"{_pct(r['roi'])} | {q(r['q_value'])} | {q(r['q_fair'])} | {flag} |")
    return "\n".join(lines) + "\n"


def _df_md(df: pd.DataFrame) -> str:
    if df is None or len(df) == 0:
        return "_no data_\n"
    df = df.reset_index()
    head = "| " + " | ".join(map(str, df.columns)) + " |\n|" + "---|" * len(df.columns) + "\n"
    return head + "\n".join("| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |" for row in df.values) + "\n"


def update_findings(wf: pd.DataFrame, seg_all: pd.DataFrame, today: str) -> pd.DataFrame:
    """Running log: new walk-forward survivors are added; existing ones re-checked on all data (holding/fading)."""
    path = REPORTS / "findings.csv"
    old = pd.read_csv(path, dtype=str) if path.exists() else pd.DataFrame(
        columns=["dimension", "segment", "direction", "first_seen", "last_checked", "status", "n", "roi", "q_value", "note"])
    cur = seg_all.set_index(["dimension", "segment"])
    rows = {(r["dimension"], r["segment"]): dict(r) for _, r in old.iterrows()}
    if not wf.empty:
        for _, r in wf[wf["survived"]].iterrows():
            key = (r["dimension"], r["segment"])
            if key not in rows:
                direction = "positive ROI" if r["survived_roi"] else f"{r['bias_vs_fair_train']} vs fair"
                rows[key] = {"dimension": key[0], "segment": key[1], "first_seen": today, "direction": direction,
                             "note": (f"train n={int(r['n_train'])} ROI {r['roi_train']:.1%} hit {r['hit_rate_train']:.1%} "
                                      f"fair {r['mean_fair_train']:.1%}; test n={int(r['n_test'])} ROI {r['roi_test']:.1%} "
                                      f"hit {r['hit_rate_test']:.1%} fair {r['mean_fair_test']:.1%}")}
    for key, row in rows.items():
        row["last_checked"] = today
        if key in cur.index:
            c = cur.loc[key]
            if row["direction"] == "positive ROI":
                holding, q = bool(c["beats_price"]), c["q_value"]
            else:
                holding, q = row["direction"].startswith(c["bias_vs_fair"] or "-"), c["q_fair"]
            row.update({"n": int(c["n"]), "roi": round(float(c["roi"]), 4),
                        "q_value": None if pd.isna(q) else round(float(q), 4),
                        "status": "holding" if holding else "fading"})
        else:
            row["status"] = "fading"
    out = pd.DataFrame(list(rows.values()), columns=old.columns)
    REPORTS.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False, lineterminator="\n")
    md = ["# Findings log", "",
          "Patterns that survived the walk-forward test (BH q < 0.05 on the older 70% of dates, same direction and "
          "p < 0.05 on the newer 30%). Re-checked every week on all data: **holding** = still significant in the same "
          "direction, **fading** = not any more. Only this project's Nesine data is used.", ""]
    if out.empty:
        md.append("_No pattern has survived out-of-sample yet._")
    else:
        md += ["| status | dimension | segment | direction | first seen | last checked | n | ROI | q | note |",
               "|---|---|---|---|---|---|---:|---:|---:|---|"]
        for _, r in out.sort_values(["status", "first_seen"]).iterrows():
            md.append(f"| {r['status']} | {r['dimension']} | {r['segment']} | {r['direction']} | {r['first_seen']} | "
                      f"{r['last_checked']} | {r['n']} | {r['roi']} | {r['q_value']} | {r['note']} |")
    (REPORTS / "findings.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return out


def analyze(today: str | None = None) -> dict:
    today = today or now_utc().astimezone(TR).date().isoformat()
    raw = load_rows()
    stats = {"report": None, "rows": int(len(raw))}
    REPORTS.mkdir(parents=True, exist_ok=True)
    img_dir = REPORTS / today
    img_dir.mkdir(parents=True, exist_ok=True)
    if raw.empty:
        (REPORTS / f"{today}.md").write_text(f"# Weekly analysis {today}\n\nNo settled data yet.\n", encoding="utf-8")
        return stats
    d = prepare(raw)
    seg = segment_stats(d, DIMENSIONS)
    wf, cut = walk_forward(d, DIMENSIONS)
    findings = update_findings(wf, seg, today)
    mt = match_table(raw)
    cross = cross_market(mt)

    # margins (one value per market instance)
    mk = raw.dropna(subset=["market_margin"]).drop_duplicates(["match_id", "market_key"])
    margin_market = mk.groupby("market_key")["market_margin"].agg(n="size", mean="mean", median="median").sort_values("n", ascending=False)
    margin_league = (mk[mk["market_key"] == "1X2"].groupby("league_code")["market_margin"]
                     .agg(n="size", mean="mean").sort_values("n", ascending=False))
    # official vs engine agreement
    st = read_table("settled")
    agree = pd.DataFrame()
    if not st.empty and "agree" in st:
        a = st[st["agree"].isin(["0", "1"])]
        if len(a):
            agree = a.groupby("market_key")["agree"].agg(n="size", agreement=lambda s: (s == "1").mean()).sort_values("n", ascending=False)
    # backfill check: post-match price vs our own closing snapshot
    chk = ""
    od = read_table("odds")
    if not od.empty and "snapshot_type" in od:
        key = ["event_code", "market_id", "selection_tr"]
        pre = od[od["snapshot_type"] != "post_match"].sort_values("snapshot_utc").groupby(key)["odds"].last()
        pm = od[od["snapshot_type"] == "post_match"].groupby(key)["odds"].last()
        both = pd.concat([pre.rename("pre"), pm.rename("pm")], axis=1, join="inner").apply(pd.to_numeric, errors="coerce").dropna()
        if len(both):
            chk = (f"Post-match price = our last pre-match price for {(both['pre'] == both['pm']).mean():.1%} of "
                   f"{len(both):,} selections (checks that backfilled closing prices are real pre-match prices).")

    chart_calibration(seg, img_dir / "calibration.png")
    chart_roi(seg, "odds_band", "Flat-stake ROI by odds band", img_dir / "roi_odds_band.png", order=BAND_LABELS)
    chart_roi(seg, "market_key", "Flat-stake ROI by market (15 largest)", img_dir / "roi_market.png")
    chart_movement(d, img_dir / "movement.png")

    def seg_of(dim, sort="n"):
        s = seg[seg["dimension"] == dim]
        return s.sort_values(sort, ascending=False)

    best = seg[seg["beats_price"] & ~seg["insufficient"]].sort_values("q_value")
    biased = seg[(seg["bias_vs_fair"] != "") & ~seg["insufficient"]].sort_values("q_fair")
    n_matches = raw["match_id"].nunique()
    dates = sorted(raw["date"].unique())
    md = [
        f"# Weekly analysis – {today}",
        "",
        f"Data: **{len(d):,} settled selections** with a closing price from **{n_matches:,} matches**, "
        f"{dates[0]} → {dates[-1]} ({len(dates)} match days). Only Nesine/Mackolik data collected by this project.",
        "",
        "## In short",
        "",
        f"- Segments tested: {len(seg):,}; with enough data (n ≥ {MIN_N}): {int((~seg['insufficient']).sum()):,}.",
        f"- 💰 Segments that **beat the closing price** (positive flat-stake ROI, BH q < 0.05): **{len(best)}**.",
        f"- 🔎 Segments **mispriced vs the fair probability** (margin removed, BH q < 0.05): **{len(biased)}** – "
        "useful to understand the market, but a bias smaller than the margin still loses money.",
        f"- Walk-forward: train ≤ {cut}, test after. Patterns that survived out-of-sample: "
        f"**{int(wf['survived'].sum()) if not wf.empty else 0}** → see [findings.md](findings.md)." if cut else
        "- Walk-forward: not enough match days yet (needs at least 4).",
        "- A negative ROI is normal: it is the bookmaker's margin. A segment is only interesting if it beats the implied "
        "probability *and* keeps doing so on newer data.",
        "",
    ]
    if chk:
        md += [f"- {chk}", ""]
    if len(best):
        md += ["### 💰 Beats the closing price", "", _fmt_seg_table(best), ""]
    if len(biased):
        md += ["### 🔎 Mispriced vs fair probability", "", _fmt_seg_table(biased, limit=30), ""]
    md += [
        "## 1. Calibration", "",
        f"![calibration]({today}/calibration.png)", "",
        "Points on the dashed line = the closing price was right on average. Above the line = selections won more "
        "often than the price implied.", "",
        "### By odds band", "", _fmt_seg_table(seg_of("odds_band").assign(
            o=lambda s: s["segment"].map({b: i for i, b in enumerate(BAND_LABELS)})).sort_values("o")), "",
        "### By market", "", _fmt_seg_table(seg_of("market_key")), "",
        "### By league (largest)", "", _fmt_seg_table(seg_of("league_code")), "",
        "### By MBS", "", _fmt_seg_table(seg_of("mbs")), "",
        "## 2. Flat-stake ROI by segment", "",
        f"![roi by odds band]({today}/roi_odds_band.png)", "",
        f"![roi by market]({today}/roi_market.png)", "",
        "### Home / draw / away (1X2)", "", _fmt_seg_table(seg_of("outcome")), "",
        "### Favourite / longshot (within each market)", "", _fmt_seg_table(seg_of("fav_long")), "",
        "### Weekday", "", _fmt_seg_table(seg_of("weekday")), "",
        "### Kickoff hour (Turkey time)", "", _fmt_seg_table(seg_of("kickoff_hour").sort_values("segment", key=lambda s: s.astype(int))), "",
        "## 3. Margin per market and league", "",
        "Margin = sum of implied probabilities − 1 (per market instance; DC counts 2 winners).", "",
        _df_md(margin_market.head(25).round(4)), "",
        "1X2 margin by league:", "", _df_md(margin_league.head(25).round(4)), "",
        "## 4. Odds movement", "",
        f"![movement]({today}/movement.png)" if (img_dir / "movement.png").exists() else "_No selection has both an opening and a closing snapshot yet._", "",
        "Shortening = closing price ≥ 2% below opening; drifting = ≥ 2% above. Needs both an opening and a closing snapshot.", "",
        _fmt_seg_table(seg_of("movement")), "",
        "## 5. Cross-market relationships", "",
        "**BTTS vs Over/Under 2.5** – " + str(cross.get("btts_ou_note", "no data")), "",
        _df_md(cross.get("btts_ou")), "",
        "**Half-time result → full-time result** (row share)", "", _df_md(cross.get("ht_ft")), "",
        "**Favourite and handicap** – how often the 1X2 favourite wins, and wins by 2+ (what a −1 handicap needs), "
        "by favourite's closing price", "", _df_md(cross.get("favourite_handicap")), "",
        "**Corners vs goals** – " + str(cross.get("corners_goals_note", "no data")), "",
        "**Cards vs match tightness** – " + str(cross.get("cards_tightness_note", "no data")), "",
        "## 6. Rigor and data quality", "",
        "- Hit-rate intervals: Wilson 95%. Tests: observed hits vs Σ implied probability (Poisson-binomial, normal "
        "approximation – equivalent to testing flat-stake ROI = 0), and vs Σ fair probability (margin removed). "
        "q = Benjamini–Hochberg over all segments with n ≥ 100, separately per test.",
        "- Walk-forward: segments are selected on the older 70% of match days and must repeat (same direction, "
        "p < 0.05, n ≥ 30) on the newer 30%. Survivors go to findings.md and are re-checked every week.",
        f"- n < {MIN_N} is flagged ⚠️ and never counts as a finding.",
        "- Card markets use `config/card_rules.yaml` (Nesine help article 742) and are engine-settled"
        + ("" if load("card_rules").get("include_in_analysis", True) else " – **excluded from this analysis**") + ".",
        "",
        "### How results were settled", "", _fmt_seg_table(seg_of("hit_source")), "",
        "### Official (Nesine) vs engine agreement per market", "",
        _df_md(agree.head(40).round(4)) if len(agree) else "_no overlapping settlements yet_\n", "",
    ]
    report = REPORTS / f"{today}.md"
    report.write_text("\n".join(md) + "\n", encoding="utf-8")

    summary = seg.copy()
    if not wf.empty:
        summary = summary.merge(wf[["dimension", "segment", "roi_train", "roi_test", "n_test", "p_value_test",
                                    "survived_roi", "survived_bias"]],
                                on=["dimension", "segment"], how="left")
    for c in ("hit_rate", "ci_low", "ci_high", "mean_implied", "mean_fair", "mean_odds", "roi", "roi_se", "z",
              "p_value", "q_value", "p_roi", "fair_hit_rate", "z_fair", "p_fair", "q_fair", "roi_train", "roi_test", "p_value_test"):
        if c in summary:
            summary[c] = summary[c].astype(float).round(4)
    EXPORTS.mkdir(parents=True, exist_ok=True)
    summary.to_csv(EXPORTS / "analysis_summary.csv", index=False, lineterminator="\n")
    stats.update({"report": str(report), "segments": len(seg), "beats_price": len(best), "biased": len(biased),
                  "findings": len(findings), "selections": len(d)})
    return stats
