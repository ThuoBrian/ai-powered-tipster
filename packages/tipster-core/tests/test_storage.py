"""Tests for DuckDB storage (all against an ephemeral in-memory database)."""

from __future__ import annotations

import polars as pl
import pytest

from tipster_core.ingest.football_data import parse_matches_csv
from tipster_core.leagues import LeagueCode
from tipster_core.storage import connect, match_counts, recent_matches, replace_season

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
