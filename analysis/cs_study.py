"""Correct scores, full time and half time: signs, rules and a fair race for every score Nesine lists.

Every full-time score (CORRECT_SCORE: 0-0 ... 6-0 and 'other') and half-time score (HT_CORRECT_SCORE: 0-0 ... 2-2
and 'other') is a target, on the bb_data feature table (every finished game, every market, the four goal rates,
team habits per half, league, calendar). For each score:
- own chance: Nesine's chance for that score (cut spread over the listed scores); exists where Nesine lists scores
  (most games in 2024/25 and 2026/27, a third in 2025/26);
- model chance: the four goal rates as independent Poisson (fitted to goal and result markets, no score prices);
- single signs: direction and cut-offs on 2024/25; top 10% / 5% hit rate and AUC per season; 'beyond the price'
  AUC inside groups of games with the same own chance;
- rules: every 1- and 2-condition rule from the 40 strongest signs (bb_rules machinery), found on 2024/25, confirmed
  on 2025/26 (>= 1.3 x normal), examined on 2026/27, with a luck control on shuffled results; each rule is compared
  with the same number of games taken by the own chance (on the games where Nesine lists the score) and by the model;
- fair race: own chance, model and the best other single sign, each taking its top 5% / 10% of the games in each
  later season (games where Nesine lists the score);
- live: full-time score after each half-time score.
- team score habits (draws, 0-0, 1-1, low-scoring, half-time draws; last 20 and previous season) and a
  league x score check against Nesine's chance, with its own luck control.
Writes cache/cs_targets.parquet, cs_signs.parquet, cs_rules.parquet, cs_luck.parquet, cs_race.parquet,
cs_live.parquet, cs_leagues.parquet.
"""
from math import factorial
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bb_data  # noqa: E402
import bb_rules as br  # noqa: E402
from bb_signs import SEAS, features, found_on, pretty  # noqa: E402
from htft3_report import top_hits  # noqa: E402
from htft3_signs import strat_auc  # noqa: E402
from six_plus import auc  # noqa: E402

CACHE = bb_data.CACHE
FT = ["0-0", "0-1", "0-2", "0-3", "0-4", "0-5", "0-6", "1-0", "1-1", "1-2", "1-3", "1-4", "1-5", "2-0", "2-1", "2-2",
      "2-3", "2-4", "3-0", "3-1", "3-2", "3-3", "4-0", "4-1", "4-2", "5-0", "5-1", "6-0", "OTHER"]
HT = ["0-0", "0-1", "0-2", "1-0", "1-1", "1-2", "2-0", "2-1", "2-2", "OTHER"]
N_LUCK = 5


def pois(k, lam):
    return np.exp(-lam) * lam ** k / factorial(k)


def targets(d):
    """Adds y_/own_/mod_ columns for every score; returns [(name, market, key, ycol, owncol, modcol)]."""
    out, cols = [], {}
    lam = {"FT": (d["lam_h1"] + d["lam_h2"], d["lam_a1"] + d["lam_a2"]), "HT": (d["lam_h1"], d["lam_a1"])}
    goals = {"FT": (d["ft_home"], d["ft_away"]), "HT": (d["ht_home"], d["ht_away"])}
    for half, keys, mk, pre in (("FT", FT, "CORRECT_SCORE", "cs_"), ("HT", HT, "HT_CORRECT_SCORE", "hcs_")):
        lh, la = lam[half]
        gh, ga = goals[half]
        listed = np.zeros(len(d), bool)
        mod_listed = np.zeros(len(d))
        for k in keys:
            tag = f"{half} {k}"
            yc, oc, mc = f"y_{half}_{k}", f"own_{half}_{k}", f"mod_{half}_{k}"
            if k != "OTHER":
                h, a = map(int, k.split("-"))
                hit = ((gh == h) & (ga == a)).to_numpy()
                listed |= hit
                p = pois(h, lh) * pois(a, la)
                mod_listed = mod_listed + p.to_numpy()
                cols[yc], cols[mc] = hit.astype(int), p.to_numpy()
            else:
                cols[yc], cols[mc] = (~listed).astype(int), 1 - mod_listed
            cols[oc] = d[f"{pre}{k}"].to_numpy(float) if f"{pre}{k}" in d else np.full(len(d), np.nan)
            out.append((tag, mk, k, yc, oc, mc))
    return pd.concat([d, pd.DataFrame(cols, index=d.index)], axis=1), out


