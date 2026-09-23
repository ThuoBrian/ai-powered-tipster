"""Tests for DuckDB storage (all against an ephemeral in-memory database)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl
import pytest

from tipster_core.ingest.football_data import parse_matches_csv
from tipster_core.leagues import LeagueCode
from tipster_core.storage import (
    MATCHES_COLUMNS,
    connect,
    league_summary,
    load_match_results,
    match_counts,
    recent_matches,
    replace_season,
)

PL = LeagueCode.PREMIER_LEAGUE


def test_replace_season_is_idempotent(modern_csv: bytes) -> None:
    frame = parse_matches_csv(modern_csv, PL, "2526")
    con = connect(":memory:")
    try:
        assert replace_season(con, frame) == 3
        assert replace_season(con, frame) == 3  # replaces, never duplicates
        assert match_counts(con) == [("E0", "2526", 3)]
    finally:
        con.close()


def test_recent_matches_shape_and_order(modern_csv: bytes) -> None:
    frame = parse_matches_csv(modern_csv, PL, "2526")
    con = connect(":memory:")
    try:
        replace_season(con, frame)
        recent = recent_matches(con, n=2)
        assert recent.height == 2
        assert recent.columns == [
            "league",
            "season",
            "date",
            "home_team",
            "away_team",
            "home_goals",
            "away_goals",
        ]
        dates = recent.get_column("date").to_list()
        assert dates == sorted(dates, reverse=True)
    finally:
        con.close()


def test_league_summary_one_row_per_league(modern_csv: bytes, legacy_csv: bytes) -> None:
    con = connect(":memory:")
    try:
        replace_season(con, parse_matches_csv(modern_csv, PL, "2526"))
        replace_season(con, parse_matches_csv(legacy_csv, PL, "0809"))
        replace_season(con, parse_matches_csv(modern_csv, LeagueCode.LA_LIGA, "2526"))
        summary = league_summary(con)
    finally:
        con.close()
    rows = {row["league"]: row for row in summary.iter_rows(named=True)}
    assert set(rows) == {"E0", "SP1"}
    assert (rows["E0"]["seasons"], rows["E0"]["matches"]) == (2, 5)
    assert rows["E0"]["last_date"] == rows["SP1"]["last_date"]
    assert rows["E0"]["last_ingest"] is not None


def test_recent_matches_league_filter(modern_csv: bytes) -> None:
    con = connect(":memory:")
    try:
        replace_season(con, parse_matches_csv(modern_csv, PL, "2526"))
        replace_season(con, parse_matches_csv(modern_csv, LeagueCode.LA_LIGA, "2526"))
        only_spain = recent_matches(con, n=10, leagues=[LeagueCode.LA_LIGA])
    finally:
        con.close()
    assert set(only_spain["league"]) == {"SP1"}
    assert only_spain.height == 3


def test_load_match_results_round_trips_odds(modern_csv: bytes) -> None:
    frame = parse_matches_csv(modern_csv, PL, "2526")
    con = connect(":memory:")
    try:
        replace_season(con, frame)
        results = load_match_results(con, leagues=[PL])
    finally:
        con.close()

    assert len(results) == 3
    arsenal = next(r for r in results if r.home_team == "Arsenal")
    assert arsenal.odds is not None
    assert arsenal.odds.b365 is not None
    assert arsenal.odds.b365.home == pytest.approx(1.85)

    # Man City's row has zero-marker (missing) B365 odds but real Pinnacle
    # odds — the MatchOdds group is present, just with one source null.
    city = next(r for r in results if r.home_team == "Man City")
    assert city.odds is not None
    assert city.odds.b365 is None
    assert city.odds.pinnacle is not None


def test_load_match_results_odds_none_when_no_source_present(legacy_csv: bytes) -> None:
    frame = parse_matches_csv(legacy_csv, PL, "0809")  # no odds columns in the source at all
    con = connect(":memory:")
    try:
        replace_season(con, frame)
        results = load_match_results(con, leagues=[PL])
    finally:
        con.close()
    assert results and all(result.odds is None for result in results)


def test_database_from_before_neutral_venues_still_works(modern_csv: bytes, tmp_path: Path) -> None:
    db = tmp_path / "old.duckdb"
    old_columns = [(n, t) for n, t in MATCHES_COLUMNS if n != "neutral"]
    raw = duckdb.connect(str(db))
    raw.execute("CREATE TABLE matches (" + ", ".join(f"{n} {t}" for n, t in old_columns) + ")")
    frame = parse_matches_csv(modern_csv, PL, "2526").drop("neutral")
    raw.register("old_rows", frame)
    names = ", ".join(n for n, _ in old_columns if n != "ingested_at")
    raw.execute(f"INSERT INTO matches ({names}) SELECT {names} FROM old_rows")
    raw.close()

    # Read-only (the dashboard) can't migrate, so reads default neutral to False.
    con = connect(db, read_only=True)
    try:
        assert all(not r.neutral for r in load_match_results(con))
    finally:
        con.close()

    # Any write-mode open adds the column in place.
    con = connect(db)
    try:
        assert len(load_match_results(con)) == 3
        replace_season(con, parse_matches_csv(modern_csv, PL, "2526"))
        assert match_counts(con) == [("E0", "2526", 3)]
    finally:
        con.close()


def test_replace_season_rejects_mixed_frames() -> None:
    con = connect(":memory:")
    try:
        mixed = pl.DataFrame({"league": ["E0", "SP1"], "season": ["2526", "2526"]})
        with pytest.raises(ValueError, match="exactly one league"):
            replace_season(con, mixed)
    finally:
        con.close()


def test_replace_season_requires_canonical_columns() -> None:
    con = connect(":memory:")
    try:
        with pytest.raises(ValueError, match="missing canonical columns"):
            replace_season(con, pl.DataFrame({"league": ["E0"], "season": ["2526"]}))
    finally:
        con.close()
