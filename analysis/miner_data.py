"""Wide match x selection matrices for the pattern miner and the whole-book models (cached).

cache/miner.npz holds, for the S most common selection types (market|line|selection):
  O  N x S  closing odds (NaN = not offered)
  F  N x S  fair probability (cut removed within its market; NaN if incomplete)
  Hm N x S  1 = won, 0 = lost, NaN = not offered / not settled
  per        N    period A (2024/25 + 2024), B (2025/26 + 2025), C (2026/27 + 2026)
  names      S    selection labels, match_ids N
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ml_data as md  # noqa: E402
from htft_data import CACHE  # noqa: E402

MIN_COVER = 0.25


def label(mk, line, sk):
    return f"{mk}|{'' if pd.isna(line) else f'{line:g}'}|{sk}"


def build(refresh=False):
    out = CACHE / "miner.npz"
    if out.exists() and not refresh:
        z = np.load(out, allow_pickle=True)
        return {k: z[k] for k in z.files}
    mt, sel = md.build()
    mt = mt.sort_values("kickoff_utc").reset_index(drop=True)
    sel = sel[sel["match_id"].isin(mt["match_id"])].copy()
    # data error: in Oct-Nov 2025 the four HT_2H_BTTS prices of 211 matches are stored under the wrong labels
    # (NO/NO priced above YES/YES); drop that market for those matches
    hb = sel[sel["market_key"] == "HT_2H_BTTS"].pivot_table(index="match_id", columns="selection_key",
                                                              values="closing_odds")
    swapped = hb.index[hb["NO/NO"] > hb["YES/YES"]]
    sel = sel[~((sel["market_key"] == "HT_2H_BTTS") & sel["match_id"].isin(swapped))]
    sel["lab"] = [label(a, b, c) for a, b, c in zip(sel["market_key"], sel["line"], sel["selection_key"])]
    cover = sel.groupby("lab")["match_id"].nunique() / len(mt)
    keep = cover[cover >= MIN_COVER].index
    sel = sel[sel["lab"].isin(keep)].drop_duplicates(["match_id", "lab"])
    names = np.array(sorted(keep))
    idx = pd.Index(mt["match_id"])
    piv = lambda v: sel.pivot(index="match_id", columns="lab", values=v).reindex(index=idx, columns=names)
    O = piv("closing_odds").to_numpy(np.float32)
    F = piv("fair").to_numpy(np.float32)
    Hm = piv("hit").astype(float).to_numpy(np.float32)
    per = np.where(mt["season"].isin(["2024/25", "2024"]), "A",
                   np.where(mt["season"].isin(["2025/26", "2025"]), "B", "C"))
    np.savez_compressed(out, O=O, F=F, Hm=Hm, per=per, names=names, match_ids=mt["match_id"].to_numpy(),
                        league=mt["league_id"].to_numpy(), kick=mt["kickoff_utc"].astype("int64").to_numpy())
    return build()


if __name__ == "__main__":
    z = build(refresh=True)
    print(z["O"].shape, pd.Series(z["per"]).value_counts().to_dict())
    print(pd.Series([n.split("|")[0] for n in z["names"]]).value_counts().to_string())
