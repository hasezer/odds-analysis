"""Snapshot job: upcoming matches (A, np=1, per date) + all Nesine markets (B) -> data/matches, data/odds.

Odds rows are stored only when a selection's price changes, so files stay small:
  opening = first stored row of a selection, closing = last row before kickoff.
data/snapshots records every successful B fetch (so "unchanged since" is known).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from . import http as H
from .config import TR, iso, load, now_utc
from .parsers import parse_day_list, parse_morebets, parse_odds_popup, popup_matches
from .rows import log_unmapped, match_row, odds_rows
from .runs import FailedItems
from .storage import frame, read_partition, upsert_partition

log = logging.getLogger(__name__)
RUN_HOURS_UTC = [6, 8, 10, 12, 14, 16, 18, 20, 22]  # keep in sync with .github/workflows/snapshot.yml
MAX_FAILURES_IN_A_ROW = 10  # then the remaining popups are queued for the next run


def next_run_after(now: datetime, hours: list[int] = RUN_HOURS_UTC) -> datetime:
    for day in (0, 1):
        for h in sorted(hours):
            t = (now + timedelta(days=day)).replace(hour=h, minute=0, second=0, microsecond=0)
            if t > now + timedelta(minutes=30):  # a late-starting cron run still counts as "this" run
                return t
    return now + timedelta(hours=24)


def select_for_fetch(rows: list[dict], known_events: set[str], now: datetime, cfg: dict) -> list[tuple[dict, str]]:
    """Decide which upcoming matches get a B popup fetch in this run, and why."""
    horizon_closing = next_run_after(now) + timedelta(minutes=cfg.get("buffer_minutes", 20))
    horizon_extra = now + timedelta(hours=cfg.get("resnapshot_horizon_hours", 0) or 0)
    out = []
    for r in rows:
        ko = datetime.fromisoformat(r["kickoff_utc"].replace("Z", "+00:00"))
        if ko <= now or not r["event_code"]:
            continue
        if r["event_code"] not in known_events:
            out.append((r, "opening"))
        elif ko <= horizon_closing:
            out.append((r, "closing_candidate"))
        elif ko <= horizon_extra:
            out.append((r, "resnapshot"))
    return out


def changed_rows(new: list[dict], existing) -> list[dict]:
    """Keep only selections whose odds differ from the latest stored pre-match value."""
    last: dict[tuple, str] = {}
    if existing is not None and not existing.empty:
        pre = existing[existing["snapshot_type"] != "post_match"] if "snapshot_type" in existing else existing
        for t in pre.sort_values("snapshot_utc").itertuples(index=False):
            last[(t.event_code, t.market_id, t.selection_tr)] = t.odds
    out = []
    for r in new:
        key = (str(r["event_code"]), str(r["market_id"]), str(r["selection_tr"]))
        val = "" if r["odds"] is None else str(r["odds"])
        if key not in last:
            out.append({**r, "snapshot_type": "opening"})
        elif last[key] != val:
            out.append({**r, "snapshot_type": "update"})
    return out


def fetch_odds(client: H.MackolikClient, m: dict, raw_prefix: str) -> tuple[dict, str]:
    """Odds popup (B) if it really is this match, else the program's morebets data for the match id."""
    res = client.get(H.odds_popup_path(m["event_code"]), save_as=f"{raw_prefix}/B_{m['event_code']}.json.gz")
    if not res.ok:
        raise RuntimeError(f"popup {res.error}")
    pop = parse_odds_popup(res.text)
    if pop["match"] and popup_matches(pop, m["event_code"], m["kickoff_utc"]):
        return pop, "popup"
    log.info("popup for %s resolved to another match (%s) - using morebets", m["event_code"],
             pop["match"] and pop["match"].get("iddaa_code"))
    res = client.get(H.morebets_path(m["match_id"]), save_as=f"{raw_prefix}/MB_{m['match_id']}.json.gz")
    if not res.ok:
        raise RuntimeError(f"morebets {res.error}")
    mb = parse_morebets(res.text)
    if mb["match"]["iddaa_code"] not in (None, str(m["event_code"])):
        raise RuntimeError(f"morebets event {mb['match']['iddaa_code']} != {m['event_code']}")
    return mb, "morebets"


def add_retries(todo: list[tuple[dict, str]], pending: list[dict], listed: list[dict], now: datetime) -> int:
    """Popups that failed in an earlier run are fetched again (if the match is still listed and not started)."""
    have = {str(m["event_code"]) for m, _ in todo}
    by_code = {str(m["event_code"]): m for m in listed if m["event_code"]}
    added = 0
    for item in pending:
        m = by_code.get(str(item["key"]))
        if m is None or str(item["key"]) in have:
            continue
        if datetime.fromisoformat(m["kickoff_utc"].replace("Z", "+00:00")) <= now:
            continue
        todo.append((m, "retry"))
        have.add(str(item["key"]))
        added += 1
    return added