def score_habits(m):
    """Each team's last-20 and previous-season rates of score-shaped results (strictly earlier matches)."""
    rows = []
    for side, opp in (("home", "away"), ("away", "home")):
        gf, ga, hf, ha = m[f"ft_{side}"], m[f"ft_{opp}"], m[f"ht_{side}"], m[f"ht_{opp}"]
        rows.append(pd.DataFrame({
            "match_id": m["match_id"], "team": m[f"{side}_team_id"], "kick": m["kickoff_utc"], "side": side,
            "per": m["per"], "draw": (gf == ga).astype(float), "nil_nil": ((gf == 0) & (ga == 0)).astype(float),
            "one_one": ((gf == 1) & (ga == 1)).astype(float), "low": ((gf + ga) <= 1).astype(float),
            "won_1_0": ((gf == 1) & (ga == 0)).astype(float), "lost_0_1": ((gf == 0) & (ga == 1)).astype(float),
            "ht_draw": (hf == ha).astype(float), "ht_nil_nil": ((hf == 0) & (ha == 0)).astype(float),
            "big_win": (gf - ga >= 3).astype(float), "goals": (gf + ga).astype(float)}))
    t = pd.concat(rows).sort_values(["team", "kick"]).reset_index(drop=True)
    ev = ["draw", "nil_nil", "one_one", "low", "won_1_0", "lost_0_1", "ht_draw", "ht_nil_nil", "big_win", "goals"]
    roll = t.groupby("team")[ev].transform(lambda s: s.shift(1).rolling(20, min_periods=10).mean())
    t[[f"sh20_{e}" for e in ev]] = roll.to_numpy()
    ps = t.groupby(["team", "per"])[ev].mean()
    ps.columns = [f"shps_{e}" for e in ev]
    ps = ps.reset_index()
    ps["per"] = ps["per"].map({"A": "B", "B": "C"})
    t = t.merge(ps.dropna(subset=["per"]), on=["team", "per"], how="left")
    feat = [c for c in t.columns if c.startswith(("sh20_", "shps_"))]
    h = t[t["side"] == "home"].set_index("match_id")[feat].add_prefix("home_")
    a = t[t["side"] == "away"].set_index("match_id")[feat].add_prefix("away_")
    return h.join(a)


def league_scores(d, T, min_games=150):
    """League x score: hit rate vs the chance Nesine gave (own chance, or the model where Nesine did not list
    scores) per season. 'Held' = above the chance AND >= 1.3 x the score's normal rate in all three seasons.
    Luck control: the same count when the league labels are shuffled among the games of each season (20 times),
    so a 'league' is a random group of games of the same size."""
    per = d["per"].to_numpy()
    lg = d["league"].to_numpy()
    rng = np.random.default_rng(7)
    labels = [lg]
    for _ in range(20):
        x = lg.copy()
        for k in "ABC":
            m = np.where(per == k)[0]
            x[m] = rng.permutation(lg[m])
        labels.append(x)
    groups = []
    for x in labels:
        g = {}
        for name in np.unique(x):
            g[name] = {k: np.where((x == name) & (per == k))[0] for k in "ABC"}
        groups.append(g)
    rows, counts = [], np.zeros(len(labels))
    for tag, mk, key, yc, oc, mc in T:
        y = d[yc].to_numpy(float)
        o = d[oc].to_numpy(float)
        ch = np.where(np.isnan(o), d[mc].to_numpy(float), o)
        normal = {k: y[per == k].mean() for k in "ABC"}
        for j, g in enumerate(groups):
            for name, ix in g.items():
                if any(len(ix[k]) < (min_games if k != "C" else 40) for k in "ABC"):
                    continue
                held = all(y[ix[k]].mean() > np.nanmean(ch[ix[k]]) and y[ix[k]].mean() >= 1.3 * normal[k]
                           for k in "ABC")
                counts[j] += held
                if j == 0:
                    r = {"score": tag, "league": name, "held": held}
                    for k, nm in SEAS.items():
                        r[f"games {nm}"] = len(ix[k])
                        r[f"hit % {nm}"] = y[ix[k]].mean() * 100
                        r[f"chance % {nm}"] = np.nanmean(ch[ix[k]]) * 100
                    rows.append(r)
    return pd.DataFrame(rows), counts[1:]


