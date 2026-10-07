"""Results job: every date in Mackolik's rolling window -> data/results, events, stats, official, odds(post_match).

For each finished match (list A, np=0) that is not final yet in data/results:
  D  MatchData (status, MS/İY, events)  -> results + events
  D  match page (+ rbStats if no corners) -> header + stats
  B  odds popup after FT                -> official result marks (highlight) + post-match odds
Matches are only stored as final when D says 'MS' (played) or postponed/cancelled (void).
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta

from . import http as H
from .config import TR, iso, load, now_utc
from .markets import normalize_market, normalize_selection
from .parsers import parse_day_list, parse_match_data, parse_match_page, parse_odds_popup, parse_stats_box, popup_matches
from .rows import log_unmapped, match_row, odds_rows
from .runs import FailedItems
from .storage import append_log, frame, read_partition, upsert_partition

log = logging.getLogger(__name__)

VOID_STATUS = re.compile(r"^(Ert|İpt|Ipt|Iptal|İptal|Can|Hük|Huk)", re.I)  # Ertelendi, İptal, Hükmen?
CORNER_STATS = ("Korner", "Köşe Vuruşu")


def classify_status(status: str | None) -> str:
    s = (status or "").strip()
    if s == "MS":
        return "final"
    if VOID_STATUS.match(s):
        return "void"
    return "pending"


def ft90(md: dict) -> tuple[int, int] | None:
    """Score after 90 minutes: d.ft when filled (extra-time matches), else d.s."""
    return md["ft_field"] or md["score"]


def corners(stats_by_source: dict[str, dict]) -> tuple[int | None, int | None, str | None]:
    for source in ("page", "opta", "rb"):
        st = stats_by_source.get(source) or {}
        for name in CORNER_STATS:
            if name in st:
                h, a = st[name]
                if h.isdigit() and a.isdigit():
                    return int(h), int(a), source
    return None, None, None


def events_complete(md: dict, score: tuple[int, int] | None) -> bool:
    if score is None:
        return False
    goals = [e for e in md["events"] if e["type"] == "goal" and (md["et"] is None or (e["minute"] or 0) <= 90)]
    h = sum(e["team"] == "home" for e in goals)
    return (h, len(goals) - h) == tuple(score)


def run(client: H.MackolikClient, *, raw_prefix: str = "results", limit: int | None = None) -> dict:
    cfg = load("pipeline")["results"]
    now = now_utc()
    fetched = iso(now)
    today = now.astimezone(TR).date()
    dates = [(today - timedelta(days=d)) for d in range(cfg.get("days_back", 5), -1, -1)]
    stats = {"dates": [], "listed": 0, "final": 0, "void": 0, "pending": 0, "skipped_done": 0,
             "official_markets": 0, "deferred": 0, "errors": 0, "error_detail": []}
    failures = FailedItems("results", fetched)  # deferred matches stay unfinished and are retried next run
    unmapped: dict[str, dict] = {}

    rows: dict[int, dict] = {}
    for day in dates:
        res = client.get(H.day_list_path(day.strftime("%d.%m.%Y"), np=0), save_as=f"{raw_prefix}/A_np0_{day}.html.gz",
                         backoff=H.LIST_BACKOFF_SECONDS)
        if not res.ok:
            failures.add("day_list", day.isoformat(), res.error, match_date=day.isoformat())
            stats["error_detail"].append(f"A {day}: {res.error}")
            continue
        stats["dates"].append(day.isoformat())
        for r in parse_day_list(res.text):
            if r["date"]:
                rows.setdefault(r["mackolik_match_id"], r)
    stats["listed"] = len(rows)

    match_dates = sorted({r["date"] for r in rows.values()})
    done: set[str] = set()
    ours: set[str] = set()
    for d in match_dates:
        res_df = read_partition("results", d)
        if not res_df.empty:
            done |= set(res_df["match_id"])
        m_df = read_partition("matches", d)
        if not m_df.empty:
            ours |= set(m_df["match_id"])

    out: dict[str, dict[str, list]] = {}

    def put(table: str, date: str, items: list[dict]) -> None:
        out.setdefault(table, {}).setdefault(date, []).extend(items)

    def flush() -> None:
        """Write what we have so far: a run that hits the time limit keeps its progress."""
        for table, parts in out.items():
            for date, items in parts.items():
                if table == "matches":  # never overwrite snapshot metadata (first_seen etc.)
                    old = read_partition("matches", date)
                    have = set(old["match_id"]) if not old.empty else set()
                    items = [i for i in items if str(i["match_id"]) not in have]
                if items:
                    upsert_partition(table, date, frame(items))
        out.clear()

    budget_s = cfg.get("max_minutes", 110) * 60
    started = time.monotonic()
    consecutive_failures = 0
    processed = 0

    for mid, r in sorted(rows.items(), key=lambda kv: (kv[1]["date"], kv[1]["kickoff_local"] or "")):
        if limit is not None and stats["final"] + stats["void"] + stats["pending"] >= limit:
            break
        if time.monotonic() - started > budget_s:
            stats["stopped_early"] = True  # the rest is picked up by the follow-up run
            log.warning("time budget reached; stopping with %d matches left", len(rows) - processed)
            break
        if consecutive_failures >= 15:
            stats["errors"] += 1
            stats["error_detail"].append("15 matches in a row failed - Mackolik unreachable? stopping")
            break
        processed += 1
        if processed % 25 == 0:
            flush()
        if str(mid) in done:
            stats["skipped_done"] += 1
            continue
        m = match_row(r, fetched)
        ko = datetime.fromisoformat(m["kickoff_utc"].replace("Z", "+00:00"))
        if now < ko + timedelta(minutes=cfg.get("min_minutes_after_kickoff", 150)):
            continue
        has_list_score = r["ft_home"] is not None
        if not has_list_score and str(mid) not in ours:
            continue  # unscored match we hold no odds for: not worth requests (postponed etc.)
        try:
            res = client.get(H.match_data_path(mid), referer=H.match_referer(mid), save_as=f"{raw_prefix}/D_data_{mid}.json.gz")
            if not res.ok:
                raise RuntimeError(f"MatchData {res.error}")
            md = parse_match_data(res.text)
            kind = classify_status(md["status"])
            if kind == "pending":
                stats["pending"] += 1
                continue
            date = r["date"]
            result = {
                "match_id": mid, "event_code": r["event_code"], "date": date, "kickoff_utc": m["kickoff_utc"],
                "league_code": r["league_code"], "home_team": r["home_team"], "away_team": r["away_team"],
                "status": md["status"], "result_type": kind, "fetched_utc": fetched,
                "list_ht": f"{r['ht_home']}-{r['ht_away']}" if r["ht_home"] is not None else None,
                "list_ft": f"{r['ft_home']}-{r['ft_away']}" if has_list_score else None,
            }
            if kind == "void":
                stats["void"] += 1
                put("results", date, [result])
                put("matches", date, [m])
                continue

            score = ft90(md)
            result.update({
                "ft_home": score[0] if score else None, "ft_away": score[1] if score else None,
                "ht_home": md["ht"][0] if md["ht"] else None, "ht_away": md["ht"][1] if md["ht"] else None,
                "et_score": "-".join(map(str, md["et"])) if md["et"] else None,
                "pen_score": "-".join(map(str, md["pen"])) if md["pen"] else None,
                "final_score_text": "-".join(map(str, md["score"])) if md["score"] else None,
                "events_complete": events_complete(md, score),
                "n_events": len(md["events"]),
            })
            if md["ft_field"] or md["et"] or md["pen"]:
                append_log("extra_time_matches", [{"logged_utc": fetched, "match_id": mid, "teams": f"{r['home_team']} - {r['away_team']}",
                                                   "status": md["status"], "s": result["final_score_text"], "ft": md["ft_field"],
                                                   "et": md["et"], "pen": md["pen"], "used_90min": score}])
            if has_list_score and score and (r["ft_home"], r["ft_away"]) != tuple(score) and not md["ft_field"]:
                append_log("score_mismatches", [{"logged_utc": fetched, "match_id": mid, "date": date,
                                                 "teams": f"{r['home_team']} - {r['away_team']}",
                                                 "list_ft": result["list_ft"], "d_ft": f"{score[0]}-{score[1]}",
                                                 "list_ht": result["list_ht"], "d_ht": f"{result['ht_home']}-{result['ht_away']}"}])
            if not result["events_complete"] and md["events"]:
                g = [e for e in md["events"] if e["type"] == "goal"]
                append_log("event_score_mismatches", [{"logged_utc": fetched, "match_id": mid, "date": date,
                                                       "teams": f"{r['home_team']} - {r['away_team']}", "ft": result["final_score_text"],
                                                       "goal_events": "; ".join(f"{e['minute']}' {e['team']} {e['score_after']}" for e in g)}])
            put("events", date, [{"match_id": mid, "seq": i, **{k: e[k] for k in (
                "minute", "team", "type", "detail", "player_id", "player", "assist_id", "assist", "score_after",
                "player_out_id", "player_out")}} for i, e in enumerate(md["events"])])

            page = client.get(H.match_page_path(mid), save_as=f"{raw_prefix}/D_page_{mid}.html.gz")
            stats_by_source: dict[str, dict] = {}
            if page.ok:
                hdr = parse_match_page(page.text)
                result.update({k: hdr.get(k) for k in ("league", "referee", "stadium", "attendance")})
                stats_by_source["opta"] = hdr.get("stats") or {}
            if corners(stats_by_source)[0] is None and cfg.get("fetch_rb_stats_if_no_corners", True):
                rb = client.get(H.rb_stats_path(mid), referer=H.match_referer(mid), save_as=f"{raw_prefix}/D_rb_{mid}.html.gz")
                if rb.ok and rb.text.strip():
                    stats_by_source["rb"] = parse_stats_box(rb.text)
            ch, ca, csrc = corners(stats_by_source)
            result.update({"corners_home": ch, "corners_away": ca, "corners_source": csrc,
                           "ht_corners_home": None, "ht_corners_away": None})
            put("stats", date, [{"match_id": mid, "source": src, "stat": k, "home": v[0], "away": v[1]}
                                for src, st in stats_by_source.items() for k, v in st.items()])

            official = 0
            if r["event_code"]:
                b = client.get(H.odds_popup_path(r["event_code"]), save_as=f"{raw_prefix}/B_{r['event_code']}.json.gz")
                pop = parse_odds_popup(b.text) if b.ok else None
                if pop is not None and not popup_matches(pop, r["event_code"], m["kickoff_utc"]):
                    # the popup resolved this event code to an older match: no official marks, no post-match odds
                    result["official_status"] = f"popup_other_match:{pop['match'] and pop['match'].get('iddaa_code')}"
                    stats["popup_mismatch"] = stats.get("popup_mismatch", 0) + 1
                elif pop is not None:
                    result["official_status"] = "ok"
                    result["b_status"] = pop["match"] and pop["match"]["status"]
                    off = []
                    by_market: dict = {}
                    for o in pop["outcomes"]:
                        by_market.setdefault(o["market_id"], []).append(o)
                    for mkt_id, outs in by_market.items():
                        decided = any(o["highlight"] for o in outs)
                        official += decided
                        mk = normalize_market(outs[0]["market_name"])
                        for o in outs:
                            off.append({"event_code": r["event_code"], "match_id": mid, "market_id": mkt_id,
                                        "market_type_id": o["market_type_id"], "market_tr": o["market_name"],
                                        "market_key": mk.key if mk else None, "line": o["line"],
                                        "selection_tr": o["selection"],
                                        "selection": normalize_selection(mk, o["selection"], r["home_team"], r["away_team"]) if mk else None,
                                        "market_decided": decided, "highlight": o["highlight"], "final_odds": o["odds"],
                                        "fetched_utc": fetched})
                    put("official", date, off)
                    post = odds_rows(pop, event_code=r["event_code"], match_id=mid, snapshot_utc=fetched,
                                     home=r["home_team"], away=r["away_team"], unmapped=unmapped)
                    put("odds", date, [{**p, "snapshot_type": "post_match", "source": "popup"} for p in post])
                else:
                    raise RuntimeError(f"popup {r['event_code']}: {b.error}")  # retry the match next run
            result["official_markets"] = official
            if result.get("official_status") == "ok" and official == 0 and now - ko < timedelta(hours=36):
                stats["pending"] += 1  # Nesine has not marked results yet: retry next run
                continue
            stats["official_markets"] += official
            stats["final"] += 1
            put("results", date, [result])
            put("matches", date, [m])
            consecutive_failures = 0
        except Exception as exc:  # noqa: BLE001 - one match must not stop the run; it is retried next run
            log.warning("match %s deferred: %r", mid, exc)
            stats["deferred"] += 1
            failures.add("match", mid, repr(exc), match_id=mid, match_date=r["date"], kickoff_utc=m["kickoff_utc"])
            consecutive_failures += 1
            if len(stats["error_detail"]) < 20:
                stats["error_detail"].append(f"match {mid}: {exc!r}")

    flush()
    stats["unmapped_new"] = log_unmapped(unmapped)
    stats["failed_items"] = failures.finish()
    # "saved nothing": no day list could be read, or matches were due and none was saved
    stats["saved"] = stats["final"] + stats["void"]
    stats["due"] = stats["saved"] + stats["deferred"] if stats["dates"] else 1
    return stats
