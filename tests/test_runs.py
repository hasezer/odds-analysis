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


def test_not_tried_keeps_attempts_and_abandon_logs(tmp_path):
    f = FailedItems("backfill", "r1", root=tmp_path)
    f.add("match", "m1", "statistics page failed", match_id="m1", match_date="2025-04-01")
    f.finish()
    f2 = FailedItems("backfill", "r2", root=tmp_path)
    f2.add("match", "m1", "retry not reached yet", tried=False, match_id="m1", match_date="2025-04-01")
    f2.finish()
    q = load_queue("backfill", tmp_path)
    assert q[0]["attempts"] == "1" and q[0]["last_error"] == "statistics page failed"
    f3 = FailedItems("backfill", "r3", root=tmp_path)
    f3.abandon(f3.pending("match"), "given up after 5 attempts")
    f3.finish()  # not re-added: leaves the queue
    assert load_queue("backfill", tmp_path) == []
    log = pd.read_csv(tmp_path / "failed_items.csv", dtype=str)
    assert log.iloc[-1]["kind"] == "abandoned_match" and "statistics page failed" in log.iloc[-1]["error"]


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


def test_client_starts_at_most_one_request_per_interval_across_threads():
    import time
    from concurrent.futures import ThreadPoolExecutor

    from odds_analysis import http as H

    starts = []

    class Slow:
        def get(self, url, **kw):
            starts.append(time.monotonic())
            time.sleep(0.15)  # slow answers: several requests are in flight at once
            return type("R", (), {"status_code": 502 if "bad" in url else 200, "text": "x"})()

    c = H.MackolikClient(min_interval_s=0.05)
    c._client = Slow()
    t0 = time.monotonic()
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda i: c.get(f"https://x/{i}"), range(12)))
    # a thread can record its start late (scheduling), never early: the k-th start is at least k intervals after t0
    assert len(starts) == 12
    assert all(s - t0 >= k * 0.05 - 0.005 for k, s in enumerate(sorted(starts)))
    assert max(starts) - min(starts) < 12 * 0.15  # overlapping: faster than one at a time
    with c.quick():
        assert not c.get("https://x/bad").ok  # one attempt, no backoff sleep
    assert (c.calls, c.requests, c.failed, c.soft_failed) == (13, 13, 0, 1)