def scan(d, ycol, owncol, cols):
    y = d[ycol].to_numpy(float)
    per = d["per"].to_numpy()
    own = d[owncol].to_numpy(float)
    rows = []
    for c in cols:
        k0 = found_on(d, c)
        if k0 != "A":
            continue
        x = d[c].to_numpy(float)
        F = per == "A"
        a = auc(x[F], y[F])
        if a != a:
            continue
        s = x if a >= 0.5 else -x
        r = {"sign": c, "what": pretty(c), "direction": "high" if a >= 0.5 else "low"}
        thr = np.nanquantile(s[F], 0.9)
        for k, nm in SEAS.items():
            m = per == k
            mm = m & (s >= thr)
            r[f"top 10% hit % {nm}"] = y[mm].mean() * 100 if mm.sum() else np.nan
            r[f"top 10% matches {nm}"] = int(mm.sum())
            r[f"AUC {nm}"] = auc(s[m], y[m])
            r[f"beyond price AUC {nm}"] = strat_auc(s[m], y[m], own[m], 5) if c != owncol else 0.5
        rows.append(r)
    return pd.DataFrame(rows)


def subset_compare(d, y, own, mask, k):
    """Rule vs the same number of games with the highest own chance, both on season-k games where the own chance
    exists. Returns (games, rule hits, own-chance hits)."""
    m = (d["per"] == k).to_numpy() & ~np.isnan(own)
    n = int((mask & m).sum())
    if n == 0:
        return 0, 0.0, 0.0
    h_rule = float(y[mask & m].sum())
    h_own, _ = top_hits(own[m], y[m], n)
    return n, h_rule, h_own


def model_compare(d, y, mod, mask, k):
    m = (d["per"] == k).to_numpy() & ~np.isnan(mod)
    n = int((mask & m).sum())
    if n == 0:
        return np.nan
    h, _ = top_hits(mod[m], y[m], n)
    return h / n * 100


def race(d, y, own, mod, other, k_shares=(0.05, 0.10)):
    per = d["per"].to_numpy()
    rows = []
    for name, sc in (("own chance", own), ("model chance", mod), ("best other single sign", other)):
        for share in k_shares:
            H = N = E = 0.0
            r = {"technique": name, "share": f"top {int(share * 100)}%"}
            for k in ("B", "C"):
                m = (per == k) & ~np.isnan(own)
                n = int(round(share * m.sum()))
                h, n = top_hits(sc[m], y[m], n)
                nrm = y[m].mean()
                r[f"hit % {SEAS[k]}"] = h / n * 100 if n else np.nan
                H, N, E = H + h, N + n, E + nrm * n
            r["games (both)"], r["hit % (both)"], r["x normal"] = int(N), H / N * 100 if N else np.nan, H / E if E else np.nan
            rows.append(r)
    return rows


def live(d):
    x = d.assign(ht=d["ht_home"].astype(int).astype(str) + "-" + d["ht_away"].astype(int).astype(str),
                 ft=d["ft_home"].astype(int).astype(str) + "-" + d["ft_away"].astype(int).astype(str))
    g = x.groupby(["ht", "ft"]).size().rename("games").reset_index()
    g["share % of this half-time score"] = g["games"] / g.groupby("ht")["games"].transform("sum") * 100
    return g.sort_values(["ht", "games"], ascending=[True, False])


