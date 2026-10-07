"""The 26 leagues of config/leagues.yaml: lookup by new-site competition id and season labels."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import cache

import yaml

from .config import ROOT
from .schema import season_label

SPLIT_SEASON_START_MONTH = 7  # split-year seasons start in July/August (the 2019/20 COVID restart is a backfill matter)


@dataclass(frozen=True)
class Competition:
    league: dict
    competition_id: str
    special: bool  # e.g. Japan's 2026 "J1 100 Year Vision League"
    season: str | None  # fixed season for an extra competition


@cache
def leagues() -> tuple[dict, ...]:
    return tuple(yaml.safe_load((ROOT / "config" / "leagues.yaml").read_text(encoding="utf-8"))["leagues"])


@cache
def competitions() -> dict[str, Competition]:
    out = {}
    for lg in leagues():
        out[lg["mackolik"]["competition_id"]] = Competition(lg, lg["mackolik"]["competition_id"], False, None)
        for x in lg.get("extra") or []:
            out[x["competition_id"]] = Competition(lg, x["competition_id"], True, x["season"])
    return out


def season_for(comp: Competition, d: date) -> str:
    """Season label of a match played on d: '2024' (calendar-year) or '2024/25' (split-year)."""
    if comp.season:
        return comp.season
    lg = comp.league
    split_from = min(lg.get("split_from") or [9999])
    calendar = lg["calendar_year"] and not (d.year > split_from or (d.year == split_from and d.month >= SPLIT_SEASON_START_MONTH))
    if calendar:
        return str(d.year)
    return season_label(d.year if d.month >= SPLIT_SEASON_START_MONTH else d.year - 1, calendar=False)
