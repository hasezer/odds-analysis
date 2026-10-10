import json
import os
import subprocess
import sys
import textwrap
from datetime import date, datetime, timezone
from pathlib import Path

from odds_analysis.daily import _typed, next_run_after
from odds_analysis.leagues import competitions, season_for

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]


def test_next_run_after():
    assert next_run_after(datetime(2026, 10, 6, 10, 5, tzinfo=UTC)) == datetime(2026, 10, 6, 12, tzinfo=UTC)
    assert next_run_after(datetime(2026, 10, 6, 22, 10, tzinfo=UTC)) == datetime(2026, 10, 7, 6, tzinfo=UTC)


def test_season_labels_per_league():
    comps = {c.league["league_id"]: c for c in competitions().values() if not c.special}
    assert season_for(comps["TUR-1"], date(2026, 10, 7)) == "2026/27"
    assert season_for(comps["TUR-1"], date(2026, 5, 20)) == "2025/26"
    assert season_for(comps["NOR-1"], date(2026, 10, 7)) == "2026"
    assert season_for(comps["JPN-1"], date(2025, 10, 7)) == "2025"  # calendar year before the switch
    assert season_for(comps["JPN-1"], date(2026, 10, 7)) == "2026/27"  # autumn-spring from August 2026
    vision = next(c for c in competitions().values() if c.special)
    assert (vision.league["league_id"], season_for(vision, date(2026, 4, 4))) == ("JPN-1", "2026")


def test_typed_only_stores_changes():
    row = {"match_id": "m", "market_type_id": "1", "line": None, "handicap_home": None, "handicap_away": None,
           "selection_key": "1", "odds": 2.1, "price_type": "opening_snapshot"}
    key = ("m", "1", None, None, None, "1")
    assert _typed(row, {})["price_type"] == "opening_snapshot"  # new selection
    assert _typed(row, {key: {"odds": 2.1}}) is None  # unchanged
    assert _typed(row, {key: {"odds": 2.2}})["price_type"] == "intraday_snapshot"


