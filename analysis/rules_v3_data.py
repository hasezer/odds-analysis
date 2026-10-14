"""Condition library for rule hunt v3: the price conditions of rules_deep plus six NEW kinds of information.

Every condition ("atom") is a yes/no per match, known before kickoff. Families:
  price     one selection's closing odds inside one of its 10 price ranges (period-A deciles)   (as rules_deep)
  equal     two odds within 0.10 of each other                                                 (as rules_deep)
  disagree  Nesine's chance for a selection vs the chance its OTHER markets imply (goal-rate model), quintiles
  form      a team's recent form: goals, shots on target, corners, points, scoring vs what the odds expected...
  last      what happened in each team's previous match, and in the last meeting of the two teams
  context   league, part of the season, weekday, kick-off time, month
  margin    the cut Nesine takes on a market, and how well its core prices fit one goal model
  corners   expected corners (from the corners line)
Bins are cut on period A only. Writes cache/v3_atoms.npz (X: N x K, aligned with cache/miner.npz).
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load  # noqa: E402
import miner_data as mdat  # noqa: E402
import ml_data as md  # noqa: E402
import rules_deep as rd  # noqa: E402
from htft_data import CACHE  # noqa: E402
from rule_miner import nice  # noqa: E402
from rules_targets import tr_labels  # noqa: E402
from dashboard import leagues  # noqa: E402

OUT = CACHE / "v3_atoms.npz"

FORM = {  # feature: (english, turkish, decimals)
    "r6_gf": ("avg goals scored, last 6", "son 6 maç attığı gol ort.", 2),
    "r6_ga": ("avg goals conceded, last 6", "son 6 maç yediği gol ort.", 2),
    "r6_res_gf": ("goals scored minus what the odds expected, last 6", "son 6 maç beklenenden fazla attığı gol", 2),
    "r6_res_ga": ("goals conceded minus what the odds expected, last 6", "son 6 maç beklenenden fazla yediği gol", 2),
    "r15_res_gf": ("goals scored minus expected, last 15", "son 15 maç beklenenden fazla attığı gol", 2),
    "r15_res_ga": ("goals conceded minus expected, last 15", "son 15 maç beklenenden fazla yediği gol", 2),
    "r6_sot": ("shots on target, last 6", "son 6 maç isabetli şut", 1),
    "r6_sota": ("shots on target allowed, last 6", "son 6 maç rakibin isabetli şutu", 1),
    "r6_cor": ("corners won, last 6", "son 6 maç kazandığı korner", 1),
    "r6_cora": ("corners conceded, last 6", "son 6 maç verdiği korner", 1),
    "r6_res_cor": ("match corners minus expected, last 6", "son 6 maç beklenenden fazla korner", 1),
    "r6_pts": ("points per game, last 6", "son 6 maç puan ort.", 2),
    "r6_poss": ("possession %, last 6", "son 6 maç topla oynama %", 0),
    "r6_sh2": ("2nd-half goals scored, last 6", "son 6 maç 2. yarı golü", 2),
    "rest": ("days since previous match", "önceki maçtan bu yana gün", 1),
    "r15_conv": ("finishing (goals above 30% of shots on target), last 15", "son 15 maç bitiricilik", 2),
}
SIDE = {"h": ("Home team", "Ev sahibi"), "a": ("Away team", "Deplasman")}


def qbins(v, A, nb, nd):
    """Atoms for the quantile bins of v (cut on period A): list of (mask, english range, turkish range)."""
    e = np.unique(np.round(np.nanquantile(v[A], np.linspace(0, 1, nb + 1)), nd))
    out = []
    for k in range(len(e) - 1):
        lo, hi = e[k], e[k + 1]
        m = (v > lo) & (v <= hi) if k else (v <= hi)
        if k == len(e) - 2:
            m = v > lo
        f = f"{{:.{nd}f}}"
        txt = f"≤ {f.format(hi)}" if k == 0 else f"> {f.format(lo)}" if k == len(e) - 2 else \
            f"{f.format(lo)}–{f.format(hi)}"
        out.append((np.nan_to_num(m).astype(bool) & ~np.isnan(v), txt, txt.replace(".", ",")))
    return out


def last_match_table(match_ids):
    """Previous match of each team, and previous meeting of the two teams (only matches finished before kickoff)."""
    m = load.matches()
    m = m[(m["status"] == "finished") & m["ft_home"].notna()].sort_values("kickoff_utc")
    rows = []
    for side in ("home", "away"):
        o = "away" if side == "home" else "home"
        rows.append(pd.DataFrame({"match_id": m["match_id"], "team": m[f"{side}_team_id"], "kick": m["kickoff_utc"],
                                  "venue": side, "gf": m[f"ft_{side}"], "ga": m[f"ft_{o}"],
                                  "hgf": m[f"ht_{side}"], "hga": m[f"ht_{o}"]}))
    t = pd.concat(rows).sort_values(["team", "kick"]).reset_index(drop=True)
    g = t.groupby("team")
    for c in ("gf", "ga", "hgf", "hga"):
        t[f"p_{c}"] = g[c].shift(1)
    t["p_days"] = (t["kick"] - g["kick"].shift(1)).dt.days
    p = t.set_index(["match_id", "venue"])[["p_gf", "p_ga", "p_hgf", "p_hga", "p_days"]]
    h = p.xs("home", level="venue").add_prefix("h_")
    a = p.xs("away", level="venue").add_prefix("a_")
    # previous meeting of the same two teams (either venue), seen from today's home team
    m["pair"] = [tuple(sorted(x)) for x in zip(m["home_team_id"], m["away_team_id"])]
    gg = m.groupby("pair")
    prev = pd.DataFrame({"match_id": m["match_id"],
                         "pm_home": gg["home_team_id"].shift(1), "pm_fh": gg["ft_home"].shift(1),
                         "pm_fa": gg["ft_away"].shift(1)}).set_index("match_id")
    cur = m.set_index("match_id")
    same = prev["pm_home"] == cur["home_team_id"]
    prev["pm_gf"] = np.where(same, prev["pm_fh"], prev["pm_fa"])      # goals of today's home team back then
    prev["pm_ga"] = np.where(same, prev["pm_fa"], prev["pm_fh"])
    prev.loc[prev["pm_home"].isna(), ["pm_gf", "pm_ga"]] = np.nan
    return h.join(a).join(prev[["pm_gf", "pm_ga"]]).reindex(match_ids)


def build(refresh=False):
    if OUT.exists() and not refresh:
        z = np.load(OUT, allow_pickle=True)
        return {k: z[k] for k in z.files}
    z = mdat.build()
    O, F, per, names, ids = z["O"], z["F"], z["per"], list(z["names"]), z["match_ids"]
    A = per == "A"
    N = len(ids)
    cols, en, tr, fam, mkt = [], [], [], [], []

    def add(mask, e, t, f, mk=()):
        mask = np.asarray(mask, bool)
        if mask[A].sum() < 100:            # too rare to ever pass the gates
            return
        cols.append(mask); en.append(e); tr.append(t); fam.append(f); mkt.append(",".join(sorted(mk)))

    # ---- price + equal (same as rules_deep)
    spec, lab, mk0 = rd.atoms(z)
    Xp = rd.masks(spec, O).astype(bool)
    for k, s in enumerate(spec):
        add(Xp[:, k], lab[k][0], lab[k][1], "price" if s[0] == "r" else "equal", mk0[k])

    # ---- disagree: Nesine's fair chance / goal-model chance, quintiles
    mt, sel = md.build()
    sel = sel[sel["q"].notna()]
    sel["lab"] = [mdat.label(a, b, c) for a, b, c in zip(sel["market_key"], sel["line"], sel["selection_key"])]
    sel = sel[sel["lab"].isin(names)].drop_duplicates(["match_id", "lab"])
    Q = sel.pivot(index="match_id", columns="lab", values="q").reindex(index=ids, columns=names).to_numpy(np.float32)
    ens, trs = [nice(n) for n in names], tr_labels(names)
    for i, n in enumerate(names):
        if np.isnan(Q[A, i]).mean() > .5 or np.isnan(F[A, i]).mean() > .5:
            continue
        ratio = F[:, i] / np.where(Q[:, i] > .005, Q[:, i], np.nan)
        for msk, te, tt in qbins(ratio, A, 5, 2):
            add(msk, f"{ens[i]}: Nesine's chance ÷ other markets' chance {te}",
                f"{trs[i]}: Nesine olasılığı ÷ diğer marketlerin olasılığı {tt}", "disagree", {n.split("|")[0]})

    # ---- form
    mt = mt.set_index("match_id").reindex(ids)
    for side, (se, st) in SIDE.items():
        for feat, (fe, ft, nd) in FORM.items():
            v = mt[f"{side}_{feat}"].to_numpy(float)
            for msk, te, tt in qbins(v, A, 5, nd):
                add(msk, f"{se} {fe} {te}", f"{st} {ft} {tt}", "form")
    both = (mt["h_r6_res_gf"] + mt["a_r6_res_gf"]).to_numpy(float)
    for msk, te, tt in qbins(both, A, 5, 2):
        add(msk, f"Both teams together scored minus expected, last 6 {te}",
            f"İki takım birlikte son 6 maç beklenenden fazla gol {tt}", "form")

    # ---- last match / last meeting
    lm = last_match_table(ids)
    for side, (se, st) in SIDE.items():
        gf, ga = lm[f"{side}_p_gf"].to_numpy(float), lm[f"{side}_p_ga"].to_numpy(float)
        hgf, hga = lm[f"{side}_p_hgf"].to_numpy(float), lm[f"{side}_p_hga"].to_numpy(float)
        ok = ~np.isnan(gf)
        ht = np.sign(hgf - hga); ft = np.sign(gf - ga)
        items = [
            (gf > ga, "won", "kazandı"), (gf == ga, "drew", "berabere kaldı"), (gf < ga, "lost", "kaybetti"),
            (gf + ga >= 4, "had 4+ goals", "4+ gollü bitti"), (gf + ga >= 5, "had 5+ goals", "5+ gollü bitti"),
            (gf + ga <= 1, "had 0-1 goals", "0-1 gollü bitti"), ((gf > 0) & (ga > 0), "both teams scored", "KG var"),
            ((gf == 0) & (ga == 0), "ended 0-0", "0-0 bitti"), (gf >= 3, "scored 3+", "3+ gol attı"),
            (ga >= 3, "conceded 3+", "3+ gol yedi"), (gf == 0, "failed to score", "gol atamadı"),
            (ga == 0, "kept a clean sheet", "gol yemedi"),
            ((ht * ft == -1), "was a comeback (HT/FT 1/2 or 2/1)", "dönüş maçıydı (İY/MS 1/2 ya da 2/1)"),
            ((ht == -1) & (ft == 1), "they came back to win", "geriden gelip kazandı"),
            ((ht == 1) & (ft == -1), "they lost a half-time lead", "devre önde olup kaybetti"),
            ((ht == 0) & (ft != 0), "was level at half time, not at full time", "devre berabere, maç değil"),
            (hgf + hga >= 2, "had 2+ first-half goals", "ilk yarı 2+ gol"),
            (np.abs(gf - ga) >= 3, "was won/lost by 3+", "3+ farklı bitti"),
        ]
        for s in ("2-1", "1-2", "3-2", "2-3", "3-1", "1-3", "2-2", "1-1", "1-0", "0-1", "2-0", "0-2", "3-0", "0-3"):
            x, y = map(int, s.split("-"))
            items.append(((gf == x) & (ga == y), f"ended {s} (their goals first)", f"{s} bitti (kendi golü önce)"))
        for msk, te, tt in items:
            add(np.nan_to_num(msk).astype(bool) & ok, f"{se}'s previous match {te}", f"{st} önceki maçı {tt}", "last")
        days = lm[f"{side}_p_days"].to_numpy(float)
        add(days <= 4, f"{se} played ≤ 4 days ago", f"{st} ≤ 4 gün önce oynadı", "last")
        add(days >= 14, f"{se} had 14+ days off", f"{st} 14+ gün dinlendi", "last")
    pgf, pga = lm["pm_gf"].to_numpy(float), lm["pm_ga"].to_numpy(float)
    ok = ~np.isnan(pgf)
    for msk, te, tt in [(pgf > pga, "today's home team won", "bugünkü ev sahibi kazandı"),
                        (pgf == pga, "was a draw", "berabere bitti"),
                        (pgf < pga, "today's away team won", "bugünkü deplasman kazandı"),
                        (pgf + pga >= 4, "had 4+ goals", "4+ gollü bitti"), (pgf + pga <= 1, "had 0-1 goals", "0-1 gollü"),
                        ((pgf > 0) & (pga > 0), "both teams scored", "KG var"),
                        (pgf + pga >= 3, "had 3+ goals", "3+ gollü bitti")]:
        add(np.nan_to_num(msk).astype(bool) & ok, f"Last meeting of these teams {te}", f"Son karşılaşma: {tt}", "last")

    # ---- context
    lg = leagues()
    league = z["league"]
    for l in sorted(set(league)):
        add(league == l, f"League: {lg.get(l, {}).get('en', l)}", f"Lig: {lg.get(l, {}).get('tr', l)}", "context")
    phase = mt["phase"].to_numpy(float)
    for lo, hi, te, tt in [(0, .1, "first 10% of the season", "sezonun ilk %10'u"),
                           (.1, .5, "first half of the season (after the start)", "sezonun ilk yarısı"),
                           (.5, .9, "second half of the season (before the end)", "sezonun ikinci yarısı"),
                           (.9, 1.01, "last 10% of the season", "sezonun son %10'u")]:
        add((phase > lo) & (phase <= hi) if lo else phase <= hi, f"Season stage: {te}", f"Sezon dönemi: {tt}", "context")
    kick = pd.DatetimeIndex(mt["kickoff_utc"]).tz_convert("Europe/Istanbul")
    wd, hr, mo = kick.weekday.to_numpy(), kick.hour.to_numpy(), kick.month.to_numpy()
    days_en = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    days_tr = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    for d in range(7):
        add(wd == d, f"Played on a {days_en[d]}", f"{days_tr[d]} günü oynandı", "context")
    for lo, hi in [(0, 16), (16, 19), (19, 21), (21, 22), (22, 24)]:
        add((hr >= lo) & (hr < hi), f"Kick-off {lo:02d}:00–{hi:02d}:00 (Turkey time)",
            f"Başlama saati {lo:02d}:00–{hi:02d}:00 (TR)", "context")
    mon_en = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    mon_tr = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım",
              "Aralık"]
    for k in range(12):
        add(mo == k + 1, f"Played in {mon_en[k]}", f"{mon_tr[k]} ayında oynandı", "context")

    # ---- margin: Nesine's cut per market, and how well its core prices fit one goal model
    mks = np.array([n.split("|")[0] + "|" + n.split("|")[1] for n in names])
    full = {"1X2|": 3, "OU|2.5": 2, "BTTS|": 2, "HT_FT|": 9, "HT_1X2|": 3, "OU|3.5": 2}
    for g, need in full.items():
        ix = np.where(mks == g)[0]
        if len(ix) != need:
            continue
        s = (1 / O[:, ix]).sum(1) - 1
        nm = nice(names[ix[0]]).rsplit(" ", 1)[0] if g != "OU|2.5" and g != "OU|3.5" else f"Over/under {g[3:]}"
        for msk, te, tt in qbins(s * 100, A, 5, 1):
            add(msk, f"Nesine's cut on {nm} (%) {te}", f"Nesine marjı, {nm} (%) {tt}", "margin", {g.split("|")[0]})
    rm = mt["fit_rmse"].to_numpy(float)
    for msk, te, tt in qbins(rm * 100, A, 5, 2):
        add(msk, f"How badly Nesine's core prices fit one goal model (×100) {te}",
            f"Nesine ana oranlarının gol modeline uyumsuzluğu (×100) {tt}", "margin")

    # ---- corners
    ce = mt["corners_exp"].to_numpy(float)
    for msk, te, tt in qbins(ce, A, 5, 1):
        add(msk, f"Expected corners (from the corners line) {te}", f"Beklenen korner {tt}", "corners", {"CORNERS_OU"})

    X = np.stack(cols, 1)
    np.savez_compressed(OUT, X=X, en=np.array(en, dtype=object), tr=np.array(tr, dtype=object),
                        fam=np.array(fam), mkt=np.array(mkt, dtype=object))
    return build()


if __name__ == "__main__":
    a = build(refresh=True)
    print(a["X"].shape)
    print(pd.Series(a["fam"]).value_counts().to_string())
