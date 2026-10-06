"""Phase 0: verify every Mackolik/Nesine endpoint from the machine this runs on (GitHub Actions).

Writes phase0_output/summary.json, phase0_output/summary.md, phase0_output/market_catalog.csv
and raw responses to phase0_output/raw/ (uploaded as a 7-day artifact, never committed).
Exit code 1 if any critical check fails (e.g. GitHub runners are blocked).
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import sys
import traceback
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from odds_analysis import http as H  # noqa: E402
from odds_analysis.parsers import (  # noqa: E402
    parse_day_list,
    parse_match_data,
    parse_match_page,
    parse_odds_popup,
    parse_stats_box,
)

TR = timezone(timedelta(hours=3))
EXAMPLE_FINISHED_EVENT = "3179478"  # Galler-Danimarka 04.10.2026, FT 0-1
EXAMPLE_MATCH_ID = 4445150  # Portekiz-Norveç 04.10.2026, MS 2-1, İY 1-1
BLOCK_MARKERS = ("cf-chl", "Attention Required", "Access denied", "captcha", "Request unsuccessful")

log = logging.getLogger("phase0")


class Checks:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, name: str, ok: bool, detail: str = "", critical: bool = True) -> bool:
        self.items.append({"check": name, "ok": bool(ok), "critical": critical, "detail": detail})
        log.info("%s %s - %s", "PASS" if ok else ("FAIL" if critical else "WARN"), name, detail)
        return ok

    @property
    def failed_critical(self) -> list[dict]:
        return [c for c in self.items if c["critical"] and not c["ok"]]


def looks_blocked(res: H.FetchResult) -> bool:
    return res.status in (401, 403, 451) or any(m.lower() in res.text[:5000].lower() for m in BLOCK_MARKERS)


def fetch_desc(res: H.FetchResult) -> str:
    return f"HTTP {res.status}, {len(res.text):,} chars, {res.elapsed_s:.1f}s, attempts={res.attempts}" + (
        f", error={res.error}" if res.error else ""
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="phase0_output")
    ap.add_argument("--sample", type=int, default=15, help="finished matches to deep-check (B + D)")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    out = Path(args.out)
    raw = out / "raw"
    out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    rng = random.Random(args.seed)
    checks = Checks()
    facts: dict = {"run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    catalog: Counter = Counter()
    catalog_examples: dict[tuple, dict] = {}

    def add_catalog(popup: dict) -> None:
        seen = set()
        for o in popup["outcomes"]:
            key = (o["market_type_id"], o["market_name"])
            if key in seen:
                continue
            seen.add(key)
            catalog[key] += 1
            catalog_examples.setdefault(key, {"line": o["line"], "selections": []})
        for o in popup["outcomes"]:
            ex = catalog_examples[(o["market_type_id"], o["market_name"])]
            if o["selection"] not in ex["selections"] and len(ex["selections"]) < 12:
                ex["selections"].append(o["selection"])

    with H.MackolikClient(raw_dir=raw) as client:
        # ---------- A: day list ----------
        today = datetime.now(TR).date()
        window: dict[str, dict] = {}
        all_rows: dict[int, dict] = {}
        for offset in range(-7, 3):
            day = today + timedelta(days=offset)
            d = day.strftime("%d.%m.%Y")
            res = client.get(H.day_list_path(d, np=0), save_as=f"A_list_{day.isoformat()}.html")
            if offset == -7 and looks_blocked(res):
                checks.add("A reachable (not blocked)", False, fetch_desc(res))
            rows = parse_day_list(res.text) if res.ok else []
            per_section = Counter(r["date"] for r in rows)
            window[day.isoformat()] = {
                "http": res.status,
                "chars": len(res.text),
                "rows": len(rows),
                "sections": dict(per_section),
                "played": sum(r["ft_home"] is not None for r in rows),
            }
            for r in rows:
                all_rows.setdefault(r["mackolik_match_id"], r)
        facts["A_window_by_requested_date"] = window
        non_empty = [k for k, v in window.items() if v["rows"] > 0]
        checks.add("A reachable (not blocked)", any(v["http"] == 200 for v in window.values()), f"{len(non_empty)} dates returned rows")
        past_days = [k for k in non_empty if k < today.isoformat()]
        checks.add("A returns played matches for past dates (np=0)", len(past_days) >= 3, f"past dates with data: {past_days}")
        oldest = min(non_empty) if non_empty else None
        facts["A_oldest_date_with_rows"] = oldest
        facts["A_window_days_back"] = (today - datetime.fromisoformat(oldest).date()).days if oldest else None

        res = client.get(H.day_list_path("-1", np=0), save_as="A_list_all_np0.html")
        rows_all = parse_day_list(res.text) if res.ok else []
        facts["A_d_minus1_np0"] = {"http": res.status, "chars": len(res.text), "rows": len(rows_all),
                                   "sections": dict(sorted(Counter(r["date"] for r in rows_all).items()))}
        checks.add("A d=-1 returns whole window in one call", len(rows_all) > 0, fetch_desc(res), critical=False)
        res_np1 = client.get(H.day_list_path("-1", np=1), save_as="A_list_all_np1.html")
        rows_np1 = parse_day_list(res_np1.text) if res_np1.ok else []
        facts["A_d_minus1_np1_rows"] = len(rows_np1)
        res_w = client.get(H.day_list_path(today.strftime("%d.%m.%Y"), np=0, week=1), save_as="A_list_week_param_test.html")
        today_ids = {r["mackolik_match_id"] for r in parse_day_list((raw / f"A_list_{today.isoformat()}.html").read_text(encoding="utf-8"))}
        facts["A_week_param_ignored"] = {r["mackolik_match_id"] for r in parse_day_list(res_w.text)} == today_ids

        for r in rows_all:
            all_rows.setdefault(r["mackolik_match_id"], r)
        rows_list = list(all_rows.values())
        facts["A_field_coverage"] = {
            "rows": len(rows_list),
            "event_code": sum(r["event_code"] is not None for r in rows_list),
            "league_code": sum(r["league_code"] is not None for r in rows_list),
            "mbs": sum(r["mbs"] is not None for r in rows_list),
            "with_scores": sum(r["ft_home"] is not None for r in rows_list),
            "with_1x2_odds": sum(any(m["market"] == "Maç Sonucu" for m in r["markets"]) for r in rows_list),
            "mbs_distribution": dict(Counter(r["mbs"] for r in rows_list)),
        }
        ex = next((r for r in rows_list if r["mackolik_match_id"] == EXAMPLE_MATCH_ID), None)
        if ex:
            ok = (ex["ft_home"], ex["ft_away"], ex["ht_home"], ex["ht_away"]) == (2, 1, 1, 1) and ex["event_code"] is not None
            checks.add("A parses Portekiz-Norveç row (2-1, İY 1-1, event code)", ok, json.dumps({k: ex[k] for k in ("date", "kickoff_local", "league_code", "mbs", "event_code", "home_team", "away_team")}, ensure_ascii=False), critical=False)
            facts["A_example_row"] = ex
        else:
            checks.add("A parses Portekiz-Norveç row", False, "match 4445150 no longer in rolling window", critical=False)

        # ---------- B: odds popup ----------
        res = client.get(H.odds_popup_path(EXAMPLE_FINISHED_EVENT), save_as=f"B_popup_{EXAMPLE_FINISHED_EVENT}.json")
        try:
            pop = parse_odds_popup(res.text)
            n_markets = len({o["market_id"] for o in pop["outcomes"]})
            checks.add("B popup works for finished match e=3179478", res.ok and n_markets > 0,
                       f"{fetch_desc(res)}; status={pop['match'] and pop['match']['status']}; Nesine markets={n_markets}; "
                       f"highlighted outcomes={sum(o['highlight'] for o in pop['outcomes'])}")
            add_catalog(pop)
            facts["B_finished_example"] = {"match": pop["match"], "markets": n_markets, "outcomes": len(pop["outcomes"]),
                                           "highlighted": sum(o["highlight"] for o in pop["outcomes"]),
                                           "null_odds": sum(o["odds"] is None for o in pop["outcomes"])}
            facts["B_finished_1x2"] = [o for o in pop["outcomes"] if o["market_name"] == "Maç Sonucu"]
        except Exception as exc:  # noqa: BLE001
            checks.add("B popup works for finished match e=3179478", False, f"{fetch_desc(res)}; {exc}")

        upcoming = [r for r in rows_np1 if r["event_code"]]
        for r in rng.sample(upcoming, min(5, len(upcoming))):
            res = client.get(H.odds_popup_path(r["event_code"]), save_as=f"B_popup_{r['event_code']}.json")
            try:
                pop = parse_odds_popup(res.text)
                add_catalog(pop)
                facts.setdefault("B_upcoming_samples", []).append(
                    {"event_code": r["event_code"], "teams": f"{r['home_team']} - {r['away_team']}", "league": r["league_code"],
                     "status": pop["match"] and pop["match"]["status"], "start_time_utc": pop["match"] and pop["match"]["start_time"],
                     "kickoff_local_list": f"{r['date']} {r['kickoff_local']}",
                     "markets": len({o['market_id'] for o in pop['outcomes']}), "nesine": pop.get("nesine_found")})
            except Exception as exc:  # noqa: BLE001
                facts.setdefault("B_upcoming_samples", []).append({"event_code": r["event_code"], "error": str(exc)})
        ups = facts.get("B_upcoming_samples", [])
        checks.add("B popup works for upcoming matches", any(u.get("markets") for u in ups), f"{sum(bool(u.get('markets')) for u in ups)}/{len(ups)} returned Nesine markets")

        # ---------- C: program page ----------
        res = client.get(H.PROGRAM_PATH, referer="https://arsiv.mackolik.com/", save_as="C_program.html")
        rows_c = parse_day_list(res.text) if res.ok else []
        facts["C_program"] = {"http": res.status, "rows": len(rows_c), "sections": dict(Counter(r["date"] for r in rows_c)),
                              "with_event_code": sum(r["event_code"] is not None for r in rows_c),
                              "with_league_code": sum(r["league_code"] is not None for r in rows_c)}
        checks.add("C program page reachable and parseable", len(rows_c) > 0, fetch_desc(res))

        # ---------- D: match detail ----------
        def check_match(mid: int, tag: str) -> dict:
            ref = H.match_referer(mid)
            page = client.get(H.match_page_path(mid), save_as=f"D_page_{mid}.html")
            dtl = client.get(H.match_data_path(mid), referer=ref, save_as=f"D_data_{mid}.json")
            opta = client.get(H.opta_stats_path(mid), referer=ref, save_as=f"D_opta_{mid}.html")
            rb = client.get(H.rb_stats_path(mid), referer=ref, save_as=f"D_rb_{mid}.html")
            info: dict = {"match_id": mid, "tag": tag, "http": [page.status, dtl.status, opta.status, rb.status]}
            try:
                hdr = parse_match_page(page.text) if page.ok else {}
                info.update({k: hdr.get(k) for k in ("league", "kickoff_local", "status_text", "score", "stadium", "referee", "attendance")})
                info["stats_in_page"] = bool(hdr.get("stats"))
            except Exception as exc:  # noqa: BLE001
                info["page_error"] = repr(exc)
            try:
                md = parse_match_data(dtl.text)
                info.update({"data_status": md["status"], "data_score": md["score"], "ht": md["ht"], "ft_field": md["ft_field"],
                             "et": md["et"], "pen": md["pen"],
                             "goals": [f"{e['minute']}' {e['team']} ({e['score_after']}) {e['detail']}" for e in md["events"] if e["type"] == "goal"],
                             "cards": [f"{e['minute']}' {e['team']} {e['type']}{'/' + e['detail'] if e['detail'] else ''}" for e in md["events"] if e["type"] in ("yellow", "red")],
                             "n_subs": sum(e["type"] == "sub" for e in md["events"]),
                             "events_goal_score_matches": md["score"] is None or md["goal_score_from_events"] == tuple(md["score"])})
            except Exception as exc:  # noqa: BLE001
                info["data_error"] = repr(exc)
            info["opta_stats"] = parse_stats_box(opta.text) if opta.ok and opta.text.strip() else {}
            info["rb_stats"] = parse_stats_box(rb.text) if rb.ok and rb.text.strip() else {}
            return info

        ex_d = check_match(EXAMPLE_MATCH_ID, "example")
        facts["D_example"] = ex_d
        checks.add("D match page reachable", ex_d["http"][0] == 200, f"HTTP {ex_d['http']}")
        checks.add("D header: MS 2-1 for Portekiz-Norveç", tuple(ex_d.get("score") or ()) == (2, 1), str(ex_d.get("score")))
        checks.add("D data: İY 1-1 + goals 36' (0-1), 38' (1-1), 79' (2-1)",
                   tuple(ex_d.get("ht") or ()) == (1, 1) and [g.split(" ")[0] for g in ex_d.get("goals", [])] == ["36'", "38'", "79'"],
                   f"ht={ex_d.get('ht')} goals={ex_d.get('goals')}")
        checks.add("D stats box (Korner etc.)", "Korner" in ex_d["opta_stats"], json.dumps(ex_d["opta_stats"], ensure_ascii=False))
        checks.add("D referee + stadium", bool(ex_d.get("referee") and ex_d.get("stadium")), f"{ex_d.get('referee')} @ {ex_d.get('stadium')}", critical=False)

        # deep sample of finished matches across the window: B after FT + D coverage + A/D score cross-check
        finished = [r for r in rows_list if r["ft_home"] is not None and r["mackolik_match_id"] != EXAMPLE_MATCH_ID]
        sample = rng.sample(finished, min(args.sample, len(finished)))
        deep = []
        for r in sample:
            info = check_match(r["mackolik_match_id"], "sample")
            info["teams"] = f"{r['home_team']} - {r['away_team']}"
            info["league_code"] = r["league_code"]
            info["list_ft"] = (r["ft_home"], r["ft_away"])
            info["list_ht"] = (r["ht_home"], r["ht_away"]) if r["ht_home"] is not None else None
            info["score_mismatch_list_vs_D"] = info.get("data_score") is not None and tuple(info["data_score"]) != info["list_ft"]
            if r["event_code"]:
                res = client.get(H.odds_popup_path(r["event_code"]), save_as=f"B_popup_{r['event_code']}.json")
                try:
                    pop = parse_odds_popup(res.text)
                    add_catalog(pop)
                    info["B_markets_after_ft"] = len({o["market_id"] for o in pop["outcomes"]})
                    info["B_highlighted"] = sum(o["highlight"] for o in pop["outcomes"])
                    info["B_status"] = pop["match"] and pop["match"]["status"]
                except Exception as exc:  # noqa: BLE001
                    info["B_error"] = repr(exc)
            deep.append(info)
        facts["deep_sample"] = deep

        # past matches without a score in the list: what does D say? (postponed / abandoned -> void / unresolved)
        unscored = [r for r in rows_list if r["ft_home"] is None and r["date"] and r["date"] < today.isoformat()]
        facts["A_past_without_score"] = len(unscored)
        statuses = []
        for r in unscored[:6]:
            res = client.get(H.match_data_path(r["mackolik_match_id"]), referer=H.match_referer(r["mackolik_match_id"]),
                             save_as=f"D_data_{r['mackolik_match_id']}.json")
            try:
                md = parse_match_data(res.text)
                statuses.append({"match_id": r["mackolik_match_id"], "teams": f"{r['home_team']} - {r['away_team']}",
                                 "date": r["date"], "status": md["status"], "is_playing": md["is_playing"],
                                 "score_text": json.loads(res.text)["d"].get("s")})
            except Exception as exc:  # noqa: BLE001
                statuses.append({"match_id": r["mackolik_match_id"], "error": repr(exc)})
        facts["D_unscored_past_statuses"] = statuses
        n = len(deep) or 1
        facts["deep_sample_coverage"] = {
            "n": len(deep),
            "D_data_ok": sum("data_status" in d for d in deep),
            "D_has_ht": sum(bool(d.get("ht")) for d in deep),
            "D_has_goal_events_matching_score": sum(bool(d.get("events_goal_score_matches")) for d in deep),
            "D_opta_stats": sum(bool(d["opta_stats"]) for d in deep),
            "D_rb_stats": sum(bool(d["rb_stats"]) for d in deep),
            "D_any_corners": sum("Korner" in d["opta_stats"] or "Köşe Vuruşu" in d["rb_stats"] for d in deep),
            "D_referee": sum(bool(d.get("referee")) for d in deep),
            "B_after_ft_has_markets": sum(bool(d.get("B_markets_after_ft")) for d in deep),
            "score_mismatch_list_vs_D": sum(d["score_mismatch_list_vs_D"] for d in deep),
        }
        checks.add("D data endpoint works on sampled finished matches",
                   facts["deep_sample_coverage"]["D_data_ok"] >= 0.8 * n, json.dumps(facts["deep_sample_coverage"]))

    # ---------- outputs ----------
    with (out / "market_catalog.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["market_type_id", "market_name", "line", "matches_seen", "example_selections"])
        for (type_id, name), cnt in sorted(catalog.items(), key=lambda kv: (-kv[1], kv[0][1])):
            ex = catalog_examples[(type_id, name)]
            w.writerow([type_id, name, ex["line"], cnt, " | ".join(ex["selections"])])
    facts["market_catalog_size"] = len(catalog)
    facts["checks"] = checks.items
    (out / "summary.json").write_text(json.dumps(facts, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    md = ["# Phase 0 check results", "", f"Run at {facts['run_at_utc']}", "", "| Result | Check | Detail |", "|---|---|---|"]
    for c in checks.items:
        icon = "✅" if c["ok"] else ("❌" if c["critical"] else "⚠️")
        md.append(f"| {icon} | {c['check']} | {c['detail'][:300].replace('|', '/')} |")
    md += ["", "## Rolling window (endpoint A, np=0)", "", "| requested d | rows | sections |", "|---|---|---|"]
    for k, v in window.items():
        md.append(f"| {k} | {v['rows']} | {v['sections']} |")
    md += ["", f"d=-1, np=0 → {facts['A_d_minus1_np0']['rows']} rows; d=-1, np=1 → {facts['A_d_minus1_np1_rows']} rows; "
           f"week param ignored: {facts['A_week_param_ignored']}", "",
           "## Deep sample coverage", "", "```", json.dumps(facts["deep_sample_coverage"], indent=1), "```",
           "", "## Past matches without a score (D status)", "", "```",
           json.dumps(facts.get("D_unscored_past_statuses", []), ensure_ascii=False, indent=1), "```",
           "", f"Distinct Nesine markets seen: {len(catalog)} (see market_catalog.csv artifact)"]
    (out / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))

    if checks.failed_critical:
        print(f"\n{len(checks.failed_critical)} critical check(s) failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(1)
