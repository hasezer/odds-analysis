import numpy as np
import pandas as pd

from odds_analysis.export import add_probabilities, price_table


def test_price_table_opening_closing_and_post_match():
    odds = pd.DataFrame([
        # match 1: opened 2.00, moved to 1.80 before kickoff; post-match row must not be used
        dict(event_code="e1", match_id="1", market_id="m", selection_tr="1", odds="2.0", snapshot_utc="2026-10-04T06:00:00Z", snapshot_type="opening", source="popup"),
        dict(event_code="e1", match_id="1", market_id="m", selection_tr="1", odds="1.8", snapshot_utc="2026-10-04T16:00:00Z", snapshot_type="update", source="popup"),
        dict(event_code="e1", match_id="1", market_id="m", selection_tr="1", odds="1.8", snapshot_utc="2026-10-05T05:00:00Z", snapshot_type="post_match", source="popup"),
        # match 2: never snapshotted -> closing from post-match, no opening
        dict(event_code="e2", match_id="2", market_id="m", selection_tr="1", odds="3.1", snapshot_utc="2026-10-05T05:00:00Z", snapshot_type="post_match", source="popup"),
    ])
    snaps = pd.DataFrame([dict(event_code="e1", match_id="1", snapshot_utc="2026-10-04T18:00:00Z")])
    kickoffs = {"1": "2026-10-04T18:45:00Z", "2": "2026-10-04T18:45:00Z"}
    p = price_table(odds, snaps, kickoffs).set_index("event_code")
    assert (p.loc["e1", "opening_odds"], p.loc["e1", "closing_odds"], p.loc["e1", "closing_source"]) == (2.0, 1.8, "snapshot")
    assert p.loc["e1", "closing_utc"] == "2026-10-04T18:00:00Z"  # last fetch before kickoff, price unchanged since 16:00
    assert np.isnan(p.loc["e2", "opening_odds"]) and p.loc["e2", "closing_odds"] == 3.1
    assert p.loc["e2", "closing_source"] == "post_match"


def test_fair_probabilities_remove_margin():
    df = pd.DataFrame({
        "match_id": ["1"] * 5, "market_id": ["a", "a", "a", "b", "b"], "family": ["score"] * 5,
        "market_key": ["1X2"] * 3 + ["DC"] * 2, "opening_odds": [np.nan] * 5,
        "closing_odds": [2.0, 3.5, 4.0, 1.2, np.nan],
    })
    df = add_probabilities(df)
    fair = df.loc[df.market_id == "a", "fair_prob"]
    assert abs(fair.sum() - 1) < 1e-9
    assert abs(df.loc[0, "market_margin"] - (1 / 2 + 1 / 3.5 + 1 / 4 - 1)) < 1e-9
    assert df.loc[df.market_id == "b", "fair_prob"].isna().all()  # incomplete market -> no fair price