SCENARIO = textwrap.dedent('''
    import json
    from datetime import datetime, timedelta, timezone
    from odds_analysis import daily, flat, ingest, store, www
    from odds_analysis.parsers import parse_odds_popup

    UTC = timezone.utc
    NOW = datetime(2026, 10, 7, 10, 0, tzinfo=UTC)
    ko = NOW + timedelta(days=2)
    MATCH = {"id": "u1", "iddaaCode": 555, "mstUtc": int(ko.timestamp() * 1000),
             "competitionId": "482ofyysbdbeoxauk19yg7tdt", "stageId": 1, "state": "pre", "substate": None,
             "homeTeam": {"id": "h", "name": "Fenerbahçe"}, "awayTeam": {"id": "a", "name": "Beşiktaş"},
             "score": {}}
    def listing(c, d):
        return {"competitions": {}, "matches": {"u1": MATCH} if d == ko.date() else {}}
    def outcomes(o1, ou_over, hl=None):
        hl = hl or set()
        base = [("Maç Sonucu", 1, k, v) for k, v in (("1", o1), ("X", 3.4), ("2", 3.0))]
        base += [("2,5 Alt/Üst", 12, k, v) for k, v in (("Alt", 1.9), ("Üst", ou_over))]
        base += [("Oyuncu Gol Atar", 701, "Biri", 3.0), ("4,5 Kart Puanı Alt/Üst", 301, "Üst", 1.8)]
        return [{"market_name": n, "market_type_id": t, "selection": s, "odds": v, "mbs": 1,
                 "highlight": (n, s) in hl} for n, t, s, v in base]
    state = {"o1": 2.0, "over": 1.8, "hl": set()}
    def fetch(c, m, day_lists, np):
        return outcomes(state["o1"], state["over"], state["hl"]), "popup", {"id": 4500001}
    www.listing = listing
    ingest.fetch_outcomes = fetch
    class C: pass
    out = {}
    daily.now_utc = lambda: NOW
    out["run1"] = daily.snapshot_run(C(), full=True)              # opening
    daily.now_utc = lambda: NOW + timedelta(hours=2)
    state["o1"] = 2.1
    out["run2"] = daily.snapshot_run(C(), full=True)              # nothing due (not closing yet, already opened)
    daily.now_utc = lambda: ko - timedelta(hours=1)
    out["run3"] = daily.snapshot_run(C(), full=True)              # closing: full copy
    state["over"] = 1.75
    daily.now_utc = lambda: ko - timedelta(minutes=30)
    out["run4"] = daily.snapshot_run(C(), full=True)              # later closing: earlier one becomes intraday
    o = store.read("odds")
    out["price_types"] = sorted(o.groupby("price_type").size().items())
    out["markets"] = sorted(set(o["market_key"]))
    # results: finished 2-1, Nesine marks 1 and Üst
    MATCH.update({"state": "post", "substate": "fullTime", "score": {"home": "2", "away": "1", "ht": {"home": 1, "away": 0}}})
    state["hl"] = {("Maç Sonucu", "1"), ("2,5 Alt/Üst", "Üst")}
    key_event_calls = []
    www.key_events = lambda c, u: key_event_calls.append(u) or [
        {"type": "goal", "subType": "goal", "position": "home", "timeMin": "10", "score": "1-0", "playerName": "A", "periodId": 1},
        {"type": "goal", "subType": "goal", "position": "away", "timeMin": "50", "score": "1-1", "playerName": "B", "periodId": 2},
        {"type": "goal", "subType": "goal", "position": "home", "timeMin": "80", "score": "2-1", "playerName": "C", "periodId": 2}]
    www.stats_page = lambda c, u: "<b>Genel İstatistikler</b> Korner 6 4 Sarı Kart 2 1 <b>Oyuncu İstatistikleri</b> Stat: X Arena ("
    daily.now_utc = lambda: ko + timedelta(hours=4)
    daily.load = lambda name: {"results": {"days_back": 3, "min_minutes_after_kickoff": 150, "max_minutes": 10},
                               "settlement": {}, "snapshot": {}}
    out["results"] = daily.results_run(C())
    s = store.read("settlements")
    out["settled"] = sorted((r.market_type_id, r.selection_key, bool(r.hit), r.status) for r in s.itertuples())
    m = store.read("matches").iloc[0]
    out["match"] = [m.status, int(m.ft_home), int(m.ft_away), m.stadium, m.arsiv_match_id]
    view, hits = flat.match_view(store.read("analysis_flat"))
    out["view"] = view[["Ev Sahibi", "MS", "MS 1", "2,5 Üst"]].astype(str).values.tolist()
    out["quality_fail"] = out["results"]["quality"]["fail"]
    out["key_event_calls"] = key_event_calls
    out["cards"] = sorted(store.read("stats")["yellow_cards"].tolist())
    print(json.dumps(out, default=str))
''')


