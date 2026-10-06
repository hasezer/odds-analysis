import math

import numpy as np
import pandas as pd

from odds_analysis.analysis import band_of, bh, pb_test, segment_stats, wilson


def test_wilson_known_value():
    lo, hi = wilson(50, 100)
    assert abs(lo - 0.4038) < 1e-3 and abs(hi - 0.5962) < 1e-3
    assert all(np.isnan(wilson(0, 0)))


def test_pb_test_equals_binomial_z_for_equal_probs():
    z, p = pb_test(60, np.full(100, 0.5))
    assert abs(z - 2.0) < 1e-9
    assert abs(p - math.erfc(2 / math.sqrt(2))) < 1e-12


def test_benjamini_hochberg():
    q = bh(pd.Series([0.01, 0.04, 0.03, 0.20, np.nan]))
    assert np.allclose(q[:4], [0.04, 0.0533333, 0.0533333, 0.20])
    assert np.isnan(q[4])


def test_odds_bands():
    assert band_of(1.01) == "1.01-1.20" and band_of(1.2) == "1.01-1.20" and band_of(1.21) == "1.21-1.40"
    assert band_of(5.0) == "4.01-5.00" and band_of(5.5) == "5.00+"


def test_beats_price_needs_more_hits_and_positive_roi():
    rng = np.random.default_rng(1)
    n = 2000
    # priced at 2.0 (implied 50%) but wins 60%: should beat the price
    good = pd.DataFrame({"seg": "good", "hit": (rng.random(n) < 0.6).astype(int), "implied": 0.5, "price": 2.0, "fair_prob": 0.45})
    # priced at 2.0 but wins 40%: significant, but the wrong way
    bad = pd.DataFrame({"seg": "bad", "hit": (rng.random(n) < 0.4).astype(int), "implied": 0.5, "price": 2.0, "fair_prob": 0.45})
    d = pd.concat([good, bad], ignore_index=True)
    d["profit"] = np.where(d["hit"] == 1, d["price"] - 1, -1.0)
    s = segment_stats(d, ["seg"]).set_index("segment")
    assert bool(s.loc["good", "beats_price"]) and not bool(s.loc["bad", "beats_price"])
    assert s.loc["good", "bias_vs_fair"] == "underpriced" and s.loc["bad", "bias_vs_fair"] == "overpriced"
