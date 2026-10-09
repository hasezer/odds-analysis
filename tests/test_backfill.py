import json
import os
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from odds_analysis.backfill import season_pages
from odds_analysis.budget import daily_usage, job_minutes, used_this_month
from odds_analysis.leagues import leagues

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc


def test_job_minutes_round_up_per_job():
    jobs = [{"started_at": "2026-10-07T10:00:00Z", "completed_at": "2026-10-07T10:00:20Z"},  # 20 s -> 1
            {"started_at": "2026-10-07T10:00:00Z", "completed_at": "2026-10-07T10:02:01Z"},  # 121 s -> 3
            {"started_at": None, "completed_at": None}]  # skipped
    assert job_minutes(jobs) == 4


def test_minutes_ledger_sums():
    led = pd.DataFrame([{"run_id": "1", "workflow": "Snapshot odds", "created_at": "2026-10-06T08:07:00Z", "minutes": "3"},
                        {"run_id": "2", "workflow": "Backfill", "created_at": "2026-10-06T23:17:00Z", "minutes": "100"},
                        {"run_id": "3", "workflow": "Results", "created_at": "2026-10-01T05:04:00Z", "minutes": "20"},
                        {"run_id": "4", "workflow": "Results", "created_at": "2026-09-30T05:04:00Z", "minutes": "20"}])
    now = datetime(2026, 10, 7, 12, tzinfo=UTC)
    assert used_this_month(led, now) == 123  # September's run not counted
    assert daily_usage(led, now, days=7) == round(23 / 7, 1)  # backfill not counted as daily usage


def test_season_pages_newest_first():
    lg = {x["league_id"]: x for x in leagues()}
    tur = season_pages(lg["TUR-1"], 2026)
    assert tur[0][:2] == ("2026-2027", "2026/27") and tur[-1][:2] == ("2019-2020", "2019/20")
    jpn = [(p, s, special) for p, s, _, _, special in season_pages(lg["JPN-1"], 2026)]
    assert jpn[:2] == [("2026", "2026", False), ("2026-2027", "2026/27", False)]
    assert ("2026", "2026", True) in jpn  # J1 100 Year Vision League


SCENARIO = textwrap.dedent('''
    import json
    from datetime import date, datetime, timedelta, timezone
    import pandas as pd
    from odds_analysis import backfill, budget, daily, ingest, store, www

    UTC = timezone.utc
    def ms(d, h=18):
        return int(datetime(d.year, d.month, d.day, h - 3, tzinfo=UTC).timestamp() * 1000)
    D1, D2 = date(2026, 9, 26), date(2026, 9, 27)
    def fixtures(c, slug, cid, page):
        if (slug, page) == ("t%C3%BCrkiye-trendyol-s%C3%BCper-lig", "2026-2027"):
            return [{"match_id": "a", "stage": "Normal Sezon", "kickoff_utc": "2026-09-26T15:00:00Z", "status": "Played"},
                    {"match_id": "b", "stage": "Normal Sezon", "kickoff_utc": "2026-09-27T15:00:00Z", "status": "Played"}]
        return []
    def listing(c, d):
        mk = lambda i, code: {"id": i, "iddaaCode": code, "mstUtc": ms(d), "competitionId": "482ofyysbdbeoxauk19yg7tdt",
                              "stageId": 1, "state": "post", "substate": "fullTime",
                              "homeTeam": {"id": "h", "name": "Göztepe"}, "awayTeam": {"id": "a", "name": "Rizespor"},
                              "score": {"home": "1", "away": "0", "ht": {"home": 0, "away": 0}}}
        return {"competitions": {}, "matches": {"a": mk("a", 11)} if d == D1 else {"b": mk("b", None)} if d == D2 else {}}
    seen_delays = []
    def fetch(c, m, day_lists, np):
        seen_delays.append(getattr(c._local, "quick", False))
        if len(seen_delays) == 1:
            raise RuntimeError("popup HTTP 502")  # first pass: one attempt, no waiting; the second pass succeeds
        return [{"market_name": "Maç Sonucu", "market_type_id": 1, "selection": s, "odds": v, "mbs": 1, "highlight": s == "1"}
                for s, v in (("1", 2.0), ("X", 3.2), ("2", 3.6))], "popup", {"id": 1}
    www.season_fixtures, www.listing, ingest.fetch_outcomes = fixtures, listing, fetch
    www.key_events = lambda c, u: [{"type": "goal", "subType": "goal", "position": "home", "timeMin": "70", "score": "1-0", "periodId": 2}]
    www.stats_page = lambda c, u: "Genel İstatistikler Korner 5 3 Oyuncu İstatistikleri"
    budget.allowance = lambda now=None, running_minutes=0: {"used": 10, "left": 1990, "reserve": 900, "monthly": 2000, "ok": True, "daily_usage_7d": None}
    cfg = {"monthly_minutes": 2000, "daily_reserve": 900, "oldest_date": "2026-09-26", "newest_offset_days": 0, "max_job_minutes": 5, "parallel_requests": 2}
    real_load = backfill.load
    backfill.load = lambda name: cfg if name == "backfill" else real_load(name)
    class FixedDate(date):
        @classmethod
        def today(cls): return date(2026, 9, 27)
    backfill.date = FixedDate
    backfill.README = backfill.DIR.parent / "README.md"
    backfill.README.parent.mkdir(parents=True, exist_ok=True)
    backfill.README.write_text("# x\\n")
    from odds_analysis import http as H
    C = H.MackolikClient  # fetches are all replaced above: no request leaves the test
    from odds_analysis.runs import save_queue
    save_queue("backfill", [{"job": "backfill", "kind": "match", "key": "zz", "match_id": "zz", "match_date": "2026-09-26",
                             "attempts": "5", "last_error": "WrongMatch('no fallback had the match')"}])
    out = {"run": backfill.run(C())}
    from collections import defaultdict
    from odds_analysis.runs import FailedItems
    st = defaultdict(int)
    out["only_other"] = backfill.process_date(C(), D1, {}, FailedItems("t", "x"), st, datetime.now(UTC), {},
                                              only={"zzz"})  # a retry of another match: match "a" is not redone
    out["only_other_stats"] = dict(st)
    out["past_deadline"] = backfill.process_date(C(), D1, {}, FailedItems("t", "x"), defaultdict(int), datetime.now(UTC),
                                                 {}, deadline=0)
    out["seen_delays"] = seen_delays
    out["state"] = json.loads(backfill.STATE.read_text())["next_date"]
    out["matches"] = sorted(store.read("matches")["match_id"])
    out["settled"] = int((store.read("settlements")["status"] == "settled").sum())
    out["progress"] = pd.read_csv(backfill.PROGRESS).to_dict("records")
    out["readme"] = backfill.README.read_text()
    print(json.dumps(out, default=str))
''')


