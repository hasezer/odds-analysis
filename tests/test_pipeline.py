from datetime import datetime, timezone

import pandas as pd

from odds_analysis import storage
from odds_analysis.results import classify_status, corners, events_complete
from odds_analysis.snapshot import changed_rows, next_run_after, select_for_fetch

UTC = timezone.utc


def test_next_run_after():
    assert next_run_after(datetime(2026, 10, 6, 10, 5, tzinfo=UTC)) == datetime(2026, 10, 6, 12, tzinfo=UTC)
    # a 22:00 run that starts late still schedules the next morning
    assert next_run_after(datetime(2026, 10, 6, 22, 10, tzinfo=UTC)) == datetime(2026, 10, 7, 6, tzinfo=UTC)


def test_select_for_fetch():
    now = datetime(2026, 10, 6, 10, 0, tzinfo=UTC)
    rows = [
        {"event_code": "1", "kickoff_utc": "2026-10-06T09:00:00Z"},  # started
        {"event_code": "2", "kickoff_utc": "2026-10-08T18:00:00Z"},  # new -> opening
        {"event_code": "3", "kickoff_utc": "2026-10-06T12:10:00Z"},  # known, before next run+buffer -> closing
        {"event_code": "4", "kickoff_utc": "2026-10-06T18:00:00Z"},  # known, later -> skip
    ]
    got = {r["event_code"]: why for r, why in select_for_fetch(rows, {"3", "4"}, now, {"buffer_minutes": 20})}
    assert got == {"2": "opening", "3": "closing_candidate"}


def test_changed_rows_only_stores_moves():
    existing = pd.DataFrame([
        {"event_code": "9", "market_id": "1", "selection_tr": "1", "odds": "2.1", "snapshot_utc": "a", "snapshot_type": "opening"},
        {"event_code": "9", "market_id": "1", "selection_tr": "X", "odds": "3.2", "snapshot_utc": "a", "snapshot_type": "opening"},
    ])
    new = [
        {"event_code": "9", "market_id": "1", "selection_tr": "1", "odds": 2.1},
        {"event_code": "9", "market_id": "1", "selection_tr": "X", "odds": 3.0},
        {"event_code": "9", "market_id": "1", "selection_tr": "2", "odds": None},
    ]
    out = changed_rows(new, existing)
    assert [(r["selection_tr"], r["snapshot_type"]) for r in out] == [("X", "update"), ("2", "opening")]


def test_upsert_is_idempotent(tmp_path):
    rows = storage.frame([{"match_id": 1, "status": "MS", "ft_home": 2}, {"match_id": 2, "status": "Ert.", "ft_home": None}])
    storage.upsert_partition("results", "2026-10-04", rows, root=tmp_path)
    path = storage.partition_path("results", "2026-10-04", tmp_path)
    first = path.read_bytes()
    storage.upsert_partition("results", "2026-10-04", rows, root=tmp_path)
    assert path.read_bytes() == first
    storage.upsert_partition("results", "2026-10-04", storage.frame([{"match_id": 2, "status": "MS", "ft_home": 1}]), root=tmp_path)
    df = storage.read_partition("results", "2026-10-04", tmp_path)
    assert df.set_index("match_id").loc["2", "status"] == "MS"
    assert df.set_index("match_id").loc["1", "ft_home"] == "2"


def test_status_classification():
    assert classify_status("MS") == "final"
    assert classify_status("Ert.") == "void"
    assert classify_status("IY") == "pending"
    assert classify_status("67") == "pending"


def test_corners_prefers_opta():
    assert corners({"opta": {"Korner": ("6", "4")}, "rb": {"Köşe Vuruşu": ("5", "4")}}) == (6, 4, "opta")
    assert corners({"opta": {}, "rb": {"Köşe Vuruşu": ("5", "4")}}) == (5, 4, "rb")
    assert corners({}) == (None, None, None)


def test_events_complete_detects_disallowed_goal():
    # Yunanistan-Almanya 04.10.2026: MS 0-0 but the feed still lists a 32' goal
    md = {"et": None, "events": [{"type": "goal", "team": "away", "minute": 32}]}
    assert not events_complete(md, (0, 0))
    assert events_complete(md, (0, 1))
