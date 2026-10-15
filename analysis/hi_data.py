"""Data for the high-odds hit-rate study (cached in cache/hi_data.npz).

Targets: every bet type whose typical (median) Nesine odds are >= 4 and that wins >= 1% of matches, plus a few
combined bets. Outcomes are computed from the score (half-time and full-time), so every match counts, even when
Nesine did not offer that market.

Features (all known before kickoff; NaN where missing):
  odds      log closing odds of all ~160 selection types
  fair      Nesine's chance for each selection (its cut removed within the market)
  disagree  Nesine's chance / the chance its other markets imply (goal-rate model)
  model     the four goal rates fitted to Nesine's core prices, their fit error, expected corners
  form      rolling team form (rules_v3_data / ml_data): goals, shots, corners, points, vs expected ...
  last      each team's previous match and the previous meeting of the two teams
  context   league (number), season stage, hour, weekday, month
  margin    Nesine's cut on six main markets
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load  # noqa: E402
import miner_data as mdat  # noqa: E402
import ml_data as md  # noqa: E402
import rules_v3_data as v3  # noqa: E402
from htft_data import CACHE  # noqa: E402
from rule_miner import nice  # noqa: E402

OUT = CACHE / "hi_data.npz"
MIN_MED_ODDS, MIN_RATE = 4.0, 0.01


def cells(m):
    """(h1, a1, h2, a2) cell index of each match in the 8^4 grid of ml_data (goals capped at 7 per team-half)."""
    h1, a1 = m["ht_home"].to_numpy(float), m["ht_away"].to_numpy(float)
    h2, a2 = m["ft_home"].to_numpy(float) - h1, m["ft_away"].to_numpy(float) - a1
    ok = ~np.isnan(h1 + a1 + h2 + a2) & (h2 >= 0) & (a2 >= 0)
    c = [np.clip(np.nan_to_num(v), 0, md.G - 1).astype(int) for v in (h1, a1, h2, a2)]
    idx = ((c[0] * md.G + c[1]) * md.G + c[2]) * md.G + c[3]
    return idx, ok


def build(refresh=False):
    if OUT.exists() and not refresh:
        z = np.load(OUT, allow_pickle=True)
        return {k: z[k] for k in z.files}
    z = mdat.build()
    O, F, Hm, per, names, ids = z["O"], z["F"], z["Hm"], z["per"], list(z["names"]), z["match_ids"]
    m = load.matches().set_index("match_id").reindex(ids)
    idx, ok = cells(m)
    keys = {}
    for n in names:
        mk, _, sk = n.split("|")
        keys.setdefault(mk, []).append(sk)

    # ---- targets
    T, tnames, tkeys, tprice = [], [], [], []
    for i, n in enumerate(names):
        mk, line, sk = n.split("|")
        med = np.nanmedian(O[:, i])
        if not med >= MIN_MED_ODDS or sk == "OTHER":
            continue
        pm = md.predicate(mk, float(line) if line else None, sk, keys[mk])
        if pm is None:
            y = Hm[:, i]
        else:
            y = np.where(ok, pm[idx], np.nan)
        if np.nanmean(y) < MIN_RATE:
            continue
        T.append(y); tnames.append(nice(n)); tkeys.append(n); tprice.append(i)
    G = md
    extra = {
        "HT/FT comeback (1/2 or 2/1)": ((G.HT == "1") & (G.FT == "2")) | ((G.HT == "2") & (G.FT == "1")),
        "Draw with 4+ goals (2-2, 3-3 ...)": (G.FT == "X") & (G.T >= 4),
        "Total goals 6+ (any)": G.T >= 6,
        "Both teams score in both halves": (G.H1 > 0) & (G.A1 > 0) & (G.H2 > 0) & (G.A2 > 0),
        "Winner by 3+ goals": np.abs(G.HH - G.AA) >= 3,
        "Half-time draw, full-time not (X/1 or X/2)": (G.HT == "X") & (G.FT != "X"),
        "Home team scores 3+": G.HH >= 3,
        "Away team scores 3+": G.AA >= 3,
        "5+ goals and both score": (G.T >= 5) & (G.HH > 0) & (G.AA > 0),
        "2nd half has 3+ goals": G.T2 >= 3,
    }
    for k, pm in extra.items():
        T.append(np.where(ok, pm[idx], np.nan)); tnames.append(k); tkeys.append(k); tprice.append(-1)
    Y = np.stack(T, 1).astype(np.float32)
    # the same bet under two names (e.g. draw & over 2.5 = draw & over 3.5): keep the first
    seen, keep = set(), []
    for j in range(Y.shape[1]):
        h = np.nan_to_num(Y[:, j], nan=-1).tobytes()
        if h not in seen:
            seen.add(h); keep.append(j)
    Y = Y[:, keep]
    tnames, tkeys, tprice = ([v[j] for j in keep] for v in (tnames, tkeys, tprice))

    # ---- features
    feats, fnames, ffam = [], [], []

    def add(v, n, f):
        feats.append(np.asarray(v, np.float32)); fnames.append(n); ffam.append(f)

    for i, n in enumerate(names):
        if np.isnan(O[:, i]).mean() < .7:
            add(np.log(O[:, i]), f"odds: {nice(n)}", "odds")
            add(F[:, i], f"chance: {nice(n)}", "fair")
    mt, sel = md.build()
    sel = sel[sel["q"].notna()]
    sel["lab"] = [mdat.label(a, b, c) for a, b, c in zip(sel["market_key"], sel["line"], sel["selection_key"])]
    sel = sel[sel["lab"].isin(names)].drop_duplicates(["match_id", "lab"])
    Q = sel.pivot(index="match_id", columns="lab", values="q").reindex(index=ids, columns=names).to_numpy(np.float32)
    for i, n in enumerate(names):
        if np.isnan(Q[:, i]).mean() < .7 and np.isnan(F[:, i]).mean() < .7:
            add(F[:, i] / np.where(Q[:, i] > .002, Q[:, i], np.nan), f"disagree: {nice(n)}", "disagree")
    mt = mt.set_index("match_id").reindex(ids)
    for c in ("lam_h1", "lam_a1", "lam_h2", "lam_a2", "fit_rmse", "corners_exp"):
        add(mt[c], f"model: {c}", "model")
    for c in mt.columns:
        if c[:2] in ("h_", "a_") and c[2:] not in ("team_id",):
            add(mt[c], f"form: {c}", "form")
    lm = v3.last_match_table(ids)
    for c in lm.columns:
        add(lm[c], f"last: {c}", "last")
    L = pd.Index(sorted(set(z["league"])))
    add(L.get_indexer(z["league"]), "context: league", "context")
    kick = pd.DatetimeIndex(mt["kickoff_utc"]).tz_convert("Europe/Istanbul")
    add(mt["phase"], "context: season stage", "context")
    add(kick.hour + kick.minute / 60, "context: kick-off hour", "context")
    add(kick.weekday, "context: weekday", "context")
    add(kick.month, "context: month", "context")
    mks = np.array([n.split("|")[0] + "|" + n.split("|")[1] for n in names])
    for g, need in {"1X2|": 3, "OU|2.5": 2, "BTTS|": 2, "HT_FT|": 9, "HT_1X2|": 3, "OU|3.5": 2}.items():
        ix = np.where(mks == g)[0]
        if len(ix) == need:
            add((1 / O[:, ix]).sum(1) - 1, f"margin: {g}", "margin")
    X = np.stack(feats, 1)
    np.savez_compressed(OUT, Y=Y, tnames=np.array(tnames, dtype=object), tkeys=np.array(tkeys, dtype=object),
                        tprice=np.array(tprice), X=X, fnames=np.array(fnames, dtype=object),
                        ffam=np.array(ffam, dtype=object), per=per, ids=ids, league=z["league"],
                        leagues=np.array(L, dtype=object), O=O, F=F, Q=Q, names=np.array(names, dtype=object))
    return build()


if __name__ == "__main__":
    d = build(refresh=True)
    print("targets", d["Y"].shape, "features", d["X"].shape)
    print(pd.Series(d["ffam"]).value_counts().to_string())
    for n, y in zip(d["tnames"], d["Y"].T):
        print(f"{n:45s} {np.nanmean(y) * 100:5.1f}%  n={(~np.isnan(y)).sum()}")
