"""Rule hunt v4: money-focused scans. Where does Nesine's pricing slip, every season?

For every priced bet type (~160 selections) and each dimension below, the matches are split into cells and the
return per 100 staked (at closing odds) is measured in A (2024/25 + 2024), B (2025/26 + 2025), C (2026/27 + 2026).
  odds      the bet's own odds band (10 bands cut on period A)
  cut       Nesine's cut on that market in that match (5 bands cut on A)
  league    the 26 leagues
  weekday / hour / month / stage   calendar
  rest_home / rest_away             days since the team's previous match (<=3, 4-5, 6-8, 9+)
  league_x_odds                     league x the bet's own odds tercile
A cell is kept when it made money in A, B AND C (A, B >= 60 bets; C >= 15) and its return z-score over all
periods is >= 2. Luck control: 20 runs per dimension with the cell labels shuffled across matches within each period.
Writes cache/rules_v4.parquet and cache/rules_v4_luck.parquet.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hi_data  # noqa: E402
import miner_data as mdat  # noqa: E402
from dashboard import leagues  # noqa: E402
from htft_data import CACHE  # noqa: E402
from rule_miner import nice  # noqa: E402

SHUFFLES = 20
P = "ABC"


def bins(v, A, nb):
    e = np.unique(np.nanquantile(v[A], np.linspace(0, 1, nb + 1)))
    if len(e) < 3:
        return np.full(len(v), -1), []
    e[0], e[-1] = -np.inf, np.inf
    code = np.digitize(v, e[1:-1])
    code = np.where(np.isnan(v), -1, code)
    labs = []
    for k in range(len(e) - 1):
        lo, hi = e[k], e[k + 1]
        labs.append(f"≤ {hi:.2f}" if lo == -np.inf else f"> {lo:.2f}" if hi == np.inf else f"{lo:.2f}–{hi:.2f}")
    return code, labs


def cell_stats(code, ret, per, ncode):
    """per period: bets, return sum, return sum of squares, per code."""
    out = {}
    for p in P:
        m = (per == p) & (code >= 0) & ~np.isnan(ret)
        out[p] = (np.bincount(code[m], minlength=ncode), np.bincount(code[m], weights=ret[m], minlength=ncode),
                  np.bincount(code[m], weights=ret[m] ** 2, minlength=ncode))
    return out


def passing(st):
    n = sum(st[p][0] for p in P)
    s = sum(st[p][1] for p in P)
    s2 = sum(st[p][2] for p in P)
    z = s / np.sqrt(np.maximum(s2 - s ** 2 / np.maximum(n, 1), 1e-9))
    ok = (st["A"][0] >= 60) & (st["B"][0] >= 60) & (st["C"][0] >= 15) & (z >= 2)
    for p in P:
        ok &= st[p][1] > 0
    return ok, z


def run():
    z = mdat.build()
    d = hi_data.build()
    O, Hm, per, names = z["O"], z["Hm"], z["per"], list(z["names"])
    A = per == "A"
    fn = list(d["fnames"])
    feat = lambda n: d["X"][:, fn.index(n)]
    lg = z["league"].astype(str)
    L = sorted(set(lg))
    lgc = pd.Index(L).get_indexer(lg)
    hour = feat("context: kick-off hour")
    hour_c = np.digitize(hour, [16, 19, 21, 22])
    hour_l = ["before 16:00", "16:00–19:00", "19:00–21:00", "21:00–22:00", "22:00 or later"]
    stage = feat("context: season stage")
    stage_c = np.where(np.isnan(stage), -1, np.digitize(stage, [.1, .5, .9]))
    stage_l = ["first 10% of season", "rest of 1st half", "2nd half (before the end)", "last 10% of season"]
    rest = {s: feat(f"form: {s}_rest") for s in ("h", "a")}
    rest_c = {s: np.where(np.isnan(v), -1, np.digitize(v, [3.5, 5.5, 8.5])) for s, v in rest.items()}
    rest_l = ["≤ 3 days", "4–5 days", "6–8 days", "9+ days"]
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    fixed = {
        "league": (lgc, [leagues().get(x, {}).get("en", x) for x in L]),
        "weekday": (feat("context: weekday").astype(int), days),
        "hour": (hour_c, hour_l),
        "month": (feat("context: month").astype(int) - 1, months),
        "stage": (stage_c, stage_l),
        "rest_home": (rest_c["h"], rest_l),
        "rest_away": (rest_c["a"], rest_l),
    }
    mks = np.array([n.split("|")[0] + "|" + n.split("|")[1] for n in names])
    rng = np.random.default_rng(11)
    rows, luck = [], {}
    for i, n in enumerate(names):
        o, y = O[:, i], Hm[:, i]
        ok = ~np.isnan(o) & ~np.isnan(y)
        if ok.sum() < 3000:
            continue
        ret = np.where(ok, y * o - 1, np.nan)
        grp = np.where(mks == mks[i])[0]
        cut = (1 / O[:, grp]).sum(1) - 1 if len(grp) >= 2 else np.full(len(o), np.nan)
        oc, ol = bins(np.where(ok, o, np.nan), A & ok, 10)
        cc, cl = bins(np.where(ok, cut, np.nan), A & ok, 5)
        t3, _ = bins(np.where(ok, o, np.nan), A & ok, 3)
        lxo = np.where((lgc >= 0) & (t3 >= 0), lgc * 3 + t3, -1)
        lxo_l = [f"{lab} & odds tercile {k + 1}" for lab in fixed["league"][1] for k in range(3)]
        dims = dict(fixed, odds=(oc, ol), cut=(cc, [f"cut {x}" for x in cl]), league_x_odds=(lxo, lxo_l))
        for dim, (code, labs) in dims.items():
            if not len(labs):
                continue
            nc = len(labs)
            code = np.where(ok, code, -1)
            st = cell_stats(code, ret, per, nc)
            good, zz = passing(st)
            for k in np.where(good)[0]:
                row = {"bet_key": n, "bet": nice(n), "dimension": dim, "cell": labs[k], "z_all": zz[k]}
                for p in P:
                    nn, ss = st[p][0][k], st[p][1][k]
                    row.update({f"bets_{p}": int(nn), f"return_per_100_{p}": ss / nn * 100})
                    hh = np.bincount(code[(per == p) & (code >= 0)], weights=y[(per == p) & (code >= 0)],
                                     minlength=nc)[k]
                    row[f"hit_{p}"] = hh / nn * 100
                rows.append(row)
            cnt = []
            for s in range(SHUFFLES):
                cs = code.copy()
                for p in P:
                    ix = np.where((per == p) & (code >= 0))[0]
                    cs[ix] = rng.permutation(code[ix])
                cnt.append(int(passing(cell_stats(cs, ret, per, nc))[0].sum()))
            luck.setdefault(dim, np.zeros(SHUFFLES))
            luck[dim] += np.array(cnt)
        print(f"{nice(n)[:40]:40s} kept so far {len(rows)}", flush=True)
    r = pd.DataFrame(rows)
    lk = pd.DataFrame({"dimension": list(luck), "luck_mean": [v.mean() for v in luck.values()],
                       "luck_max": [v.max() for v in luck.values()]})
    lk["real"] = lk["dimension"].map(r.groupby("dimension").size() if len(r) else {}).fillna(0).astype(int)
    r.to_parquet(CACHE / "rules_v4.parquet")
    lk.to_parquet(CACHE / "rules_v4_luck.parquet")
    return r, lk


if __name__ == "__main__":
    r, lk = run()
    pd.set_option("display.width", 250)
    print(lk.to_string())
    if len(r):
        print(r.sort_values("z_all", ascending=False).round(1).head(40).to_string())