def test_backfill_scenario(tmp_path):
    env = {**os.environ, "ODDS_DATA_DIR": str(tmp_path / "data"), "PYTHONPATH": str(ROOT / "src")}
    r = subprocess.run([sys.executable, "-c", SCENARIO], env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-3000:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["run"]["finished"] and out["run"]["final"] == 1 and out["run"]["no_odds"] == 1
    assert out["run"]["second_pass"] == 1 and out["run"]["deferred"] == 0
    assert out["run"]["abandoned"] == 1  # tried in 5 jobs already: given up, not retried
    assert out["seen_delays"] == [True, False]  # first pass quick (no backoff), second pass with the normal retries
    assert out["state"] == "2026-09-25"  # both dates done, newest first
    assert out["matches"] == ["a", "b"]  # the match without Nesine odds is stored too
    assert out["settled"] == 3
    assert out["only_other"] == ["set()", True] and out["only_other_stats"].get("final", 0) == 0 and "no_odds" not in out["only_other_stats"]
    assert out["past_deadline"][1] is False  # deadline passed: the date is not complete (redone by the next job)
    assert out["progress"] == [{"league_id": "TUR-1", "season": "2026/27", "matches": 2, "done": 2, "pct": 100.0}]
    assert "**2 of 2 matches (100.0 %)**" in out["readme"] and "| 2026/27 | 2 | 2 | 100 % |" in out["readme"]


def test_no_minutes_limit_while_public(monkeypatch):
    from odds_analysis import budget

    led = pd.DataFrame([{"run_id": "1", "workflow": "Backfill", "created_at": "2026-10-07T10:00:00Z", "minutes": "1500"}])
    monkeypatch.setattr(budget, "refresh_ledger", lambda now, root: led)
    now = datetime(2026, 10, 8, 12, tzinfo=UTC)
    monkeypatch.setattr(budget, "repo_is_public", lambda: False)
    assert not budget.allowance(now)["ok"]  # 500 left < 900 reserve
    monkeypatch.setattr(budget, "repo_is_public", lambda: True)
    a = budget.allowance(now)
    assert a["ok"] and a["public"]


def test_visibility_unknown_counts_as_private(monkeypatch):
    from odds_analysis import budget

    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert budget.repo_is_public() is False


def test_visibility_request_url(monkeypatch):
    import httpx

    from odds_analysis import budget

    seen = []

    def handler(request):
        seen.append(str(request.url))
        ok = str(request.url) == "https://api.github.com/repos/o/r"
        return httpx.Response(200 if ok else 400, json={"private": False} if ok else {})

    monkeypatch.setenv("GH_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    real = budget._client
    monkeypatch.setattr(budget, "_client", lambda: httpx.Client(base_url=real().base_url, transport=httpx.MockTransport(handler)))
    assert budget.repo_is_public() is True
    assert seen == ["https://api.github.com/repos/o/r"]
