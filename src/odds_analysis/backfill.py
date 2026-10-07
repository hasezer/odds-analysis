"""History backfill of the 26 leagues (2019-08-01 -> 6 days ago), newest first, resumable, within the minutes budget.

1. Index (once): the fixture page of every league season gives each match its season and stage (exact even for
   seasons that do not follow the calendar, e.g. the 2019/20 COVID restarts or Argentina's overlapping 2020/2021).
   -> data/backfill/fixtures.csv.gz
2. Dates, newest first: the www.mackolik.com listing of a date gives the iddaa codes; every finished match of the
   26 leagues is processed exactly like the daily results job (events, statistics, final odds + winner marks,
   settlements) and written per date. The cursor (data/backfill/state.json) moves one day back per finished date.
3. Every job stops after max_job_minutes, or as soon as the month's Actions minutes left would drop below
   daily_reserve (config/backfill.yaml). Progress: data/backfill_progress.csv and the README.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from datetime import time as dtime

import pandas as pd

from . import budget, daily, flat, quality, www
from . import http as H
from .config import DATA, ROOT, TR, load
from .ingest import season_type
from .leagues import leagues
from .runs import FailedItems

log = logging.getLogger(__name__)
UTC = timezone.utc
DIR = DATA / "backfill"
STATE = DIR / "state.json"
FIXTURES = DIR / "fixtures.csv.gz"
PROGRESS = DATA / "backfill_progress.csv"
README = ROOT / "README.md"
FIRST_SEASON = 2019
BUDGET_CHECK_S = 15 * 60
RESULTS_WINDOW = (dtime(4, 50), dtime(6, 0))  # UTC; the results run starts at 05:04


# ---------------------------------------------------------------- state

def load_state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {"indexed": [], "next_date": None}


def save_state(state: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")


def season_pages(lg: dict, last_year: int) -> list[tuple[str, str, str, str, bool]]:
    """[(page_label, season, slug, competition_id, special)] for one league, newest first."""
    mk = lg["mackolik"]
    out = []
    for y in range(last_year, FIRST_SEASON - 1, -1):
        if lg["calendar_year"]:
            out.append((str(y), str(y), mk["slug"], mk["competition_id"], False))
            if y in (lg.get("split_from") or []):
                out.append((f"{y}-{y + 1}", f"{y}/{str(y + 1)[2:]}", mk["slug"], mk["competition_id"], False))
        else:
            out.append((f"{y}-{y + 1}", f"{y}/{str(y + 1)[2:]}", mk["slug"], mk["competition_id"], False))
    for x in lg.get("extra") or []:
        out.append((x["season"], x["season"], x["slug"], x["competition_id"], True))
    return out


def build_index(c: H.MackolikClient, state: dict, deadline: float, stats: dict) -> bool:
    """Fetch the season fixture pages not indexed yet. Returns True when the index is complete."""
    rows = pd.read_csv(FIXTURES, dtype=str) if FIXTURES.exists() else pd.DataFrame()
    new = []
    done = set(state["indexed"])
    complete = True
    for lg in leagues():
        for page, season, slug, cid, special in season_pages(lg, date.today().year):
            key = f"{lg['league_id']} {season}"
            if key in done:
                continue
            if time.monotonic() > deadline:
                complete = False
                break
            fx = www.season_fixtures(c, slug, cid, page)
            if not fx and lg["calendar_year"] and "-" not in page and lg["league_id"] == "ARG-1":
                fx = www.season_fixtures(c, slug, cid, f"{page}-{int(page) + 1}")  # Superliga 2019/20 is filed as 2019-2020
            for f in fx:
                new.append({**f, "league_id": lg["league_id"], "season": season, "special": int(special)})
            done.add(key)
            stats["seasons_indexed"] = stats.get("seasons_indexed", 0) + 1
    if new:
        rows = pd.concat([rows, pd.DataFrame(new)], ignore_index=True).drop_duplicates("match_id", keep="last")
        DIR.mkdir(parents=True, exist_ok=True)
        rows.sort_values(["kickoff_utc", "match_id"]).to_csv(FIXTURES, index=False,
                                                              compression={"method": "gzip", "mtime": 0})
    state["indexed"] = sorted(done)
    return complete


# ---------------------------------------------------------------- dates

def process_date(c: H.MackolikClient, d: date, index: dict, failures: FailedItems, stats: dict, now: datetime,
                 unsettleable: dict, deadline: float = float("inf")) -> tuple[set[tuple[str, str]], bool]:
    """All matches of the 26 leagues on one Turkish date. Returns the touched (season, league_id) partitions and
    whether the date is complete (False: the job deadline came first; the matches done so far are saved)."""
    day_stats = {"dates": [], "error_detail": []}
    matches = daily.list_matches(c, [d], failures, day_stats)
    if not day_stats["dates"]:
        raise RuntimeError(f"date listing {d} failed")
    collected, touched, day_lists, todo = [], set(), {}, []
    for m in matches:
        fx = index.get(m["match_id"])
        if fx is not None:  # season and stage from the fixture page
            m["season"] = fx["season"]
            m["round"] = fx["stage"] if isinstance(fx["stage"], str) else m["round"]
            m["season_type"] = season_type(m["round"], special=fx["special"] == "1")
        touched.add((m["season"], m["league_id"]))
        if m["status"] not in daily.FINAL_STATUS or not m["iddaa_event_code"]:
            collected.append({"matches": [m]})  # no Nesine odds: the match is still stored (coverage)
            stats["no_odds"] += 1
            continue
        todo.append(m)
    # Mackolik often answers HTTP 500/502 for a page for ~20 s. Instead of sleeping 5/15/45 s on every such answer,
    # the first pass makes one attempt per request and moves on; the matches that failed get a second pass at the
    # end of the date with the normal retries and backoff. Only failures of the second pass count as failed.
    complete, default_delays = True, getattr(c, "retry_delays", H.BACKOFF_SECONDS)
    try:
        for first_pass in (True, False):
            c.retry_delays, again = (() if first_pass else default_delays), []
            for m in todo:
                if time.monotonic() > deadline:
                    complete = False
                    break
                failed_before = getattr(c, "failed", 0)
                try:
                    collected.append(daily.collect_finished(c, m, day_lists, now,
                                                            unsettleable[(m["league_id"], m["season"])]))
                    stats["final" if m["status"] == "finished" else "void"] += 1
                except Exception as exc:  # noqa: BLE001 - logged; retried by the next backfill job
                    if first_pass:
                        c.failed = failed_before
                        again.append(m)
                        continue
                    stats["deferred"] += 1
                    failures.add("match", m["match_id"], repr(exc), match_id=m["match_id"], match_date=d.isoformat())
                    if len(stats["error_detail"]) < 20:
                        stats["error_detail"].append(f"match {m['match_id']}: {exc!r}")
            stats["second_pass"] += len(again) if first_pass else 0
            todo = again
            if not complete or not todo:
                break
    finally:
        c.retry_delays = default_delays
    daily.write_rows(*collected)
    return touched, complete


def run(c: H.MackolikClient) -> dict:
    cfg = load("backfill")
    started = time.monotonic()
    deadline = started + cfg.get("max_job_minutes", 100) * 60
    now = datetime.now(UTC).replace(microsecond=0)
    stats = defaultdict(int, {"dates": [], "error_detail": []})
    # the daily results run (05:04 UTC) must not wait behind a backfill job: stop by 04:50, don't start until 06:00
    if RESULTS_WINDOW[0] <= now.time() < RESULTS_WINDOW[1]:
        stats["quiet"] = True
        stats["note"] = "results window (04:50-06:00 UTC): the 06:17 schedule continues"
        return dict(stats)
    cut = now.replace(hour=RESULTS_WINDOW[0].hour, minute=RESULTS_WINDOW[0].minute, second=0)
    if cut <= now:
        cut += timedelta(days=1)
    if (cut - now).total_seconds() < deadline - started:
        deadline = started + (cut - now).total_seconds()
        stats["quiet"] = True  # this job stops for the results run: no follow-up job, the 06:17 schedule continues
    allow = budget.allowance(now)
    stats["budget"] = allow
    if not allow["ok"]:
        stats["paused"] = f"minutes left {allow['left']} < daily_reserve {allow['reserve']}"
        write_progress(load_state(), allow)
        return dict(stats)
    state = load_state()
    failures = FailedItems("backfill", now.isoformat().replace("+00:00", "Z"))
    if not build_index(c, state, deadline, stats):
        save_state(state)
        stats["note"] = "fixture index not complete yet - continued by the next job"
        write_progress(state, allow)
        return dict(stats)
    save_state(state)
    fx = pd.read_csv(FIXTURES, dtype=str)
    index = fx.set_index("match_id").to_dict("index")
    unsettleable = defaultdict(set)
    for u in (load("pipeline").get("settlement") or {}).get("unsettleable", []):
        unsettleable[(u["league_id"], u["season"])] |= set(u["families"])

    today = now.astimezone(TR).date()
    newest = today - timedelta(days=cfg.get("newest_offset_days", 6))
    oldest = date.fromisoformat(cfg.get("oldest_date", "2019-08-01"))
    cursor = date.fromisoformat(state["next_date"]) if state.get("next_date") else newest
    retry = sorted({i["match_date"] for i in failures.pending("match") + failures.pending("listing")
                    if i.get("match_date")}, reverse=True)
    touched: set[tuple[str, str]] = set()
    last_budget = time.monotonic()
    queue = [date.fromisoformat(d) for d in retry]
    while True:
        if time.monotonic() > deadline:
            stats["stopped"] = "job time limit"
            break
        if time.monotonic() - last_budget > BUDGET_CHECK_S:
            last_budget = time.monotonic()
            allow = budget.allowance(datetime.now(UTC), running_minutes=(time.monotonic() - started) / 60)
            if not allow["ok"]:
                stats["paused"] = f"minutes left {allow['left']} < daily_reserve {allow['reserve']}"
                break
        if queue:
            d, is_retry = queue.pop(0), True
        elif cursor >= oldest:
            d, is_retry = cursor, False
        else:
            stats["finished"] = True
            break
        try:
            t, complete = process_date(c, d, index, failures, stats, now, unsettleable, deadline)
            touched |= t
            if not complete:  # the date is redone by the next job (upserts make that safe)
                if is_retry:
                    queue.insert(0, d)
                stats["stopped"] = "job time limit"
                break
            stats["dates"].append(d.isoformat())
        except Exception as exc:  # noqa: BLE001 - the date is retried by the next job
            failures.add("listing", d.isoformat(), repr(exc), match_date=d.isoformat())
            stats["error_detail"].append(f"date {d}: {exc!r}")
        if not is_retry:
            cursor = d - timedelta(days=1)
            state["next_date"] = cursor.isoformat()
            save_state(state)
    for d in queue:  # retries not reached in this job stay queued
        failures.add("listing", d.isoformat(), "retry not reached yet", match_date=d.isoformat())
    for season, lid in sorted(touched):
        flat.rebuild(season, lid)
    stats["failed_items"] = failures.finish()
    stats["saved"] = stats["final"] + stats["void"]
    stats["due"] = stats["saved"] + stats["deferred"]
    stats["cursor"] = state.get("next_date")
    stats["touched"] = [f"{lid} {s}" for s, lid in sorted(touched)]
    stats["quality"] = quality.run_checks(sorted(touched), "backfill", now.isoformat(), run_at=failures.run_at)
    write_progress(state, stats["budget"])
    return dict(stats)


# ---------------------------------------------------------------- progress

def progress_table(state: dict) -> pd.DataFrame:
    if not FIXTURES.exists():
        return pd.DataFrame(columns=["league_id", "season", "matches", "done", "pct"])
    cfg = load("backfill")
    fx = pd.read_csv(FIXTURES, dtype=str)
    day = pd.to_datetime(fx["kickoff_utc"], utc=True).dt.tz_convert("Europe/Istanbul").dt.date.astype(str)
    newest = (datetime.now(UTC).astimezone(TR).date() - timedelta(days=cfg.get("newest_offset_days", 6))).isoformat()
    fx = fx[(day >= cfg.get("oldest_date", "2019-08-01")) & (day <= newest)].assign(day=day)
    cursor = state.get("next_date")
    fx["done"] = fx["day"] > cursor if cursor else False
    out = fx.groupby(["league_id", "season"]).agg(matches=("match_id", "size"), done=("done", "sum")).reset_index()
    out["pct"] = (100 * out["done"] / out["matches"]).round(1)
    return out.sort_values(["season", "league_id"], ascending=[False, True])


def write_progress(state: dict, allow: dict | None) -> None:
    table = progress_table(state)
    table.to_csv(PROGRESS, index=False, lineterminator="\n")
    readme = README
    text = readme.read_text(encoding="utf-8")
    block = readme_block(table, state, allow)
    start, end = "<!-- backfill-progress:start -->", "<!-- backfill-progress:end -->"
    if start in text:
        text = re.sub(re.escape(start) + r".*?" + re.escape(end), block, text, flags=re.S)
    else:
        text = text.rstrip() + "\n\n## Backfill progress\n\n" + block + "\n"
    readme.write_text(text, encoding="utf-8")


def readme_block(table: pd.DataFrame, state: dict, allow: dict | None) -> str:
    lines = ["<!-- backfill-progress:start -->",
             f"_Updated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by the Backfill workflow (newest dates first)._", ""]
    if table.empty:
        lines.append("Not started yet: the first job builds the fixture index of every league season.")
    else:
        total, done = int(table["matches"].sum()), int(table["done"].sum())
        lines.append(f"**{done:,} of {total:,} matches ({100 * done / max(total, 1):.1f} %)** · next date to process: "
                     f"{state.get('next_date') or '-'}")
        lines += ["", "| Season | Matches | Done | % |", "|---|---|---|---|"]
        by = table.groupby("season")[["matches", "done"]].sum().sort_index(ascending=False)
        for season, r in by.iterrows():
            lines.append(f"| {season} | {int(r['matches']):,} | {int(r['done']):,} | {100 * r['done'] / max(r['matches'], 1):.0f} % |")
        lines.append("")
        lines.append("Per league and season: [`data/backfill_progress.csv`](data/backfill_progress.csv).")
    if allow:
        usage = allow.get("daily_usage_7d")
        lines += ["", f"Actions minutes this month: **{allow['used']:,} used of {allow['monthly']:,}**, "
                      f"{allow['left']:,} left; the backfill pauses below the daily reserve of {allow['reserve']:,}."
                  + (f" Daily jobs used {usage} min/day over the last 7 days (≈ {round(usage * 30):,}/month)." if usage else "")]
    lines.append("<!-- backfill-progress:end -->")
    return "\n".join(lines)
