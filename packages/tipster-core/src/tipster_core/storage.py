"""DuckDB storage for the tipster.

One table today: ``matches`` — the normalised historical corpus produced by
the ingest layer. The schema mirrors the canonical column order produced by
``tipster_core.ingest.football_data.parse_matches_csv``.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl
from duckdb import DuckDBPyConnection

DEFAULT_DB_PATH = Path("data") / "tipster.duckdb"

#: (column name, DuckDB type) in canonical order. Odds columns are nullable:
#: column sets drift between seasons (ADR 0002).
MATCHES_COLUMNS: tuple[tuple[str, str], ...] = (
    ("league", "VARCHAR NOT NULL"),
    ("season", "VARCHAR NOT NULL"),
    ("date", "DATE NOT NULL"),
    ("home_team", "VARCHAR NOT NULL"),
    ("away_team", "VARCHAR NOT NULL"),
    ("home_goals", "INTEGER NOT NULL"),
    ("away_goals", "INTEGER NOT NULL"),
    ("odds_b365_h", "DOUBLE"),
    ("odds_b365_d", "DOUBLE"),
    ("odds_b365_a", "DOUBLE"),
    ("odds_pinnacle_h", "DOUBLE"),
    ("odds_pinnacle_d", "DOUBLE"),
    ("odds_pinnacle_a", "DOUBLE"),
    ("odds_avg_h", "DOUBLE"),
    ("odds_avg_d", "DOUBLE"),
    ("odds_avg_a", "DOUBLE"),
    ("odds_max_h", "DOUBLE"),
    ("odds_max_d", "DOUBLE"),
    ("odds_max_a", "DOUBLE"),
    ("odds_b365_c_h", "DOUBLE"),
    ("odds_b365_c_d", "DOUBLE"),
    ("odds_b365_c_a", "DOUBLE"),
    ("odds_pinnacle_c_h", "DOUBLE"),
    ("odds_pinnacle_c_d", "DOUBLE"),
    ("odds_pinnacle_c_a", "DOUBLE"),
    ("odds_avg_c_h", "DOUBLE"),
    ("odds_avg_c_d", "DOUBLE"),
    ("odds_avg_c_a", "DOUBLE"),
    ("odds_max_c_h", "DOUBLE"),
    ("odds_max_c_d", "DOUBLE"),
    ("odds_max_c_a", "DOUBLE"),
    ("source_file", "VARCHAR"),
    ("ingested_at", "TIMESTAMP DEFAULT current_timestamp"),
)

MATCHES_DDL = (
    "CREATE TABLE IF NOT EXISTS matches (\n    "
    + ",\n    ".join(f"{name} {sql_type}" for name, sql_type in MATCHES_COLUMNS)
    + "\n)"
)

#: Columns the ingest frame must provide (everything but the table default).
_FRAME_COLUMNS: tuple[str, ...] = tuple(
    name for name, _ in MATCHES_COLUMNS if name != "ingested_at"
)


def connect(
    db_path: str | Path = DEFAULT_DB_PATH, *, read_only: bool = False
) -> DuckDBPyConnection:
    """Open the tipster database, ensuring the schema in write mode.

    A path of ``":memory:"`` gives an ephemeral database (useful in tests).
    In read-only mode the schema is assumed to exist already.
    """
    path = str(db_path)
    if path != ":memory:" and not read_only:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(path, read_only=read_only)
    if not read_only:
        con.execute(MATCHES_DDL)
    return con


def replace_season(con: DuckDBPyConnection, matches: pl.DataFrame) -> int:
    """Idempotently write one (league, season) of matches.

    Existing rows for the frame's league and season are deleted first, so
    re-ingesting replaces rather than duplicates. Returns the row count
    written.
    """
    for required in ("league", "season"):
        if required not in matches.columns:
            msg = f"matches frame is missing column {required!r}"
            raise ValueError(msg)
    leagues = matches.get_column("league").unique().to_list()
    seasons = matches.get_column("season").unique().to_list()
    if len(leagues) != 1 or len(seasons) != 1:
        msg = "replace_season expects exactly one league and one season per frame"
        raise ValueError(msg)
    missing = [name for name in _FRAME_COLUMNS if name not in matches.columns]
    if missing:
        msg = f"matches frame is missing canonical columns: {missing}"
        raise ValueError(msg)

    con.execute("DELETE FROM matches WHERE league = ? AND season = ?", [leagues[0], seasons[0]])
    con.register("new_matches", matches)
    cols = ", ".join(f'"{name}"' for name in _FRAME_COLUMNS)
    try:
        con.execute(f"INSERT INTO matches ({cols}) SELECT {cols} FROM new_matches")
    finally:
        con.unregister("new_matches")
    return matches.height


def match_counts(con: DuckDBPyConnection) -> list[tuple[str, str, int]]:
    """Row counts per (league, season), ordered — the coverage view."""
    rows = con.execute(
        "SELECT league, season, count(*) AS matches"
        " FROM matches GROUP BY ALL ORDER BY league, season"
    ).fetchall()
    return [(str(r[0]), str(r[1]), int(r[2])) for r in rows]


def recent_matches(con: DuckDBPyConnection, n: int = 20) -> pl.DataFrame:
    """The *n* most recent matches with core columns, as a polars frame."""
    return con.execute(
        "SELECT league, season, date, home_team, away_team, home_goals, away_goals"
        " FROM matches ORDER BY date DESC, league LIMIT ?",
        [n],
    ).pl()
