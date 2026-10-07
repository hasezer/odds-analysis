"""Data quality checks after every job -> data/quality.csv (appended; one row per check and scope).

status: ok | warn | fail. Checks (SCHEMA.md):
  duplicate_keys, orphan_rows, odds_range, market_sum, scores_present, events_match_score, popup_match, coverage
"""

from __future__ import annotations

from pathlib import Path


from . import store
from .catalog import OVERLAP
from .config import DATA
from .schema import TABLES
from .storage import append_log, read_log

ODDS_MIN, ODDS_MAX = 1.01, 1000
SUM_MIN = 1.00
SUM_MAX, SUM_MAX_MANY = 1.30, 1.70  # 2-3 selections / more selections (combos, İY/MS, scores have higher margins)
NO_SUM_FAMILIES = {"player", "special"}
MARKET = ["match_id", "market_type_id", "line", "handicap_home", "handicap_away"]


def _row(check: str, scope: str, status: str, value, detail: str = "") -> dict:
    return {"check": check, "scope": scope, "status": status, "value": value, "detail": detail[:500]}


def check_partition(season: str, league_id: str, root: Path = DATA) -> list[dict]:
    scope = f"{league_id} {season}"
    out = []
    t = {n: store.read(n, season=season, league_id=league_id, root=root)
         for n in ("matches", "odds", "settlements", "events", "stats")}
    markets = store.read("markets", root=root)

    for name, df in t.items():
        if df.empty:
            continue
        key = list(TABLES[name].key)
        dup = int(df.duplicated(subset=key).sum())
        out.append(_row("duplicate_keys", f"{scope} {name}", "fail" if dup else "ok", dup))

    ids = set(t["matches"]["match_id"]) if not t["matches"].empty else set()
    for name in ("odds", "settlements", "events", "stats"):
        df = t[name]
        if df.empty:
            continue
        orphans = int((~df["match_id"].isin(ids)).sum())
        if name in ("odds", "settlements"):
            orphans += int((~df["market_type_id"].isin(set(markets["market_type_id"]))).sum())
        out.append(_row("orphan_rows", f"{scope} {name}", "fail" if orphans else "ok", orphans,
                        "rows whose match or market does not exist"))

    o = t["odds"]
    if not o.empty:
        priced = o[o["odds"].notna()]
        bad = priced[(priced["odds"] < ODDS_MIN) | (priced["odds"] > ODDS_MAX)]
        out.append(_row("odds_range", scope, "fail" if len(bad) else "ok", len(bad), "odds outside 1.01-1000"))
        fam = markets.set_index("market_type_id")["family"]
        close = o[o["price_type"].isin(["closing_history", "closing_snapshot"])].copy()
        close["family"] = close["market_type_id"].map(fam)
        close = close[~close["family"].isin(NO_SUM_FAMILIES)]
        g = close.groupby(MARKET + ["price_type", "captured_at_utc"], dropna=False)["odds"]
        complete = g.apply(lambda s: s.notna().all() and len(s) > 1)
        overlap = close.groupby(MARKET + ["price_type", "captured_at_utc"], dropna=False)["market_key"].first() \
            .map(OVERLAP).fillna(1)
        sums = (g.apply(lambda s: (1 / s).sum()) / overlap)[complete]
        many = (g.size() > 3) | (overlap > 1)  # more selections, or double chance
        limit = many[complete].map({True: SUM_MAX_MANY, False: SUM_MAX})
        off = sums[(sums < SUM_MIN) | (sums > limit)]
        share = len(off) / len(sums) if len(sums) else 0
        out.append(_row("market_sum", scope, "warn" if len(off) else "ok", len(off),
                        f"{len(off)} of {len(sums)} complete markets outside 100-130 % (2-3 selections) / 100-170 % ({share:.1%})"))

    m = t["matches"]
    if not m.empty:
        fin = m[m["status"] == "finished"]
        missing = fin[fin[["ht_home", "ht_away", "ft_home", "ft_away"]].isna().any(axis=1)]
        out.append(_row("scores_present", scope, "fail" if len(missing) else "ok", len(missing),
                        "finished matches without HT or FT score: " + " ".join(missing["match_id"].head(10))))
        ev = t["events"]
        if not ev.empty:
            goals = ev[ev["event_type"].isin(["goal", "penalty_goal", "own_goal"]) & (ev["minute"] <= 90)]
            cnt = goals.groupby(["match_id", "team_side"]).size().unstack(fill_value=0)
            j = fin.set_index("match_id")[["ft_home", "ft_away"]].join(cnt, how="inner")
            for side in ("home", "away"):
                if side not in j:
                    j[side] = 0
            bad = j[(j["ft_home"] != j["home"]) | (j["ft_away"] != j["away"])]
            out.append(_row("events_match_score", scope, "warn" if len(bad) else "ok", len(bad),
                            "event goals != FT score: " + " ".join(bad.index[:10])))
        # coverage: share of finished matches with odds / events / stats
        n = len(fin)
        if n:
            for name in ("odds", "events", "stats"):
                have = fin["match_id"].isin(set(t[name]["match_id"])).sum() if not t[name].empty else 0
                out.append(_row(f"coverage_{name}", scope, "ok", round(have / n, 3), f"{have} of {n} finished matches"))
    return out


def popup_check(root: Path = DATA) -> dict:
    """Popups that showed another match (uuid or kickoff differs) are rejected at ingestion and logged."""
    log = read_log("failed_items", root)
    n = int((log["kind"] == "popup_mismatch").sum()) if not log.empty and "kind" in log else 0
    return _row("popup_match", "all", "warn" if n else "ok", n, "popups rejected because they showed another match")


def run_checks(partitions: list[tuple[str, str]], job: str, checked_at: str, root: Path = DATA) -> dict:
    rows = [r for s, lid in partitions for r in check_partition(s, lid, root)] + [popup_check(root)]
    append_log("quality", [{"checked_at_utc": checked_at, "job": job, **r} for r in rows], root)
    return {"checks": len(rows), "fail": sum(r["status"] == "fail" for r in rows),
            "warn": sum(r["status"] == "warn" for r in rows)}