def run():
    d = bb_data.build()
    d = d.join(score_habits(bb_data.scope()), on="match_id")
    d, T = targets(d)
    L, lg_luck = league_scores(d, T)
    L.to_parquet(CACHE / "cs_leagues.parquet")
    pd.DataFrame({"run": range(len(lg_luck)), "held": lg_luck}).to_parquet(CACHE / "cs_leagues_luck.parquet")
    print("league x score held:", int(L["held"].sum()), "of", len(L), "| luck runs:", lg_luck.tolist(), flush=True)
    cols = [c for c in features(d) if not c.startswith(("y_", "own_", "mod_"))]
    d[[c for c in d.columns if c.startswith(("y_", "own_", "mod_"))] + ["match_id", "per"]].to_parquet(
        CACHE / "cs_targets.parquet")
    per = d["per"].to_numpy()
    sig_all, rules_all, luck_all, race_all = [], [], [], []
    for tag, mk, key, yc, oc, mc in T:
        y = d[yc].to_numpy(float)
        own, mod = d[oc].to_numpy(float), d[mc].to_numpy(float)
        normal = {k: y[per == k].mean() * 100 for k in "ABC"}
        S = scan(d, yc, oc, cols)
        S.insert(0, "score", tag)
        sig_all.append(S)
        # best other single sign, chosen on 2024/25 (not the score's own price)
        own_like = {oc, f"odds_{mk}||{key}", f"{'cs_' if mk == 'CORRECT_SCORE' else 'hcs_'}{key}"}
        cand = S[~S["sign"].isin(own_like)].sort_values("top 10% hit % 2024/25", ascending=False)
        bo = cand.iloc[0]
        xo = d[bo["sign"]].to_numpy(float)
        other = xo if bo["direction"] == "high" else -xo
        for r in race(d, y, own, mod, other):
            r.update({"score": tag, "best other sign": bo["what"]})
            race_all.append(r)
        sig = S[["sign", "direction"]]
        for pool, sr in (("scan-ready", True), ("all signs", False)):
            res, _ = br.run_one(d, y, sig, "A", sr)
            res["confirmed"] = (res["hit % 2025/26"] >= 1.3 * normal["B"]) & (res["matches 2025/26"] >= br.NMIN / 2)
            for k in ("B", "C"):
                cmp = [subset_compare(d, y, own, m, k) for m in res["_mask"]]
                res[f"games with own price {SEAS[k]}"] = [c[0] for c in cmp]
                res[f"rule hits there {SEAS[k]}"] = [c[1] for c in cmp]
                res[f"own-price hits, same games {SEAS[k]}"] = [c[2] for c in cmp]
                res[f"model, same size, % {SEAS[k]}"] = [model_compare(d, y, mod, m, k) for m in res["_mask"]]
            res["criteria"] = [br.criteria(r) for r in res["rule"]]
            res["rule"] = [br.text(r) for r in res["rule"]]
            res = res.drop(columns="_mask")
            res.insert(0, "pool", pool)
            res.insert(0, "score", tag)
            for k, nm in SEAS.items():
                res[f"normal % {nm}"] = normal[k]
            rules_all.append(res)
            for s in range(N_LUCK):
                lr, nl = br.run_one(d, y, sig, "A", sr, shuffle_seed=3000 + s)
                c = (lr["hit % 2025/26"] >= 1.3 * nl["B"]) & (lr["matches 2025/26"] >= br.NMIN / 2)
                luck_all.append({"score": tag, "pool": pool, "run": s, "confirmed": int(c.sum())})
        print(tag, "normal", {k: round(v, 2) for k, v in normal.items()}, "confirmed",
              int(rules_all[-2]["confirmed"].sum()), int(rules_all[-1]["confirmed"].sum()), "luck",
              [x["confirmed"] for x in luck_all[-2 * N_LUCK:]], flush=True)
    pd.concat(sig_all, ignore_index=True).to_parquet(CACHE / "cs_signs.parquet")
    pd.concat(rules_all, ignore_index=True).to_parquet(CACHE / "cs_rules.parquet")
    pd.DataFrame(luck_all).to_parquet(CACHE / "cs_luck.parquet")
    pd.DataFrame(race_all).to_parquet(CACHE / "cs_race.parquet")
    live(d).to_parquet(CACHE / "cs_live.parquet")


if __name__ == "__main__":
    run()
