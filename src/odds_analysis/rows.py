"""Turn parsed responses into table rows (matches, odds, unmapped markets)."""

from __future__ import annotations

from .config import iso, kickoff_utc
from .markets import normalize_market, normalize_selection
from .storage import append_log, read_log


def match_row(r: dict, seen_utc: str) -> dict:
    """Row of endpoint A/C -> data/matches row."""
    ko = kickoff_utc(r["date"], r["kickoff_local"]) if r.get("date") and r.get("kickoff_local") else None
    ms = next((m for m in r["markets"] if m["market"] == "Maç Sonucu"), None)
    return {
        "match_id": r["mackolik_match_id"],
        "event_code": r["event_code"],
        "date": r["date"],
        "kickoff_local": r["kickoff_local"],
        "kickoff_utc": iso(ko) if ko else None,
        "league_code": r["league_code"],
        "league_id": r["league_id"],
        "mbs": r["mbs"],
        "home_team_id": r["home_team_id"],
        "home_team": r["home_team"],
        "away_team_id": r["away_team_id"],
        "away_team": r["away_team"],
        "code_1x2": ms["list_code"] if ms else None,
        "first_seen_utc": seen_utc,
        "last_seen_utc": seen_utc,
    }


def odds_rows(popup: dict, *, event_code: str, match_id: int, snapshot_utc: str,
              home: str | None, away: str | None, unmapped: dict[str, dict]) -> list[dict]:
    """Parsed B popup -> one row per Nesine selection. Unknown markets are collected in `unmapped`."""
    out = []
    for o in popup["outcomes"]:
        mk = normalize_market(o["market_name"])
        if mk is None:
            u = unmapped.setdefault(o["market_name"], {
                "first_seen_utc": snapshot_utc, "market_tr": o["market_name"],
                "market_type_id": o["market_type_id"], "example_event_code": event_code, "selections": []})
            if len(u["selections"]) < 10 and o["selection"] not in u["selections"]:
                u["selections"].append(o["selection"])
        out.append({
            "event_code": event_code,
            "match_id": match_id,
            "snapshot_utc": snapshot_utc,
            "market_id": o["market_id"],
            "market_type_id": o["market_type_id"],
            "market_tr": o["market_name"],
            "market_key": mk.key if mk else None,
            "line": o["line"] if o["line"] is not None else (mk.line if mk else None),
            "family": mk.family if mk else None,
            "selection_tr": o["selection"],
            "selection": normalize_selection(mk, o["selection"], home, away) if mk else None,
            "odds": o["odds"],
            "mbs": o["mbs"],
        })
    return out


def log_unmapped(unmapped: dict[str, dict]) -> int:
    """Append markets not seen before to data/unmapped_markets.csv."""
    known = set(read_log("unmapped_markets").get("market_tr", []))
    rows = [{**u, "selections": " | ".join(u["selections"])} for name, u in unmapped.items() if name not in known]
    append_log("unmapped_markets", rows)
    return len(rows)