def run(client: H.MackolikClient, *, raw_prefix: str = "snapshot") -> dict:
    cfg = load("pipeline")["snapshot"]
    now = now_utc()
    snap = iso(now)
    today = now.astimezone(TR).date()
    stats = {"dates": [], "matches_listed": 0, "fetched": 0, "odds_rows": 0, "errors": 0, "error_detail": []}
    failures = FailedItems("snapshot", snap)

    rows: dict[int, dict] = {}
    days = [today + timedelta(days=o) for o in range(cfg.get("days_ahead", 10) + 1)]
    for attempt in (1, 2):  # failed dates get one more round at the end
        failed = []
        for day in days:
            res = client.get(H.day_list_path(day.strftime("%d.%m.%Y"), np=1), save_as=f"{raw_prefix}/A_np1_{day}.html.gz",
                             backoff=H.LIST_BACKOFF_SECONDS)
            if not res.ok:
                failed.append((day, res.error))
                continue
            for r in parse_day_list(res.text):
                rows.setdefault(r["mackolik_match_id"], r)
            stats["dates"].append(day.isoformat())
        days = [d for d, _ in failed]
        if not days:
            break
    for day, err in failed:  # the next run requests every date again
        failures.add("day_list", day.isoformat(), err, match_date=day.isoformat())
        stats["error_detail"].append(f"A {day}: {err}")
    match_rows = [match_row(r, snap) for r in rows.values() if r["date"]]
    stats["matches_listed"] = len(match_rows)

    by_date: dict[str, list[dict]] = {}
    for m in match_rows:
        by_date.setdefault(m["date"], []).append(m)
    for date, ms in by_date.items():  # keep first_seen_utc of existing rows
        old = read_partition("matches", date)
        if not old.empty:
            first = dict(zip(old["match_id"], old["first_seen_utc"]))
            for m in ms:
                m["first_seen_utc"] = first.get(str(m["match_id"]), m["first_seen_utc"])
        upsert_partition("matches", date, frame(ms))

    known: set[str] = set()
    existing_odds = {}
    for date in by_date:
        df = read_partition("odds", date)
        existing_odds[date] = df
        if not df.empty:
            known |= set(df["event_code"])

    todo = select_for_fetch(match_rows, known, now, cfg)
    stats["retried"] = add_retries(todo, failures.pending("odds"), match_rows, now)
    log.info("listed %d matches, fetching %d popups", len(match_rows), len(todo))
    unmapped: dict[str, dict] = {}
    new_odds: dict[str, list[dict]] = {}
    snaps: dict[str, list[dict]] = {}
    in_a_row = 0
    for m, reason in todo:
        if in_a_row >= MAX_FAILURES_IN_A_ROW:  # Mackolik is down: don't spend the job's time limit on retries
            failures.add("odds", m["event_code"], "not tried: Mackolik unreachable", match_id=m["match_id"],
                         match_date=m["date"], kickoff_utc=m["kickoff_utc"])
            stats["not_tried"] = stats.get("not_tried", 0) + 1
            continue
        try:
            pop, source = fetch_odds(client, m, raw_prefix)
        except Exception as exc:  # noqa: BLE001 - logged and fetched again by the next run
            in_a_row += 1
            stats["deferred"] = stats.get("deferred", 0) + 1
            failures.add("odds", m["event_code"], repr(exc), match_id=m["match_id"], match_date=m["date"],
                         kickoff_utc=m["kickoff_utc"])
            if len(stats["error_detail"]) < 20:
                stats["error_detail"].append(f"odds {m['event_code']}: {exc}")
            continue
        in_a_row = 0
        stats["fetched"] += 1
        stats["morebets_fallback"] = stats.get("morebets_fallback", 0) + (source == "morebets")
        rows_ = [{**r, "source": source} for r in odds_rows(
            pop, event_code=m["event_code"], match_id=m["match_id"], snapshot_utc=snap,
            home=m["home_team"], away=m["away_team"], unmapped=unmapped)]
        new_odds.setdefault(m["date"], []).extend(rows_)
        snaps.setdefault(m["date"], []).append({
            "snapshot_utc": snap, "event_code": m["event_code"], "match_id": m["match_id"], "reason": reason,
            "kickoff_utc": m["kickoff_utc"], "status": pop["match"] and pop["match"]["status"], "source": source,
            "selections": len(rows_), "with_odds": sum(r["odds"] is not None for r in rows_)})

    for date, rows_ in new_odds.items():
        changed = changed_rows(rows_, existing_odds.get(date))
        stats["odds_rows"] += len(changed)
        upsert_partition("odds", date, frame(changed))
    for date, s in snaps.items():
        upsert_partition("snapshots", date, frame(s))
    stats["unmapped_new"] = log_unmapped(unmapped)
    stats["failed_items"] = failures.finish()
    # "saved nothing": no match could be listed, or popups were due and none was saved
    stats["due"] = len(todo) if match_rows else 1
    stats["saved"] = stats["fetched"] if match_rows else 0
    return stats