def test_daily_scenario(tmp_path):
    env = {**os.environ, "ODDS_DATA_DIR": str(tmp_path / "data"), "PYTHONPATH": str(ROOT / "src")}
    r = subprocess.run([sys.executable, "-c", SCENARIO], env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-3000:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["run1"]["fetched"] == 1 and out["run2"]["fetched"] == 0
    assert out["run3"]["fetched"] == 1 and out["run4"]["fetched"] == 1
    # opening 5 selections, closing copy 5 (run 4), earlier closing copy relabelled intraday (5);
    # run 2 fetched nothing so the 2.0 -> 2.1 move is only seen by the closing run
    assert dict(out["price_types"]) == {"closing_snapshot": 5, "intraday_snapshot": 5, "opening_snapshot": 5}
    assert out["markets"] == ["1X2", "OU"]  # player and card markets dropped
    assert ["1", "1", True, "settled"] in out["settled"] and ["12", "OVER", True, "settled"] in out["settled"]
    assert out["match"] == ["finished", 2, 1, "X Arena", "4500001"]
    assert out["view"] == [["Fenerbahçe", "2-1", "2.1", "1.75"]]  # closing snapshot prices
    assert out["quality_fail"] == 0
    assert out["key_event_calls"] == []  # no extra time: the key events are not fetched
    assert out["cards"] == [1, 2]


def test_key_events_only_for_extra_time():
    from odds_analysis.ingest import went_to_extra_time

    assert not went_to_extra_time({"_substate": "fullTime"})
    assert went_to_extra_time({"_substate": "afterExtraTime"}) and went_to_extra_time({"_substate": "afterPenalties"})


def test_wrong_popup_falls_back_to_morebets_of_previous_day(monkeypatch):
    """A 01:15 match is filed under the previous day in the arsiv list."""
    from odds_analysis import http as H
    from odds_analysis import ingest, parsers

    calls = []

    class Client:
        def get(self, path, **kw):
            calls.append(path)
            if "oddspopup" in path:
                return H.FetchResult(path, 200, json.dumps({"data": {"matches": [{"uuid": "OLD"}]}}), 0, 1)
            return H.FetchResult(path, 200, path, 0, 1)

    monkeypatch.setattr(parsers, "parse_day_list",
                        lambda text: [{"event_code": "3180648", "mackolik_match_id": 4475858}] if "d=02.10.2026" in text else [])
    monkeypatch.setattr(parsers, "parse_morebets",
                        lambda text: {"match": {"iddaa_code": "3180648"}, "outcomes": [{"market_name": "Maç Sonucu"}]})
    match = {"match_id": "u1", "iddaa_event_code": "3180648", "kickoff_local_tr": "2026-10-03T01:15:00+03:00"}
    outcomes, source, meta = ingest.fetch_outcomes(Client(), match, {}, np=0)
    assert (source, meta["id"], len(outcomes)) == ("morebets", 4475858, 1)
    assert any("d=03.10.2026" in p for p in calls) and any("d=02.10.2026" in p for p in calls)
    assert calls[-1].endswith("mac=4475858&type=ByDate")


def test_past_date_falls_back_to_new_site_markets(monkeypatch):
    """Past dates are no longer in the arsiv lists: the new site's markets (keyed by match uuid) are used."""
    from odds_analysis import http as H
    from odds_analysis import ingest, parsers, www

    class Client:
        def get(self, path, **kw):
            if "oddspopup" in path:
                return H.FetchResult(path, 200, json.dumps({"data": {"matches": [{"uuid": "OLD"}]}}), 0, 1)
            return H.FetchResult(path, 200, "", 0, 1)

    monkeypatch.setattr(parsers, "parse_day_list", lambda text: [])
    monkeypatch.setattr(www, "market_outcomes", lambda c, uuid: [{"market_name": "Maç Sonucu", "market_type_id": "1",
                                                                  "selection": "1", "odds": 2.0, "mbs": 1, "highlight": False}])
    match = {"match_id": "u1", "iddaa_event_code": "777", "kickoff_local_tr": "2023-03-04T19:00:00+03:00",
             "kickoff_utc": datetime(2023, 3, 4, 16, tzinfo=UTC)}
    outcomes, source, meta = ingest.fetch_outcomes(Client(), match, {}, np=0)
    rows, _ = ingest.odds_rows_from(match, outcomes, price_type="closing_history", source=source)
    assert (source, meta, rows[0]["source"], rows[0]["selection_key"]) == ("new", {}, "new", "1")


def test_finished_match_kept_without_statistics(monkeypatch):
    """Backfill second pass: a statistics page that keeps failing no longer drops the match's odds."""
    import pytest

    from odds_analysis import daily, ingest, www

    m = {"match_id": "u1", "status": "finished", "season": "2024/25", "league_id": "TUR-1", "iddaa_event_code": "1",
         "ft_home": 1, "ft_away": 0, "ht_home": 0, "ht_away": 0, "_substate": "fullTime"}
    monkeypatch.setattr(www, "stats_page", lambda c, u: None)
    monkeypatch.setattr(ingest, "fetch_outcomes", lambda c, m, d, np: (
        [{"market_name": "Maç Sonucu", "market_type_id": 1, "selection": "1", "odds": 2.0, "mbs": 1, "highlight": True}],
        "popup", {}))
    with pytest.raises(RuntimeError, match="statistics page failed"):
        daily.collect_finished(None, dict(m), {}, datetime(2026, 10, 10, tzinfo=UTC), set())
    rows = daily.collect_finished(None, dict(m), {}, datetime(2026, 10, 10, tzinfo=UTC), set(), allow_missing_stats=True)
    assert rows["stats"] == [] and len(rows["odds"]) == 1 and rows["settlements"][0]["hit"] is True
