"""High-scoring correct scores 3-2, 2-3, 3-3, 2-4, 4-2: a focused second pass (after cs_study.py).

Each is rare (1-3% of games), so besides the scores one by one this looks at them as a group (both teams 2+ goals,
5-6 goals in total) and as packs (the most likely of the five, backed together).
For every score, on the games where Nesine lists scores (2025/26 + 2026/27 pooled, sign choices fixed in advance or
found on 2024/25), each technique takes the same share of games (top 2 / 5 / 10%) and is compared:
- own chance: Nesine's chance for the score;  model: the four goal rates as independent Poisson;
- markets that describe the score directly: result & over 4.5 goals (3-3 = draw & over 4.5; 3-2 / 4-2 = home win &
  over 4.5; 2-3 / 2-4 = away win & over 4.5), both teams 2+ goals (team-goals markets), the 4-5 / 6+ goal ranges,
  result & both score, and products of them;
- own chance x (own / model): Nesine's own view where it disagrees with the goal markets;
- logistic regression on these log-chances, trained on 2024/25.
Rules: every 1- and 2-condition rule from these hand-picked signs (fewer signs = fewer lucky rules), found on 2024/25,
confirmed on 2025/26, examined on 2026/27, with 10 shuffled-results luck runs; compared with the same games taken by
the own chance. Packs: back the k most likely of the five (k = 1, 2, 3) when their chances add up to the top 5% /
10% of 2024/25. Live: each score after each half-time score.
Writes cache/cs_high_race.parquet, cs_high_rules.parquet, cs_high_luck.parquet, cs_high_packs.parquet,
cs_high_live.parquet.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bb_data  # noqa: E402
import bb_rules as br  # noqa: E402
from bb_signs import SEAS  # noqa: E402
from cs_study import subset_compare  # noqa: E402
from htft3_report import top_hits  # noqa: E402
from six_plus import auc  # noqa: E402

CACHE = bb_data.CACHE
SCORES = ["3-2", "2-3", "3-3", "2-4", "4-2"]
RESULT = {"3-2": "1", "4-2": "1", "2-3": "2", "2-4": "2", "3-3": "X"}
RANGE = {"3-2": "4-5", "2-3": "4-5", "3-3": "6+", "2-4": "6+", "4-2": "6+"}
SHARES = (0.02, 0.05, 0.10)


def load():
    d = bb_data.build()
    t = pd.read_parquet(CACHE / "cs_targets.parquet")
    keep = ["match_id"] + [c for c in t.columns if any(c.endswith(f"FT_{s}") for s in SCORES)]
    d = d.merge(t[keep], on="match_id", how="left")
    own = d[[f"own_FT_{s}" for s in SCORES]]
    d["own_FT_group"] = own.sum(axis=1, min_count=len(SCORES))
    d["y_FT_group"] = d[[f"y_FT_{s}" for s in SCORES]].max(axis=1)
    d["mod_FT_group"] = d[[f"mod_FT_{s}" for s in SCORES]].sum(axis=1)
    return d


def signs_for(d, s):
    """Hand-picked signs for score s (higher = more likely): (column or series, name)."""
    r, g = RESULT[s], RANGE[s]
    both2 = d["f_TEAM_OU_HOME_1.5_OVER"] * d["f_TEAM_OU_AWAY_1.5_OVER"]
    res45 = d[f"f_1X2_AND_OU_4.5_{r}&OVER"]
    out = {
        "own chance": d[f"own_FT_{s}"],
        "goals model": d[f"mod_FT_{s}"],
        f"result {r} & over 4.5": res45,
        "both teams 2+ goals": both2,
        f"goal range {g}": d[f"f_GOAL_RANGE__{g}"],
        f"result {r} & both score": d[f"f_1X2_AND_BTTS__{r}&YES"],
        f"result {r} & over 4.5 x both teams 2+": res45 * both2,
        f"result {r} & both score x goal range {g}": d[f"f_1X2_AND_BTTS__{r}&YES"] * d[f"f_GOAL_RANGE__{g}"],
        "own chance x (own / model)": d[f"own_FT_{s}"] ** 2 / d[f"mod_FT_{s}"],
        "the five high scores together (own)": d["own_FT_group"],
    }
    return {k: v.to_numpy(float) for k, v in out.items()}


def logistic(d, s, names, sig):
    y = d[f"y_FT_{s}"].to_numpy(float)
    per = d["per"].to_numpy()
    X = np.column_stack([np.log(np.clip(sig[n], 1e-6, None)) for n in names])
    ok = ~np.isnan(X).any(axis=1)
    tr = ok & (per == "A")
    mu, sd = X[tr].mean(0), X[tr].std(0) + 1e-9
    lr = LogisticRegression(C=0.5, max_iter=2000).fit((X[tr] - mu) / sd, y[tr])
    p = np.full(len(d), np.nan)
    p[ok] = lr.predict_proba((X[ok] - mu) / sd)[:, 1]
    return p


def race(d, s, sig):
    """Each technique takes its top share of the games where the own chance exists, in 2025/26 and 2026/27."""
    y = d[f"y_FT_{s}"].to_numpy(float)
    per = d["per"].to_numpy()
    base = ~np.isnan(sig["own chance"])
    rows = []
    for name, sc in sig.items():
        r = {"score": s, "technique": name}
        A = (per == "A") & base & ~np.isnan(sc)
        r["AUC 2024/25"] = auc(sc[A], y[A])
        for share in SHARES:
            H = N = E = 0.0
            for k in ("B", "C"):
                m = (per == k) & base
                n = int(round(share * m.sum()))
                h, n = top_hits(np.where(np.isnan(sc[m]), -np.inf, sc[m]), y[m], n)
                H, N, E = H + h, N + n, E + y[m].mean() * n
            r[f"top {int(share * 100)}% hit %"] = H / N * 100
            r[f"top {int(share * 100)}% x normal"] = H / E
            r[f"top {int(share * 100)}% games"] = int(N)
        rows.append(r)
    return rows


def rules(d, s, sig, n_luck=10):
    """1-2 condition rules from the hand-picked signs (scan-ready ones only), found on 2024/25."""
    y = d[f"y_FT_{s}"].to_numpy(float)
    per = d["per"].to_numpy()
    r, g = RESULT[s], RANGE[s]
    cols = [f"cs_{s}", f"f_1X2_AND_OU_4.5_{r}&OVER", f"f_GOAL_RANGE__{g}", f"f_1X2_AND_BTTS__{r}&YES",
            "f_TEAM_OU_HOME_1.5_OVER", "f_TEAM_OU_AWAY_1.5_OVER", "f_OU_4.5_OVER", "f_1X2__1", "f_1X2__2", "f_1X2__X",
            "f_BTTS__YES", f"odds_1X2_AND_OU|3.5|{r}&OVER", "odds_HT_BTTS||YES", "odds_HT_OU|1.5|OVER",
            "f_TEAM_OU_HOME_2.5_OVER", "f_TEAM_OU_AWAY_2.5_OVER", "odds_GOAL_RANGE||6+", "odds_GOAL_RANGE||4-5"]
    cols = [c for c in cols if c in d]
    A = per == "A"
    signs = []
    for c in cols:
        x = d[c].to_numpy(float)
        a = auc(x[A], y[A])
        if a == a:
            signs.append({"sign": c, "direction": "high" if a >= 0.5 else "low"})
    sig_df = pd.DataFrame(signs)
    res, normal = br.run_one(d, y, sig_df, "A", True)
    res["confirmed"] = (res["hit % 2025/26"] >= 1.3 * normal["B"]) & (res["matches 2025/26"] >= br.NMIN / 2)
    own = sig["own chance"]
    for k in ("B", "C"):
        cmp = [subset_compare(d, y, own, m, k) for m in res["_mask"]]
        res[f"games with own price {SEAS[k]}"] = [c[0] for c in cmp]
        res[f"rule hits there {SEAS[k]}"] = [c[1] for c in cmp]
        res[f"own-price hits, same games {SEAS[k]}"] = [c[2] for c in cmp]
    res["criteria"] = [br.criteria(x) for x in res["rule"]]
    res["rule"] = [br.text(x) for x in res["rule"]]
    res = res.drop(columns="_mask")
    for k, nm in SEAS.items():
        res[f"normal % {nm}"] = normal[k]
    res.insert(0, "score", s)
    luck = []
    for i in range(n_luck):
        lr, nl = br.run_one(d, y, sig_df, "A", True, shuffle_seed=4000 + i)
        c = (lr["hit % 2025/26"] >= 1.3 * nl["B"]) & (lr["matches 2025/26"] >= br.NMIN / 2)
        luck.append({"score": s, "run": i, "confirmed": int(c.sum())})
    return res, luck


def packs(d):
    """Back the k most likely of the five (by own chance) when their chances add up to the top 5 / 10% of 2024/25."""
    per = d["per"].to_numpy()
    P = d[[f"own_FT_{s}" for s in SCORES]].to_numpy(float)
    Y = d[[f"y_FT_{s}" for s in SCORES]].to_numpy(float)
    ok = ~np.isnan(P).any(axis=1)
    rows = []
    for k in (1, 2, 3):
        order = np.argsort(-np.nan_to_num(P, nan=-1), axis=1)[:, :k]
        pp = np.take_along_axis(np.nan_to_num(P), order, 1).sum(1)
        hit = np.take_along_axis(Y, order, 1).max(1)
        for share in (0.05, 0.10):
            thr = float(np.nanquantile(pp[ok & (per == "A")], 1 - share))
            r = {"k": k, "share": share, "min pack chance": thr}
            for p, nm in SEAS.items():
                m = ok & (per == p)
                mm = m & (pp >= thr)
                r[f"games {nm}"], r[f"hit % {nm}"] = int(mm.sum()), hit[mm].mean() * 100
                r[f"same pack every game % {nm}"] = hit[m].mean() * 100
            rows.append(r)
    return pd.DataFrame(rows)


def live(d):
    x = d.assign(ht=d["ht_home"].astype(int).astype(str) + "-" + d["ht_away"].astype(int).astype(str),
                 ft=d["ft_home"].astype(int).astype(str) + "-" + d["ft_away"].astype(int).astype(str))
    rows = []
    for ht, g in x.groupby("ht"):
        if len(g) < 100:
            continue
        for s in SCORES:
            rows.append({"half-time": ht, "score": s, "games": len(g), "ends this score %": (g["ft"] == s).mean() * 100})
    return pd.DataFrame(rows)


def run():
    d = load()
    out_race, out_rules, out_luck = [], [], []
    for s in SCORES:
        sig = signs_for(d, s)
        names = [n for n in sig if n not in ("own chance x (own / model)", "the five high scores together (own)")]
        sig["logistic on these (trained on 2024/25)"] = logistic(d, s, names, sig)
        out_race += race(d, s, sig)
        res, luck = rules(d, s, sig)
        out_rules.append(res)
        out_luck += luck
        print(s, "rules confirmed", int(res["confirmed"].sum()), "luck", [x["confirmed"] for x in luck], flush=True)
    pd.DataFrame(out_race).to_parquet(CACHE / "cs_high_race.parquet")
    pd.concat(out_rules, ignore_index=True).to_parquet(CACHE / "cs_high_rules.parquet")
    pd.DataFrame(out_luck).to_parquet(CACHE / "cs_high_luck.parquet")
    packs(d).to_parquet(CACHE / "cs_high_packs.parquet")
    live(d).to_parquet(CACHE / "cs_high_live.parquet")


if __name__ == "__main__":
    run()
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 200)
    R = pd.read_parquet(CACHE / "cs_high_race.parquet")
    print(R.round(2).to_string(index=False))
    print(pd.read_parquet(CACHE / "cs_high_packs.parquet").round(2).to_string(index=False))
