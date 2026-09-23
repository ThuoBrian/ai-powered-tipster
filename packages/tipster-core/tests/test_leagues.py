"""Tests for league and season identifiers."""

from __future__ import annotations

from datetime import date

import pytest

from tipster_core.leagues import (
    BIG_5,
    LeagueCode,
    season_code,
    season_from_date,
    season_label,
    validate_season,
)


def test_season_code_matches_source_format() -> None:
    assert season_code(2025) == "2526"
    assert season_code(2024) == "2425"
    assert season_code(1999) == "9900"


def test_season_label_roundtrip() -> None:
    assert season_label("2526") == "2025/26"
    assert season_label(season_code(2024)) == "2024/25"


@pytest.mark.parametrize("bad", ["", "2527", "2025", "252", "abcd", "2528"])
def test_invalid_season_codes_raise(bad: str) -> None:
    with pytest.raises(ValueError, match="invalid season"):
        validate_season(bad)


def test_league_lookup_is_case_insensitive() -> None:
    assert LeagueCode.from_code("e0") is LeagueCode.PREMIER_LEAGUE
    assert LeagueCode.from_code(" sp1 ").label == "La Liga"


def test_unknown_league_codes_raise() -> None:
    with pytest.raises(ValueError, match="unknown league"):
        LeagueCode.from_code("XX")


def test_big_5_contents() -> None:
    assert len(BIG_5) == 5
    assert LeagueCode.PREMIER_LEAGUE in BIG_5
    assert LeagueCode.EREDIVISIE not in BIG_5


def test_season_from_date_mid_season() -> None:
    assert season_from_date(date(2026, 1, 15)) == "2526"


def test_season_from_date_july_cutoff() -> None:
    assert season_from_date(date(2025, 7, 1)) == "2526"
    assert season_from_date(date(2025, 6, 30)) == "2425"
