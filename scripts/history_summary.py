"""Turn the history probe outputs into the Markdown tables of HISTORY_REPORT.md.

Inputs (scratch files, not committed): coverage.jsonl from history_coverage.py and, optionally, leagues.jsonl from
history_leagues.py (extra event/corner/card samples). Prints Markdown to stdout.

Usage: python scripts/history_summary.py --coverage coverage.jsonl [--leagues leagues.jsonl] [--budget 1100]
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import statistics
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ODDS_START = "2019-08-01"  # first day with iddaa codes in the date listing
TODAY = "2026-10-07"  # matches before this day are history; later ones come from the daily pipeline

# Per-request cost measured during the investigation (compressed bytes, seconds incl. the 1 req/s throttle).
REQ = {"popup": (10_000, 1.3), "events": (1_500, 1.1), "stats": (37_000, 1.1)}
LISTING = (166_000, 7.5)  # one date listing (livescores JSON) per calendar day
PARQUET_KB_PER_MATCH = 0.35  # odds ~0.21 KB (~80 selections) + match/events/stats rows


def label(season: str) -> str:
    """'2024' stays (calendar-year league), '2024-2025' -> '2024/25'."""
    if "-" not in season:
        return season
    a, b = season.split("-")
    return f"{a}/{b[2:]}"


def pct(n: int, d: int) -> str:
    return "–" if not d else f"{round(100 * n / d)}%"


def load(path: str | None) -> list[dict]:
    if not path or not Path(path).exists():
        return []
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coverage", required=True)
    ap.add_argument("--leagues")
    ap.add_argument("--budget", type=int, default=1100, help="Actions minutes per month available for backfill")
    a = ap.parse_args()
    leagues = yaml.safe_load((ROOT / "config" / "leagues.yaml").read_text(encoding="utf-8"))["leagues"]
    cov = {(r["league"], r["season"]): r for r in load(a.coverage)}
    extra = collections.defaultdict(list)
    for r in load(a.leagues):
        extra[(r["league"], r["season"])] += r["samples"]

    per_req_s = sum(s for _, s in REQ.values())
    per_req_b = sum(b for b, _ in REQ.values())
    out: list[str] = []
    plan: list[tuple[str, str, str, int, set]] = []  # (season end, league, season, matches with odds, match days)

    out.append("### Summary per league\n")
    out.append("| League | First season with Nesine odds | Listed with odds (sampled matchday) | "
               "Markets per match by season (popup, median) | Events | Corners | Cards (stats page) |")
    out.append("|---|---|---|---|---|---|---|")
    season_rows: list[str] = []
    for lg in leagues:
        first = None
        coded = listed = 0
        mk_by_season = []
        ev = co = ca = n_s = n_e = 0
        for key, r in sorted(((k, v) for k, v in cov.items() if k[0] == lg["key"]), key=lambda kv: kv[0][1]):
            s = key[1]
            samples = [x for x in r["samples"] if x.get("popup_same_match")]
            lst = r.get("listing") or {}
            coded += lst.get("with_code", 0)
            listed += lst.get("league_matches", 0)
            # popup market counts: matchday sample + random matches of the season (history_leagues.py)
            mkts = [x["markets"] for x in samples if x.get("markets")]
            mkts += [x["popup_markets"] for x in extra.get(key, []) if x.get("popup_same_match") and x.get("popup_markets")]
            if mkts and first is None:
                first = s
            if mkts:
                mk_by_season.append(f"{label(s)}: {round(statistics.median(mkts))}")
            # only pages that loaded count (a transient 502 during the probe is not missing data)
            for x in r["samples"] + extra.get(key, []):
                if "events" in x:
                    n_e += 1
                    ev += bool(x["events"])
                if "corners" in x:
                    n_s += 1
                    co += x["corners"] is not None
                    # no "Sarı Kart" row = no yellow card; key events list every card as well
                    ca += (x.get("yellow_cards") or x.get("yellow_cards_stat")) is not None or "events" in x
            # matches the backfill would fetch: played, on/after the first listing day with codes, scaled by the
            # share of the league's matches that carried an iddaa code on the sampled matchday
            dates = [d for d in r.get("dates") or [] if d < TODAY]
            in_window = sum(d >= ODDS_START for d in dates)
            share = (lst.get("with_code", 0) / lst["league_matches"]) if lst.get("league_matches") else 0
            with_odds = round(in_window * share) if mkts or share else 0
            if with_odds:
                days_tr = {d for d in dates if d >= ODDS_START}
                plan.append((max(dates), lg["name"], label(s), with_odds, days_tr))
            stages = {k: v for k, v in (r.get("stages") or {}).items()  # the extra stages only (playoffs, groups)
                      if k not in ("Normal Sezon", "1. Tur", "2. Tur") and v != r["matches"]}
            name = r.get("competition") or lg["name"]
            season_rows.append(f"| {name} | {label(s)} | {r['matches']} | {with_odds} | "
                               f"{', '.join(f'{k} ({v})' for k, v in stages.items()) or '–'} |")
        out.append(f"| {lg['name']} | {label(first) if first else 'none found'} | {pct(coded, listed)} | "
                   f"{' · '.join(mk_by_season) or '–'} | {pct(ev, n_e)} | {pct(co, n_s)} | {pct(ca, n_s)} |")

    out.append("\n<details><summary>Matches per season (fixture pages; playoff stages included)</summary>\n")
    out.append("| League | Season | Matches (incl. not yet played) | Est. matches with Nesine odds, played by "
               f"{TODAY} | Extra stages |")
    out.append("|---|---|---|---|---|")
    out += season_rows
    out.append("\n</details>")

    total = sum(p[3] for p in plan)
    # one date listing per day on which any of the leagues played (gives uuid, iddaa code, score)
    all_days = set().union(*(p[4] for p in plan)) if plan else set()
    days = len(all_days)
    req = 3 * total + days
    secs = total * per_req_s + days * LISTING[1]
    gb = (total * per_req_b + days * LISTING[0]) / 1e9
    out.append("\n### Backfill estimate (all 26 leagues, from the oldest season with odds)\n")
    out.append(f"- Matches with Nesine odds: **{total:,}**")
    out.append(f"- Requests: **{req:,}** (3 per match: popup, key events, stats page; plus {days:,} date listings)")
    out.append(f"- Time at 1 request/second: **{req / 3600:.1f} h**; with measured latency: **{secs / 3600:.1f} h**")
    out.append(f"- Transferred (compressed): **{gb:.1f} GB**")
    out.append(f"- Parquet size: **~{total * PARQUET_KB_PER_MATCH / 1024:.0f} MB**")
    # option (b): the current and the previous season of every league only
    recent: dict[str, list] = collections.defaultdict(list)
    for p in sorted(plan, key=lambda p: p[0], reverse=True):
        recent[p[1]].append(p)
    two = [p for ps in recent.values() for p in ps[:2]]
    n2, d2 = sum(p[3] for p in two), len(set().union(*(p[4] for p in two)))
    h2 = (n2 * per_req_s + d2 * LISTING[1]) / 3600
    out.append(f"- Only the last 2 seasons per league: **{n2:,}** matches, **{3 * n2 + d2:,}** requests, "
               f"~{h2:.1f} h, {(n2 * per_req_b + d2 * LISTING[0]) / 1e9:.1f} GB")

    out.append(f"\n### Chunk plan, newest season first ({a.budget} Actions minutes per month for backfill)\n")
    out.append("| Month | Seasons | Matches | Minutes |")
    out.append("|---|---|---|---|")
    plan.sort(key=lambda p: p[0], reverse=True)
    per_label = collections.Counter(p[2] for p in plan)

    def describe(items: list[tuple[str, str]]) -> str:
        by_label: dict[str, list[str]] = collections.defaultdict(list)
        for name, lab in items:
            by_label[lab].append(name)
        return "; ".join(f"{lab}: all ({len(ns)})" if len(ns) == per_label[lab] else f"{lab}: {', '.join(ns)}"
                         for lab, ns in by_label.items())

    month, used, items, n, seen = 1, 0.0, [], 0, set()
    per_match_min = per_req_s / 60 * 1.1  # +10% for retries and job overhead
    for p in plan:
        need = p[3] * per_match_min + len(p[4] - seen) * LISTING[1] / 60
        seen |= p[4]
        if used + need > a.budget and items:
            out.append(f"| {month} | {describe(items)} | {n:,} | {math.ceil(used)} |")
            month, used, items, n = month + 1, 0.0, [], 0
        used += need
        n += p[3]
        items.append((p[1], p[2]))
    if items:
        out.append(f"| {month} | {describe(items)} | {n:,} | {math.ceil(used)} |")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
