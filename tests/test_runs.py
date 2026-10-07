import httpx
import pandas as pd

from odds_analysis import http as H
from odds_analysis.health import succeeded
from odds_analysis.runs import FailedItems, load_queue, run_status


def test_run_status():
    kw = {"max_failed_share": 0.2}
    assert run_status(calls=100, failed=0, saved=10, due=10, **kw) == "ok"
    assert run_status(calls=100, failed=5, saved=9, due=10, **kw) == "partial"  # a burst of 500/502
    assert run_status(calls=100, failed=20, saved=8, due=10, **kw) == "partial"  # exactly 20 % is not "more than"
    assert run_status(calls=100, failed=21, saved=8, due=10, **kw) == "failed"
    assert run_status(calls=10, failed=0, saved=0, due=3, **kw) == "failed"  # matches were due, none saved
    assert run_status(calls=10, failed=0, saved=0, due=0, **kw) == "ok"  # nothing to do is fine
    assert run_status(calls=10, failed=0, saved=0, due=0, item_errors=1, **kw) == "partial"
    assert run_status(calls=10, failed=0, saved=5, due=5, crashed=True, **kw) == "failed"


def test_failed_items_queue(tmp_path):
    f = FailedItems("snapshot", "2026-10-07T08:07:00Z", root=tmp_path)
    f.add("odds", 3125554, "HTTP 502", match_id=4500001, kickoff_utc="2026-10-07T18:00:00Z")
    f.add("day_list", "2026-10-08", "HTTP 500")
    assert f.finish() == 2
    FailedItems("results", "2026-10-07T08:07:00Z", root=tmp_path).finish()  # other jobs keep their own items
    q = {i["key"]: i for i in load_queue("snapshot", tmp_path)}
    assert set(q) == {"3125554", "2026-10-08"} and q["3125554"]["attempts"] == "1"

    # next run: the popup fails again (attempts 2, first failure kept), the day list worked (dropped)
    f2 = FailedItems("snapshot", "2026-10-07T10:07:00Z", root=tmp_path)
    assert [i["key"] for i in f2.pending("odds")] == ["3125554"]
    f2.add("odds", 3125554, "HTTP 500", match_id=4500001)
    f2.finish()
    q = load_queue("snapshot", tmp_path)
    assert len(q) == 1 and q[0]["attempts"] == "2" and q[0]["first_failed_utc"] == "2026-10-07T08:07:00Z"
    log = pd.read_csv(tmp_path / "failed_items.csv", dtype=str)
    assert list(log["key"]) == ["3125554", "2026-10-08", "3125554"]


def test_partial_runs_count_as_success_for_health():
    runs = pd.DataFrame({"errors": ["0", "3", "1", "2"], "status": ["ok", "partial", "failed", ""]})
    assert list(succeeded(runs)) == [True, True, False, False]
    old = pd.DataFrame({"errors": ["0", "2"]})  # rows logged before the status column existed
    assert list(succeeded(old)) == [True, False]


def _client(responses, monkeypatch):
    sleeps = []
    monkeypatch.setattr(H.time, "sleep", sleeps.append)
    seq = iter(responses)
    c = H.MackolikClient(min_interval_s=0)
    c._client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(next(seq), text="x")))
    return c, sleeps


def test_retries_500_502_with_5_15_45(monkeypatch):
    c, sleeps = _client([502, 500, 200], monkeypatch)
    assert c.get("x").ok
    assert (c.calls, c.failed, c.requests, sleeps) == (1, 0, 3, [5, 15])

    c, sleeps = _client([502, 502, 500, 502], monkeypatch)
    r = c.get("x")
    assert not r.ok and r.error == "HTTP 502" and r.attempts == 4
    assert (c.calls, c.failed, sleeps) == (1, 1, [5, 15, 45])
