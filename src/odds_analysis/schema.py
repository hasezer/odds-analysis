"""The agreed data structure (SCHEMA.md) as code: tables, columns, types, allowed values, keys, partitioning.

Every writer goes through store.py, which validates rows against these definitions. Change a table here AND in
SCHEMA.md together, and bump SCHEMA_VERSION.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SCHEMA_VERSION = 1

# column types: string, int, float, bool, ts (UTC timestamp), list (list of strings)


@dataclass(frozen=True)
class Col:
    name: str
    type: str = "string"
    required: bool = False  # NOT NULL
    enum: tuple[str, ...] | None = None
    doc: str = ""


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[Col, ...]
    key: tuple[str, ...]
    # "single": data/<table>/part-*.parquet; "history": data/<table>/season=<s>/league=<id>/part-*.parquet;
    # "snapshot": like history, snapshot rows additionally under date=YYYY-MM-DD/ (see store.partition_dir)
    partition: str
    doc: str = ""
    derived: bool = False
    meta: tuple[Col, ...] = field(default=(
        Col("schema_version", "int", True, doc="SCHEMA_VERSION used to write the row"),
        Col("ingested_at_utc", "ts", True, doc="when the row was first written (kept while the row is unchanged)"),
    ))

    @property
    def all_columns(self) -> tuple[Col, ...]:
        return self.columns + self.meta

    def col(self, name: str) -> Col:
        return next(c for c in self.all_columns if c.name == name)


SEASON_FORMAT = ("split", "calendar")
SEASON_TYPE = ("regular", "playoff", "special")
MATCH_STATUS = ("scheduled", "finished", "postponed", "cancelled", "abandoned", "pending")
FAMILY = ("result", "goals", "halves", "handicap", "combo", "corners", "cards", "player", "special")
SETTLE_SOURCE = ("official", "engine", "none")
PRICE_TYPE = ("closing_history", "opening_snapshot", "intraday_snapshot", "closing_snapshot")
SNAPSHOT_PRICE_TYPES = ("opening_snapshot", "intraday_snapshot", "closing_snapshot")
SOURCE = ("arsiv", "new")
SETTLE_STATUS = ("settled", "void", "pending", "unsettleable", "unverified")
SETTLE_BASIS = ("official", "engine")
SIDE = ("home", "away")
EVENT_TYPE = ("goal", "penalty_goal", "own_goal", "missed_penalty", "yellow", "second_yellow", "red", "sub_in", "sub_out")
STATS_SOURCE = ("opta", "rb", "new")
JOB = ("snapshot", "results", "backfill", "analysis")
RUN_STATUS = ("ok", "partial", "failed")

TABLES: dict[str, Table] = {t.name: t for t in (
    Table("leagues", (
        Col("league_id", required=True, doc="ours: <country>-<tier>, e.g. TUR-1"),
        Col("name_en", required=True), Col("name_tr", required=True), Col("country", required=True),
        Col("tier", "int", True),
        Col("mackolik_new_id", required=True, doc="competition id on www.mackolik.com"),
        Col("arsiv_code", doc="league code in the arsiv iddaa list (NULL until seen)"),
        Col("arsiv_league_id"),
        Col("season_format", required=True, enum=SEASON_FORMAT),
        Col("active", "bool", True),
    ), key=("league_id",), partition="single", doc="the 26 leagues (from config/leagues.yaml)"),

    Table("teams", (
        Col("team_id", required=True, doc="ours: <country>-<ASCII slug of the Mackolik name>, never reused"),
        Col("name_tr", required=True), Col("name_en"),
        Col("mackolik_new_id"), Col("arsiv_team_id"), Col("country"),
        Col("aliases", "list", doc="other names Mackolik used for the team"),
    ), key=("team_id",), partition="single"),

    Table("matches", (
        Col("match_id", required=True, doc="www.mackolik.com match uuid"),
        Col("iddaa_event_code"), Col("arsiv_match_id"),
        Col("league_id", required=True), Col("season", required=True),
        Col("season_type", required=True, enum=SEASON_TYPE), Col("round"),
        Col("kickoff_utc", "ts", True), Col("kickoff_local_tr", required=True, doc="Turkey time, ISO with +03:00"),
        Col("home_team_id", required=True), Col("away_team_id", required=True),
        Col("status", required=True, enum=MATCH_STATUS),
        Col("ht_home", "int"), Col("ht_away", "int"), Col("ft_home", "int"), Col("ft_away", "int"),
        Col("et_home", "int"), Col("et_away", "int"), Col("pen_home", "int"), Col("pen_away", "int"),
        Col("referee"), Col("stadium"),
    ), key=("match_id",), partition="history"),

    Table("markets", (
        Col("market_type_id", required=True, doc="Nesine market type id (popup market_type_id)"),
        Col("market_key", doc="English key without the line, e.g. OU, CORNERS_OU; NULL = not mapped yet"),
        Col("name_tr", required=True, doc="Nesine name (with the line for per-line types, e.g. '2,5 Alt/Üst')"),
        Col("family", enum=FAMILY), Col("has_line", "bool", True),
        Col("settle_source", required=True, enum=SETTLE_SOURCE),
        Col("first_seen_season"),
    ), key=("market_type_id",), partition="single"),

    Table("odds", (
        Col("match_id", required=True), Col("market_type_id", required=True), Col("market_key"),
        Col("line", "float"), Col("handicap_home", "int"), Col("handicap_away", "int"),
        Col("selection_key", required=True),
        Col("selection_name_tr", doc="Nesine's name; NULL for its unnamed placeholder selections ('-')"),
        Col("odds", "float", doc="decimal, 2 dp; NULL = selection offered without a price"),
        Col("mbs", "int"),
        Col("price_type", required=True, enum=PRICE_TYPE),
        Col("captured_at_utc", "ts", doc="NULL for closing_history (time of the last price change is unknown)"),
        Col("minutes_before_kickoff", "int"),
        Col("source", required=True, enum=SOURCE),
    ), key=("match_id", "market_type_id", "line", "handicap_home", "handicap_away", "selection_key", "price_type",
            "captured_at_utc"), partition="snapshot"),

    Table("settlements", (
        Col("match_id", required=True), Col("market_type_id", required=True), Col("line", "float"),
        Col("handicap_home", "int"), Col("handicap_away", "int"), Col("selection_key", required=True),
        Col("hit_official", "bool"), Col("hit_engine", "bool"), Col("hit", "bool"),
        Col("status", required=True, enum=SETTLE_STATUS), Col("settle_basis", enum=SETTLE_BASIS),
        Col("settled_at_utc", "ts", True),
    ), key=("match_id", "market_type_id", "line", "handicap_home", "handicap_away", "selection_key"),
        partition="history"),

    Table("events", (
        Col("match_id", required=True), Col("event_order", "int", True),
        Col("minute", "int"), Col("added_minute", "int"), Col("team_side", enum=SIDE),
        Col("event_type", required=True, enum=EVENT_TYPE),
        Col("player_name"), Col("assist_name"), Col("score_after", doc="after goals, e.g. '2-1'"),
    ), key=("match_id", "event_order"), partition="history"),

    Table("stats", (
        Col("match_id", required=True), Col("team_side", required=True, enum=SIDE),
        Col("corners", "int"), Col("yellow_cards", "int"), Col("red_cards", "int"), Col("second_yellows", "int"),
        Col("shots", "int"), Col("shots_on_target", "int"), Col("possession_pct", "float"),
        Col("fouls", "int"), Col("offsides", "int"), Col("crosses", "int"),
        Col("stats_source", required=True, enum=STATS_SOURCE),
    ), key=("match_id", "team_side"), partition="history"),

    Table("runs", (
        Col("run_id", required=True), Col("job", required=True, enum=JOB),
        Col("started_at_utc", "ts", True), Col("finished_at_utc", "ts"),
        Col("status", required=True, enum=RUN_STATUS),
        Col("requests", "int"), Col("errors", "int"), Col("matches_saved", "int"), Col("notes"),
    ), key=("run_id",), partition="single"),

    Table("analysis_flat", (
        Col("match_id", required=True), Col("league_id", required=True), Col("season", required=True),
        Col("season_type", required=True, enum=SEASON_TYPE),
        Col("kickoff_utc", "ts", True), Col("home_team_id"), Col("away_team_id"),
        Col("home_team_tr"), Col("away_team_tr"),
        Col("ht_home", "int"), Col("ht_away", "int"), Col("ft_home", "int"), Col("ft_away", "int"),
        Col("corners_total", "int"), Col("yellow_cards_total", "int"), Col("red_cards_total", "int"),
        Col("market_type_id", required=True), Col("market_key"), Col("market_name_tr"), Col("family", enum=FAMILY),
        Col("line", "float"), Col("handicap_home", "int"), Col("handicap_away", "int"),
        Col("selection_key", required=True), Col("selection_name_tr"),
        Col("closing_odds", "float"), Col("closing_source", enum=("closing_snapshot", "closing_history")),
        Col("opening_odds", "float"), Col("odds_movement_pct", "float"),
        Col("implied_prob", "float"), Col("fair_prob", "float"), Col("market_margin", "float"),
        Col("hit", "bool"), Col("status", enum=SETTLE_STATUS),
        Col("in_default_analysis", "bool", True,
            doc="false for season_type=special, card markets (until Kart Puanı is confirmed), unsettleable rows"),
    ), key=("match_id", "market_type_id", "line", "handicap_home", "handicap_away", "selection_key"),
        partition="history", derived=True,
        doc="one row per match x market x selection Nesine offered; rebuilt from the tables above, never edited"),
)}


def season_label(start_year: int, calendar: bool) -> str:
    """'2024' for calendar-year leagues, '2024/25' for split-year leagues."""
    return str(start_year) if calendar else f"{start_year}/{str(start_year + 1)[2:]}"


def season_path(season: str) -> str:
    """'2024/25' -> '2024-25' (a '/' can't be part of a directory name); '2024' unchanged."""
    return season.replace("/", "-")
