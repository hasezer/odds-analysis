"""Daily jobs on the SCHEMA.md tables: the 26 leagues of config/leagues.yaml, the 45 markets of config/markets.yaml.

snapshot (06:07, then every 2 h): www.mackolik.com date listing -> matches; the arsiv odds popup (uuid-checked,
    `morebets` fallback) -> odds: the first time a match is seen (opening_snapshot), price changes in later runs
    (intraday_snapshot) and, in the last run before kickoff, every selection (closing_snapshot).
results (05:04): finished matches of the last days -> scores, key events, statistics page, Nesine's final odds with
    winner marks (closing_history), settlements; then analysis_flat and the quality checks.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from . import flat, ingest, quality, store, www
from . import http as H
from .config import TR, load
from .leagues import competitions, season_for
from .runs import FailedItems

log = logging.getLogger(__name__)
UTC = timezone.utc
RUN_HOURS_UTC = [6, 8, 10, 12, 14, 16, 18, 20, 22]  # keep in sync with .github/workflows/snapshot.yml
MAX_FAILURES_IN_A_ROW = 10  # then the remaining popups are queued for the next run
SNAPSHOT_TYPES = ("opening_snapshot", "intraday_snapshot", "closing_snapshot")
SELECTION = ["market_type_id", "line", "handicap_home", "handicap_away", "selection_key"]


def now_utc() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def next_run_after(now: datetime, hours: list[int] = RUN_HOURS_UTC) -> datetime:
    for day in (0, 1):
        for h in sorted(hours):
            t = (now + timedelta(days=day)).replace(hour=h, minute=0, second=0, microsecond=0)
            if t > now + timedelta(minutes=30):  # a late-starting cron run still counts as "this" run
                return t
    return now + timedelta(hours=24)


# ---------------------------------------------------------------- listing -> matches

def list_matches(c: H.MackolikClient, days: list[date], failures: FailedItems, stats: dict) -> list[dict]:
    """Matches of the 26 leagues on these Turkish dates (one www.mackolik.com listing per date)."""
    out: dict[str, dict] = {}
    for d in days:
        data = www.listing(c, d)
        if data is None:
            failures.add("listing", d.isoformat(), "date listing failed", match_date=d.isoformat())
            stats["error_detail"].append(f"listing {d}: failed")
            continue
        stats["dates"].append(d.isoformat())
        comps = data.get("competitions") or {}
        for m in (data.get("matches") or {}).values():
            comp = competitions().get(m.get("competitionId"))
            if comp is None:
                continue
            ko = datetime.fromtimestamp(m["mstUtc"] / 1000, tz=UTC)
            stage = (((comps.get(m["competitionId"]) or {}).get("stage") or {}).get(str(m.get("stageId"))) or {}).get("name")
            out[m["id"]] = ingest.match_row(m, league_id=comp.league["league_id"], season=season_for(comp, ko.astimezone(TR).date()),
                                            stage=stage, special=comp.special)
    return list(out.values())


def _partitions(rows: list[dict]) -> set[tuple[str, str]]:
    return {(r["season"], r["league_id"]) for r in rows}


def save_matches(rows: list[dict]) -> None:
    """Upsert match rows without losing what other jobs stored (stadium, referee, extra time, arsiv id)."""
    for season, lid in _partitions(rows):
        old = store.read("matches", season=season, league_id=lid)
        prev = old.set_index("match_id").to_dict("index") if not old.empty else {}
        merged = []
        for r in (x for x in rows if (x["season"], x["league_id"]) == (season, lid)):
            p = prev.get(r["match_id"], {})
            merged.append({**{k: v for k, v in p.items() if not pd.isna(v)},
                           **{k: v for k, v in r.items() if v is not None}})
        store.upsert("matches", merged)
    store.upsert("teams", _new_teams(rows))


def _new_teams(rows: list[dict]) -> list[dict]:
    have = set(store.read("teams")["team_id"])
    return [t for t in ingest.team_rows(rows) if t["team_id"] not in have]


def save_markets(outs: list[dict], season: str) -> None:
    """Add market types not seen before (first_seen_season keeps the first season)."""
    have = set(store.read("markets")["market_type_id"])
    new = [r for r in ingest.market_rows(outs, season) if r["market_type_id"] not in have]
    if new:
        store.upsert("markets", new)


# ---------------------------------------------------------------- snapshot

def snapshot_run(c: H.MackolikClient, *, full: bool | None = None) -> dict:
    cfg = load("pipeline")["snapshot"]
    now = now_utc()
    today = now.astimezone(TR).date()
    full = now.hour < RUN_HOURS_UTC[0] + 2 if full is None else full  # the morning run lists all days ahead
    ahead = cfg.get("days_ahead", 10) if full else cfg.get("days_ahead_intraday", 2)
    stats = {"dates": [], "matches_listed": 0, "fetched": 0, "odds_rows": 0, "errors": 0, "error_detail": []}
    failures = FailedItems("snapshot", now.isoformat().replace("+00:00", "Z"))

    matches = list_matches(c, [today + timedelta(days=i) for i in range(ahead + 1)], failures, stats)
    stats["matches_listed"] = len(matches)
    save_matches(matches)

    # what we already hold: latest snapshot price per selection, and which matches have snapshots
    latest: dict[tuple, dict] = {}
    have_snap: set[str] = set()
    for season, lid in _partitions(matches):
        o = store.read("odds", season=season, league_id=lid)
        if o.empty:
            continue
        o = o[o["price_type"].isin(SNAPSHOT_TYPES)].sort_values("captured_at_utc")
        have_snap |= set(o["match_id"])
        for r in o.to_dict("records"):
            latest[(r["match_id"], *[_k(r[k]) for k in SELECTION])] = r

    horizon = next_run_after(now) + timedelta(minutes=cfg.get("buffer_minutes", 40))
    todo: list[tuple[dict, str]] = []
    for m in sorted(matches, key=lambda m: m["kickoff_utc"]):
        if not m["iddaa_event_code"] or m["kickoff_utc"] <= now or m["status"] != "scheduled":
            continue
        if m["kickoff_utc"] <= horizon:
            todo.append((m, "closing"))
        elif m["match_id"] not in have_snap:
            todo.append((m, "opening"))
    queued = {m["match_id"] for m, _ in todo}
    by_id = {m["match_id"]: m for m in matches}
    for item in failures.pending("odds"):  # failed in an earlier run: try again if still upcoming
        m = by_id.get(item.get("match_id"))
        if m and m["match_id"] not in queued and m["kickoff_utc"] > now and m["iddaa_event_code"]:
            todo.append((m, "closing" if m["kickoff_utc"] <= horizon else "opening"))
            queued.add(m["match_id"])
            stats["retried"] = stats.get("retried", 0) + 1

    day_lists: dict = {}
    in_a_row = 0
    for m, reason in todo:
        if in_a_row >= MAX_FAILURES_IN_A_ROW:  # Mackolik is down: queue the rest instead of burning the time limit
            failures.add("odds", m["iddaa_event_code"], "not tried: Mackolik unreachable", match_id=m["match_id"],
                         match_date=m["kickoff_local_tr"][:10], kickoff_utc=m["kickoff_utc"].isoformat())
            stats["not_tried"] = stats.get("not_tried", 0) + 1
            continue
        try:
            outcomes, source, meta = ingest.fetch_outcomes(c, m, day_lists, np=1)
        except Exception as exc:  # noqa: BLE001 - logged and fetched again by the next run
            in_a_row += 1
            failures.add("odds", m["iddaa_event_code"], repr(exc), match_id=m["match_id"],
                         match_date=m["kickoff_local_tr"][:10], kickoff_utc=m["kickoff_utc"].isoformat())
            if isinstance(exc, ingest.WrongMatch):  # counted by the popup_match quality check
                failures.add("popup_mismatch", m["iddaa_event_code"], repr(exc), match_id=m["match_id"])
            stats["deferred"] = stats.get("deferred", 0) + 1
            if len(stats["error_detail"]) < 20:
                stats["error_detail"].append(f"odds {m['iddaa_event_code']}: {exc}")
            continue
        in_a_row = 0
        stats["fetched"] += 1
        stats["morebets_fallback"] = stats.get("morebets_fallback", 0) + (source == "morebets")
        part = {"season": m["season"], "league_id": m["league_id"]}
        if meta.get("id") and not m.get("arsiv_match_id"):
            m["arsiv_match_id"] = str(meta["id"])
            save_matches([m])
        if reason == "closing":
            store.relabel_odds(m["season"], m["league_id"], {m["match_id"]}, old="closing_snapshot", new="intraday_snapshot")
            rows, outs = ingest.odds_rows_from(m, outcomes, price_type="closing_snapshot", captured_at=now, source=source)
        else:
            rows, outs = ingest.odds_rows_from(m, outcomes, price_type="opening_snapshot", captured_at=now, source=source)
            rows = [_typed(r, latest) for r in rows]
            rows = [r for r in rows if r is not None]
        stats["odds_rows"] += len(rows)
        save_markets(outs, m["season"])
        store.upsert("odds", [{**r, **part} for r in rows])

    stats["failed_items"] = failures.finish()
    stats["due"] = len(todo) if matches else 1  # "saved nothing": no match listed, or popups due and none saved
    stats["saved"] = stats["fetched"] if matches else 0
    stats["quality"] = quality.run_checks(sorted(_partitions(matches)), "snapshot", now.isoformat(), run_at=failures.run_at)
    return stats


def _k(v):
    return None if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NA else (float(v) if isinstance(v, float) else v)


def _typed(row: dict, latest: dict[tuple, dict]) -> dict | None:
    """opening_snapshot for a new selection, intraday_snapshot for a changed price, None if unchanged."""
    prev = latest.get((row["match_id"], *[_k(row[k]) for k in SELECTION]))
    if prev is None:
        return row
    p = prev["odds"]
    same = (row["odds"] is None and pd.isna(p)) or (row["odds"] is not None and not pd.isna(p) and round(float(p), 2) == round(row["odds"], 2))
    return None if same else {**row, "price_type": "intraday_snapshot"}


# ---------------------------------------------------------------- results

FINAL_STATUS = ("finished", "postponed", "cancelled", "abandoned")


def results_run(c: H.MackolikClient, *, limit: int | None = None) -> dict:
    cfg = load("pipeline")["results"]
    unsettleable = defaultdict(set)
    for u in (load("pipeline").get("settlement") or {}).get("unsettleable", []):
        unsettleable[(u["league_id"], u["season"])] |= set(u["families"])
    now = now_utc()
    today = now.astimezone(TR).date()
    stats = {"dates": [], "listed": 0, "final": 0, "void": 0, "skipped_done": 0, "deferred": 0, "errors": 0,
             "error_detail": []}
    failures = FailedItems("results", now.isoformat().replace("+00:00", "Z"))
    days = [today - timedelta(days=d) for d in range(cfg.get("days_back", 5), -1, -1)]
    matches = list_matches(c, days, failures, stats)
    stats["listed"] = len(matches)
    save_matches(matches)

    done: set[str] = set()
    for season, lid in _partitions(matches):
        s = store.read("settlements", season=season, league_id=lid)
        if not s.empty:
            open_ = set(s.loc[s["status"] == "pending", "match_id"])
            done |= set(s["match_id"]) - open_
    budget_s = cfg.get("max_minutes", 110) * 60
    started = time.monotonic()
    day_lists: dict = {}
    touched: set[tuple[str, str]] = set()
    in_a_row = 0
    wait = timedelta(minutes=cfg.get("min_minutes_after_kickoff", 150))
    for m in sorted(matches, key=lambda m: m["kickoff_utc"]):
        if m["status"] not in FINAL_STATUS or not m["iddaa_event_code"] or now < m["kickoff_utc"] + wait:
            continue
        if m["match_id"] in done:
            stats["skipped_done"] += 1
            continue
        if limit is not None and stats["final"] + stats["void"] >= limit:
            break
        if time.monotonic() - started > budget_s:
            stats["stopped_early"] = True  # the follow-up run continues
            break
        if in_a_row >= 15:
            stats["errors"] += 1
            stats["error_detail"].append("15 matches in a row failed - Mackolik unreachable? stopping")
            break
        try:
            process_finished(c, m, day_lists, now, unsettleable[(m["league_id"], m["season"])])
        except Exception as exc:  # noqa: BLE001 - one match must not stop the run; it is retried next run
            in_a_row += 1
            log.warning("match %s deferred: %r", m["match_id"], exc)
            stats["deferred"] += 1
            failures.add("match", m["match_id"], repr(exc), match_id=m["match_id"], match_date=m["kickoff_local_tr"][:10],
                         kickoff_utc=m["kickoff_utc"].isoformat())
            if isinstance(exc, ingest.WrongMatch):
                failures.add("popup_mismatch", m["iddaa_event_code"], repr(exc), match_id=m["match_id"])
            if len(stats["error_detail"]) < 20:
                stats["error_detail"].append(f"match {m['match_id']}: {exc!r}")
            continue
        in_a_row = 0
        stats["void" if m["status"] != "finished" else "final"] += 1
        touched.add((m["season"], m["league_id"]))

    for season, lid in sorted(touched):
        flat.rebuild(season, lid)
    stats["failed_items"] = failures.finish()
    stats["saved"] = stats["final"] + stats["void"]
    stats["due"] = stats["saved"] + stats["deferred"] if stats["dates"] else 1
    stats["touched"] = [f"{lid} {s}" for s, lid in sorted(touched)]
    stats["quality"] = quality.run_checks(sorted(_partitions(matches)), "results", now.isoformat(), run_at=failures.run_at)
    return stats


def process_finished(c: H.MackolikClient, m: dict, day_lists: dict, now: datetime, unsettleable: set[str]) -> None:
    """One finished (or void) match: collect its rows and write them."""
    write_rows(collect_finished(c, m, day_lists, now, unsettleable))


def collect_finished(c: H.MackolikClient, m: dict, day_lists: dict, now: datetime, unsettleable: set[str], *,
                     allow_missing_stats: bool = False) -> dict:
    """Rows of one finished (or void) match: events, statistics, Nesine's final odds + winner marks, settlements.
    Returns {"matches": [...], "markets": [(outs, season)], "odds": [...], ...} with partition columns set.
    allow_missing_stats: when the statistics page fails, keep the match without statistics (corner markets stay
    unsettled; "stats" is empty) instead of raising."""
    part = {"season": m["season"], "league_id": m["league_id"]}
    if m["status"] != "finished":  # postponed / cancelled / abandoned: every stored selection is void
        o = store.read("odds", **part)
        o = o[o["match_id"] == m["match_id"]].drop_duplicates(SELECTION) if not o.empty else o
        return {"matches": [m], "settlements": [{**{k: _k(r[k]) for k in SELECTION}, "match_id": m["match_id"],
                                                  "status": "void", "settled_at_utc": now, **part}
                                                 for r in o.to_dict("records")]}
    # The key events (goal/card minutes, substitutions) settle none of the collected markets and are the least
    # reliable page; they are only fetched when the match went to extra time, to get the score after 90 minutes.
    events = []
    if ingest.went_to_extra_time(m):
        ke = www.key_events(c, m["match_id"])
        if ke is None:
            raise RuntimeError("key events failed")
        events = ingest.event_rows(m["match_id"], ke)
    page = www.stats_page(c, m["match_id"])
    if page is None and not allow_missing_stats:  # retry the whole match next run (corners stay unsettled otherwise)
        raise RuntimeError("statistics page failed")
    stats = ingest.stats_rows(m["match_id"], page, events) if page is not None else []
    m["stadium"] = (ingest.stadium(page) if page is not None else None) or m.get("stadium")
    ingest.apply_extra_time(m, events)
    outcomes, source, meta = ingest.fetch_outcomes(c, m, day_lists, np=0)
    if meta.get("id"):
        m["arsiv_match_id"] = str(meta["id"])
    odds, outs = ingest.odds_rows_from(m, outcomes, price_type="closing_history", source=source)
    ctx = ingest.engine_ctx(m, events, stats)
    sets = ingest.settlement_rows(m, outs, ctx, now, unsettleable_families=unsettleable)
    return {"matches": [m], "markets": [(outs, m["season"])],
            **{name: [{**r, **part} for r in rows]
               for name, rows in (("odds", odds), ("events", events), ("stats", stats), ("settlements", sets))}}


def write_rows(*collected: dict) -> None:
    """Write the rows of one or more collect_finished() results (one write per table and partition)."""
    merged: dict[str, list] = defaultdict(list)
    for c in collected:
        for k, v in c.items():
            merged[k].extend(v)
    if merged["matches"]:
        save_matches(merged["matches"])
    for outs, season in merged["markets"]:
        save_markets(outs, season)
    for name in ("odds", "events", "stats", "settlements"):
        if merged[name]:
            store.upsert(name, merged[name])
